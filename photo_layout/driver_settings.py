"""Per-job Windows driver settings, including opaque manufacturer private data.

No API in this module writes a Windows printer default or submits a print job.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
import struct
from types import SimpleNamespace

from .printer_forms import (apply_media_request, driver_substituted_size, match_paper,
                            media_requests, read_supported_media, DM_SCALE)
from .specifications import DM_IN_BUFFER, DM_OUT_BUFFER, GMEM_MOVEABLE, GMEM_ZEROINIT

DM_IN_PROMPT = 4
MAX_DEVMODE_BYTES = 2 * 1024 * 1024


class DriverSettingsError(ValueError):
    """An explicit saved setting must not silently fall back to printer defaults."""


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        *[(name, ctypes.c_short) for name in (
            "dmOrientation", "dmPaperSize", "dmPaperLength", "dmPaperWidth", "dmScale",
            "dmCopies", "dmDefaultSource", "dmPrintQuality", "dmColor", "dmDuplex",
            "dmYResolution", "dmTTOption", "dmCollate")],
        ("dmFormName", ctypes.c_wchar * 32),
    ]


def parse_devmode(blob):
    """Validate a complete UTF-16 DEVMODEW without interpreting its private bytes."""
    if not isinstance(blob, bytes) or not 86 <= len(blob) <= MAX_DEVMODE_BYTES:
        raise DriverSettingsError("打印机页面设置数据长度无效，请重新保存设置")
    spec, version, size, extra, fields = struct.unpack_from("<HHHHI", blob, 64)
    if size < 86 or size + extra != len(blob):
        raise DriverSettingsError("打印机页面设置数据不完整，请重新保存设置")
    values = struct.unpack_from("<hhhhh", blob, 76)
    form = blob[102:166].decode("utf-16-le", errors="replace").split("\0", 1)[0] if size >= 166 else ""
    return SimpleNamespace(dmSpecVersion=spec, dmDriverVersion=version, dmSize=size,
                           dmDriverExtra=extra, dmFields=fields, dmOrientation=values[0],
                           dmPaperSize=values[1], dmPaperLength=values[2],
                           dmPaperWidth=values[3], dmScale=values[4], dmFormName=form)


def _buffer_blob(buffer, capacity):
    if capacity < 86 or capacity > MAX_DEVMODE_BYTES:
        raise DriverSettingsError("驱动返回的打印设置缓冲区长度无效")
    head = ctypes.string_at(buffer, 86)
    size, extra = struct.unpack_from("<HH", head, 68)
    total = size + extra
    if size < 86 or total > capacity:
        raise DriverSettingsError("驱动返回的打印设置超出缓冲区")
    blob = ctypes.string_at(buffer, total)
    parse_devmode(blob)
    return blob


def _global_memory():
    kernel = ctypes.windll.kernel32
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalUnlock.restype = wintypes.BOOL
    kernel.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalSize.restype = ctypes.c_size_t
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.restype = wintypes.HGLOBAL
    return kernel


def devmode_from_handle(handle):
    if not handle:
        raise DriverSettingsError("驱动未返回确认后的打印机页面设置")
    kernel = _global_memory()
    capacity = kernel.GlobalSize(handle)
    ptr = kernel.GlobalLock(handle)
    if not ptr:
        raise OSError("无法读取打印机页面设置")
    try:
        return _buffer_blob(ptr, capacity)
    finally:
        kernel.GlobalUnlock(handle)


def devmode_handle(blob):
    parse_devmode(blob)
    kernel = _global_memory()
    handle = kernel.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(blob))
    if not handle:
        raise OSError("无法分配打印机页面设置内存")
    ptr = kernel.GlobalLock(handle)
    if not ptr:
        kernel.GlobalFree(handle)
        raise OSError("无法锁定打印机页面设置内存")
    ctypes.memmove(ptr, blob, len(blob))
    kernel.GlobalUnlock(handle)
    return handle


_file_signatures = {}


def _driver_file_signature(path):
    if not path:
        return ""
    stat = os.stat(path)
    key = (os.path.normcase(path), stat.st_size, stat.st_mtime_ns)
    if key not in _file_signatures:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        _file_signatures[key] = {"name": os.path.basename(path).casefold(),
                                 "bytes": stat.st_size, "sha256": digest.hexdigest()}
    return _file_signatures[key].copy()


def driver_identity(queue):
    """Fingerprint the actual queue driver, rather than the editable queue label."""
    import win32print
    class DRIVER_INFO_2(ctypes.Structure):
        _fields_ = [("cVersion", wintypes.DWORD), *[(name, wintypes.LPWSTR) for name in
                    ("pName", "pEnvironment", "pDriverPath", "pDataFile", "pConfigFile")]]
    query = ctypes.WinDLL("winspool.drv", use_last_error=True).GetPrinterDriverW
    query.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    handle = win32print.OpenPrinter(queue)
    try:
        needed = wintypes.DWORD()
        query(int(handle), None, 2, None, 0, ctypes.byref(needed))
        if not needed.value or needed.value > MAX_DEVMODE_BYTES:
            raise OSError("无法读取打印机驱动标识")
        buffer = ctypes.create_string_buffer(needed.value)
        if not query(int(handle), None, 2, buffer, needed.value, ctypes.byref(needed)):
            raise OSError("无法读取打印机驱动标识")
        driver = DRIVER_INFO_2.from_buffer(buffer)
        return {"name": driver.pName or "", "environment": driver.pEnvironment or "",
                "version": driver.cVersion,
                "files": {name: _driver_file_signature(getattr(driver, "p" + name))
                          for name in ("DriverPath", "DataFile", "ConfigFile")}}
    finally:
        win32print.ClosePrinter(handle)


class DriverSession:
    """Keep a queue open while negotiating job-only settings with its driver."""
    def __init__(self, queue, owner=None):
        self.queue, self.owner = queue, owner
        self.spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
        self.spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
        self.spool.OpenPrinterW.restype = wintypes.BOOL
        self.spool.ClosePrinter.argtypes = [wintypes.HANDLE]
        self.spool.ClosePrinter.restype = wintypes.BOOL
        self.spool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
                                                  ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        self.spool.DocumentPropertiesW.restype = ctypes.c_long
        self.handle = wintypes.HANDLE()

    def __enter__(self):
        if not self.spool.OpenPrinterW(self.queue, ctypes.byref(self.handle), None):
            raise OSError(f"无法打开打印机 {self.queue}")
        try:
            self.capacity = self._call(None, None, 0)
            if not 86 <= self.capacity <= MAX_DEVMODE_BYTES:
                raise DriverSettingsError("驱动返回的页面设置长度无效")
            buffer = ctypes.create_string_buffer(self.capacity)
            if self._call(buffer, None, DM_OUT_BUFFER) != 1:
                raise OSError("无法读取打印机默认页面设置")
            self.default = _buffer_blob(buffer, self.capacity)
            return self
        except Exception:
            self.spool.ClosePrinter(self.handle)
            raise

    def __exit__(self, *_args):
        self.spool.ClosePrinter(self.handle)

    def _call(self, output, source, flags):
        # Deliberately never pass DM_UPDATE: only this job's buffer is changed.
        return self.spool.DocumentPropertiesW(self.owner, self.handle, self.queue, output, source, flags)

    def merge(self, blob, prompt=False):
        self.validate(blob)
        source = ctypes.create_string_buffer(self.capacity)
        ctypes.memmove(source, blob, len(blob))
        output = ctypes.create_string_buffer(self.capacity)
        result = self._call(output, source, DM_IN_BUFFER | DM_OUT_BUFFER | (DM_IN_PROMPT if prompt else 0))
        if prompt and result == 2:
            return None
        if result != 1:
            raise DriverSettingsError("打印机驱动未接受页面设置")
        result_blob = _buffer_blob(output, self.capacity)
        self.validate(result_blob)
        return result_blob

    def validate(self, blob):
        incoming, current = parse_devmode(blob), parse_devmode(self.default)
        if len(blob) > self.capacity or (incoming.dmSize, incoming.dmSpecVersion, incoming.dmDriverVersion) != (
                current.dmSize, current.dmSpecVersion, current.dmDriverVersion):
            raise DriverSettingsError("驱动版本或页面设置结构已改变，请重新保存页面设置")


def confirmed_public_settings(queue, blob):
    """Validate the final dialog buffer against its actual selected driver."""
    with DriverSession(queue) as session:
        session.validate(blob)
    return public_settings(blob)


def validate_profile(profile, identity):
    if not isinstance(profile, dict) or profile.get("driver_identity") != identity:
        raise DriverSettingsError("打印机驱动已变化，请在软件中重新保存页面设置")
    blob = profile.get("devmode_bytes")
    parse_devmode(blob)
    return blob


def validate_target_dc(queue, blob, paper_mm):
    """Inspect actual page geometry. Creates and deletes a DC, never StartDoc."""
    parse_devmode(blob)
    gdi = ctypes.windll.gdi32
    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    gdi.CreateDCW.restype = wintypes.HDC
    gdi.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi.GetDeviceCaps.restype = ctypes.c_int
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.DeleteDC.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(blob)
    dc = gdi.CreateDCW("WINSPOOL", queue, None, buffer)
    if not dc:
        raise DriverSettingsError("无法验证已选择的打印机页面设置")
    try:
        dpi = tuple(gdi.GetDeviceCaps(dc, code) for code in (88, 90))
        pixels = tuple(gdi.GetDeviceCaps(dc, code) for code in (110, 111))
        if min(*dpi, *pixels) <= 0:
            raise DriverSettingsError("驱动未报告有效纸张尺寸")
        actual = tuple(pixel / dots * 25.4 for pixel, dots in zip(pixels, dpi))
        if max(abs(a - b) for a, b in zip(actual, paper_mm)) > 3:
            raise DriverSettingsError(
                f"驱动确认的纸张为 {actual[0]:g} × {actual[1]:g} mm，"
                f"与本次 {paper_mm[0]:g} × {paper_mm[1]:g} mm 的尺寸或方向不符；请重新选择")
        return actual
    finally:
        gdi.DeleteDC(dc)


def target_devmode(app, queue, paper_mm, owner=None, use_saved=True):
    getter = getattr(app, "get_driver_page_profile", None)
    try:
        profile = getter(queue, paper_mm) if getter and use_saved else None
    except (ValueError, TypeError) as error:
        raise DriverSettingsError(str(error)) from error
    with DriverSession(queue, owner) as session:
        if profile is not None:
            try:
                identity = driver_identity(queue)
                blob = session.merge(validate_profile(profile, identity))
                validate_target_dc(queue, blob, paper_mm)
                if driver_identity(queue) != identity:
                    raise DriverSettingsError("打印机驱动在读取期间发生变化，请重新打开页面设置")
                return blob, "采用软件保存的打印机页面设置（含驱动私有设置）"
            except Exception as error:
                raise DriverSettingsError(f"已保存的页面设置无法使用：{error}") from error

        original = session.default
        mode = parse_devmode(original)
        has_form = mode.dmSize >= 166
        forms, fields = read_supported_media(queue)
        matched = match_paper(forms, paper_mm, mode.dmPaperSize & 0xffff)
        fallback, note = original, "采用驱动当前纸型，按实际物理页面检查尺寸"
        for request in media_requests(matched, fields):
            if request == "form" and not has_form:
                continue
            buffer = ctypes.create_string_buffer(max(len(original), ctypes.sizeof(DEVMODEW)))
            ctypes.memmove(buffer, original, len(original))
            editable = DEVMODEW.from_buffer(buffer)
            requested_note = apply_media_request(editable, paper_mm, matched, fields, request, has_form)
            try:
                candidate = session.merge(bytes(buffer[:len(original)]))
            except DriverSettingsError:
                continue
            if driver_substituted_size(parse_devmode(candidate), forms, paper_mm, has_form):
                fallback, note = candidate, "驱动重新指定纸型，按实际物理页面检查尺寸"
                continue
            return candidate, requested_note
        return fallback, note


def public_settings(blob):
    mode = parse_devmode(blob)
    return {"driver_scale_percent": mode.dmScale if mode.dmFields & DM_SCALE else None,
            "driver_orientation": mode.dmOrientation if mode.dmFields & 1 else None,
            "driver_private_settings": "已保留；具体选项以打印机属性窗口为准"}


def edit_page_settings(app, target, owner=None):
    queue, paper = target.printer, target.paper_mm
    if not queue:
        raise DriverSettingsError("请先选择可用打印机")
    if hasattr(owner, "winfo_id"):
        owner = owner.winfo_id()
    identity = driver_identity(queue)
    try:
        initial, _ = target_devmode(app, queue, paper, owner)
    except DriverSettingsError:
        # The explicit editor is the recovery path for old/corrupt driver settings.
        initial, _ = target_devmode(app, queue, paper, owner, use_saved=False)
    with DriverSession(queue, owner) as session:
        result = session.merge(initial, prompt=True)
    if result is None:
        return False
    validate_target_dc(queue, result, paper)
    if driver_identity(queue) != identity:
        raise DriverSettingsError("打印机驱动在设置期间发生变化，请重新打开页面设置")
    app.save_driver_page_profile(queue, paper, result, identity)
    return True
