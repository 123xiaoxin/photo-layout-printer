"""Negotiate physical media using the selected Windows queue and its actual ports."""
from dataclasses import dataclass

from .specifications import (
    DC_PAPERS, DC_PAPERNAMES, DC_PAPERSIZE, DM_ORIENTATION, DM_PAPERSIZE,
    DM_PAPERWIDTH, DM_PAPERLENGTH, DMORIENT_LANDSCAPE, DMORIENT_PORTRAIT,
)

DC_FIELDS = 1
DM_SCALE = 0x10
DM_FORMNAME = 0x10000


@dataclass(frozen=True)
class DriverPaper:
    code: int
    name: str
    size_mm: tuple


def read_supported_media(printer_name):
    import win32print as spool
    from pywintypes import error as WinError

    try:
        handle = spool.OpenPrinter(printer_name)
    except WinError:
        return [], None
    try:
        try:
            info = spool.GetPrinter(handle, 2)
        except WinError:
            info = spool.GetPrinter(handle, 5)
        raw_port = info.get("pPortName") or ""
        # PRINTER_INFO_2 allows multiple comma-separated ports on a pooled queue.
        ports = dict.fromkeys(port.strip() for port in raw_port.split(",") if port.strip())
        fields = None
        for port in ports:
            def query(cap):
                try:
                    return spool.DeviceCapabilities(printer_name, port, cap, info.get("pDevMode"))
                except (WinError, OSError, ValueError):
                    return None

            mask = query(DC_FIELDS)
            if isinstance(mask, int) and mask >= 0:
                fields = mask
            names = query(DC_PAPERNAMES)
            sizes = query(DC_PAPERSIZE)
            codes = query(DC_PAPERS)
            names = names if isinstance(names, (list, tuple)) else ()
            sizes = sizes if isinstance(sizes, (list, tuple)) else ()
            codes = codes if isinstance(codes, (list, tuple)) else ()
            # Never join differently sized arrays by index.
            if sizes and (len(codes) == len(sizes) or len(names) == len(sizes)):
                papers = []
                for i, size in enumerate(sizes):
                    width, height = size["x"] / 10, size["y"] / 10
                    if min(width, height) > 0:
                        papers.append(DriverPaper(codes[i] if len(codes) == len(sizes) else 0,
                                                  names[i] if len(names) == len(sizes) else "",
                                                  (width, height)))
                if papers:
                    return papers, fields
            # Some drivers publish names without codes or DC_PAPERSIZE. EnumForms also
            # includes server forms: use only names explicitly reported by this queue.
            if names:
                try:
                    forms = spool.EnumForms(handle)
                except WinError:
                    forms = []
                advertised = {name.casefold(): codes[i] if len(names) == len(codes) else 0
                              for i, name in enumerate(names)}
                papers = [DriverPaper(advertised[f["Name"].casefold()], f["Name"],
                                      (f["Size"]["cx"] / 1000, f["Size"]["cy"] / 1000))
                          for f in forms if f["Name"].casefold() in advertised]
                if papers:
                    return papers, fields
        return [], fields
    except WinError:
        return [], None
    finally:
        spool.ClosePrinter(handle)


def match_paper(papers, target, preferred_code=0):
    candidates = []
    for form in papers:
        # DC_PAPERSIZE describes DMORIENT_PORTRAIT, even for native-wide stock.
        for swapped, size in ((False, form.size_mm), (True, form.size_mm[::-1])):
            delta = tuple(abs(a - b) for a, b in zip(target, size))
            if max(delta) <= 3 and sum(delta) <= 4:
                candidates.append((sum(delta), swapped, form))
    if not candidates:
        return None
    score, swapped, paper = min(candidates, key=lambda item: (
        item[0], bool(preferred_code and item[2].code != preferred_code), item[1]))
    return {"code": paper.code, "name": paper.name, "paper_mm": paper.size_mm,
            "score": score, "swapped": swapped, "orientation_rank": int(swapped)}


def media_requests(match, fields):
    def supports(mask):
        return fields is None or (fields & mask) == mask

    if match:
        if match["code"] and supports(DM_PAPERSIZE):
            yield "code"
        # dmFormName is 32 UTF-16 code units including its terminator.
        if match["name"] and len(match["name"].encode("utf-16-le")) < 64 and supports(DM_FORMNAME):
            yield "form"
    if supports(DM_PAPERWIDTH | DM_PAPERLENGTH):
        yield "dimensions"


def driver_substituted_size(mode, catalog, target, has_form_name):
    """DocumentProperties may succeed while substituting a different paper size."""
    fields = mode.dmFields
    dimensions = DM_PAPERWIDTH | DM_PAPERLENGTH
    if fields & dimensions == dimensions and min(mode.dmPaperWidth, mode.dmPaperLength) > 0:
        size = (mode.dmPaperWidth / 10, mode.dmPaperLength / 10)
    elif fields & DM_PAPERSIZE and mode.dmPaperSize:
        # dmPaperSize is signed short; DC_PAPERS returns an unsigned WORD.
        size = next((p.size_mm for p in catalog if p.code == mode.dmPaperSize & 0xffff), None)
    elif has_form_name and fields & DM_FORMNAME and mode.dmFormName:
        size = next((p.size_mm for p in catalog if p.name.casefold() == mode.dmFormName.casefold()), None)
    else:
        size = None
    return size is not None and max(abs(a - b) for a, b in zip(sorted(size), sorted(target))) > 3


def apply_media_request(mode, target, match, fields, request, has_form_name=True):
    width, height = target
    if request == "form" and not has_form_name:
        raise ValueError("驱动 DEVMODE 未提供纸型名称字段")
    # Remove all conflicting default selectors, including the stale string some
    # drivers consult even when DM_FORMNAME is unset. Preserve private driver data.
    mode.dmFields &= ~(DM_FORMNAME | DM_PAPERSIZE | DM_PAPERWIDTH | DM_PAPERLENGTH)
    if has_form_name:
        mode.dmFormName = ""
    mode.dmPaperSize = mode.dmPaperWidth = mode.dmPaperLength = 0
    if request in ("code", "form"):
        turn = match["swapped"]
        if request == "code":
            mode.dmPaperSize = match["code"]
            mode.dmFields |= DM_PAPERSIZE
        else:
            mode.dmFormName = match["name"]
            mode.dmFields |= DM_FORMNAME
        label = match["name"] or f"{match['paper_mm'][0]:g} × {match['paper_mm'][1]:g} mm"
        note = f"驱动纸张：{label}"
    else:
        # DEVMODEW specifies dmPaperSize == 0 for an explicit length + width.
        short, long = sorted((round(width * 10), round(height * 10)))
        mode.dmPaperWidth, mode.dmPaperLength = short, long
        mode.dmFields |= DM_PAPERWIDTH | DM_PAPERLENGTH
        turn = width > height
        note = "自定义纸张"
    if fields is None or fields & DM_ORIENTATION:
        mode.dmOrientation = DMORIENT_LANDSCAPE if turn else DMORIENT_PORTRAIT
        mode.dmFields |= DM_ORIENTATION
    if mode.dmFields & DM_SCALE:
        mode.dmScale = 100
    return f"{note} · 目标 {width:g} × {height:g} mm"
