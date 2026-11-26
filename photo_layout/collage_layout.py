"""Multi-photo paper grids. All coordinates refer to the output raster, not the window."""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from PIL import Image

from .photo_fit import fit_photo, read_photo
from .cut_marks import draw_cut_ticks
from .specifications import FIT_MODE_ADAPT, FIT_MODE_OPTIONS, SIZE_5INCH_MM, SIZE_6INCH_MM


PAPERS = {
    "5寸": SIZE_5INCH_MM,
    "6寸": SIZE_6INCH_MM,
    "7寸": (127.0, 177.8),
    "8寸": (152.4, 203.2),
    "A4": (210.0, 297.0),
}
# Rows and columns are in the final paper orientation.
GRIDS = {
    "左右双拼": (1, 2),
    "上下双拼": (2, 1),
    "四宫格": (2, 2),
    "六宫格 · 三行两列": (3, 2),
    "六宫格 · 两行三列": (2, 3),
    "九宫格": (3, 3),
}
ORIENTATIONS = ("自动", "竖向", "横向")


@dataclass(frozen=True)
class CollageOptions:
    paper: str = "6寸"
    grid: str = "四宫格"
    orientation: str = "自动"
    border_mm: float = 2.0
    fit_mode: str = FIT_MODE_ADAPT
    auto_rotate: bool = True
    cut_marks: bool = True

    def __post_init__(self):
        if self.paper not in PAPERS or self.grid not in GRIDS:
            raise ValueError("请选择有效相纸和排列方式")
        if self.orientation not in ORIENTATIONS or self.fit_mode not in FIT_MODE_OPTIONS:
            raise ValueError("请选择有效方向和照片适配方式")
        if not isfinite(self.border_mm) or not 0 <= self.border_mm <= 10:
            raise ValueError("四边留白应在 0 至 10 毫米之间")

    @property
    def capacity(self):
        rows, columns = GRIDS[self.grid]
        return rows * columns


def choose_paper(options, sizes):
    portrait = PAPERS[options.paper]
    if options.orientation != "自动":
        return portrait if options.orientation == "竖向" else portrait[::-1]
    rows, columns = GRIDS[options.grid]

    def score(paper):
        width = paper[0] / columns - 2 * options.border_mm
        height = paper[1] / rows - 2 * options.border_mm
        if min(width, height) <= 0:
            return (-1, -1)
        ratio = width / height
        retained = upright = 0
        for w, h in sizes:
            direct = min((w / h) / ratio, ratio / (w / h))
            turned = min((h / w) / ratio, ratio / (h / w))
            retained += max(direct, turned) if options.auto_rotate else direct
            upright += direct
        return round(retained, 9), round(upright, 9)

    return max((portrait, portrait[::-1]), key=score)


def grid_boxes(paper_px, grid, border_px):
    """Each shared cut bisects its gutter. Rounding affects cell size by at most 1 px."""
    rows, columns = grid
    w, h = paper_px
    if w // columns <= 2 * border_px or h // rows <= 2 * border_px:
        raise ValueError("此留白过大，请减小留白或减少格数")
    boxes = []
    for r in range(rows):
        for c in range(columns):
            frame = (round(c * w / columns), round(r * h / rows),
                     round((c + 1) * w / columns), round((r + 1) * h / rows))
            x, y, right, bottom = frame
            boxes.append((frame, (x + border_px, y + border_px, right - border_px, bottom - border_px)))
    return boxes


def draw_marks(sheet, grid, border_px, dpi):
    if border_px < 1:
        return
    w, h = sheet.size
    rows, columns = grid
    vertical = (round(c * w / columns) for c in range(1, columns))
    horizontal = (round(r * h / rows) for r in range(1, rows))
    draw_cut_ticks(sheet, vertical, horizontal, border_px, dpi, "#8c8c8c")


def build_collage_task(paths, options, paper_mm, dpi):
    if not 0 < len(paths) <= options.capacity:
        raise ValueError("每张相纸需要至少一张照片，且不能超过格数")
    if not 0 < dpi <= 600:
        raise ValueError("输出分辨率须在 1 至 600 DPI 范围内")
    paper_px = tuple(round(mm * dpi / 25.4) for mm in paper_mm)
    border_px = round(options.border_mm * dpi / 25.4)
    grid = GRIDS[options.grid]
    boxes = grid_boxes(paper_px, grid, border_px)
    sheet = Image.new("RGB", paper_px, "white")
    slots = []
    for index, (frame, inner) in enumerate(boxes):
        occupied = index < len(paths)
        if occupied:
            with read_photo(paths[index]) as source:
                size = (inner[2] - inner[0], inner[3] - inner[1])
                tile = fit_photo(source, size, options.fit_mode, auto_rotate=options.auto_rotate)
                sheet.paste(tile, inner[:2])
        slots.append({"frame": frame, "photo": inner if occupied else None})
    if options.cut_marks:
        draw_marks(sheet, grid, border_px, dpi)
    factor = min(1, 1200 / max(paper_px))
    preview = sheet.resize(tuple(max(1, round(v * factor)) for v in paper_px),
                           Image.Resampling.LANCZOS, reducing_gap=3)
    photo_mm = (paper_mm[0] / grid[1], paper_mm[1] / grid[0])
    geometry = {"direction": "grid", "grid": grid, "slot_count": options.capacity,
                "paper_px": paper_px, "border_px": border_px, "slots": slots,
                "middle_margin_px": 2 * border_px}
    task = {"kind": "collage", "image": sheet, "preview_image": preview, "size": paper_px,
            "paper_mm": paper_mm, "photo_mm": photo_mm, "layout": f"{options.paper} · {options.grid}",
            "dpi": dpi, "fit_mode": options.fit_mode, "margin_mm": options.border_mm,
            "source_count": len(paths), "source_paths": list(paths), "geometry": geometry,
            "created": datetime.now().strftime("%H:%M:%S")}
    task["validation"] = validate_collage(task)
    return task


def validate_collage(task):
    geometry = task["geometry"]
    rows, columns = geometry["grid"]
    expected_px = tuple(round(mm * task["dpi"] / 25.4) for mm in task["paper_mm"])
    errors, warnings = [], []
    if task["image"].size != expected_px or geometry["paper_px"] != expected_px or task["size"] != expected_px:
        errors.append("拼版成片与相纸物理尺寸不一致")
    slots = geometry["slots"]
    count = task["source_count"]
    if len(slots) != rows * columns or not 0 < count <= len(slots) or len(task["source_paths"]) != count:
        errors.append("照片数量或排列格数与相纸不符")
    margin = round(task["margin_mm"] * task["dpi"] / 25.4)
    boxes = grid_boxes(expected_px, (rows, columns), margin)
    for index, (slot, (frame, inner)) in enumerate(zip(slots, boxes)):
        if slot["frame"] != frame or slot["photo"] != (inner if index < count else None):
            errors.append(f"第 {index + 1} 格的位置或裁剪留白不符")
    if count < len(slots):
        warnings.append(f"本页末尾 {len(slots) - count} 格留空")
    return {"ok": not errors, "errors": errors, "warnings": warnings}
