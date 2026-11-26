"""Map a composed photo sheet to a Windows printer's physical page."""
from dataclasses import dataclass

from PIL import ImageChops


@dataclass(frozen=True)
class PrintPlacement:
    physical_box: tuple
    device_box: tuple
    rotate_clockwise: bool
    scale: float


def print_placement(task, caps, calibration_mm=(0, 0)):
    """Use millimetres on both axes, including when the driver has unequal DPIs."""
    dpi = (caps["logpixels_x"], caps["logpixels_y"])
    physical = (caps["physical_width"], caps["physical_height"])
    printable = (caps["horzres"], caps["vertres"])
    if min(*dpi, *physical, *printable) <= 0:
        raise ValueError("驱动未提供有效的纸张、分辨率或可打印区域，请检查驱动的纸张设置")
    offsets = (caps["offset_x"], caps["offset_y"])
    limits = tuple((max(0, offset), min(page, offset + available))
                   for offset, page, available in zip(offsets, physical, printable))
    if any(end <= start for start, end in limits):
        raise ValueError("驱动报告的可打印范围与实际纸张没有交集，请检查驱动纸型和纸盒设置")
    paper = tuple(task["paper_mm"])
    actual = tuple(px * 25.4 / dots for px, dots in zip(physical, dpi))
    direct_error = max(abs(a - b) for a, b in zip(actual, paper))
    rotated_error = max(abs(a - b) for a, b in zip(actual, reversed(paper)))
    if min(direct_error, rotated_error) > 3.0:
        raise ValueError(f"驱动页面为 {actual[0]:.1f} × {actual[1]:.1f} mm，"
                         f"请选择 {paper[0]:g} × {paper[1]:g} mm 的相纸")
    rotate = rotated_error < direct_error
    if rotate:
        paper = paper[::-1]
        calibration_mm = (-calibration_mm[1], calibration_mm[0])
    target = tuple(mm * dots / 25.4 for mm, dots in zip(paper, dpi))
    centre = tuple(size / 2 + shift * dots / 25.4
                   for size, shift, dots in zip(physical, calibration_mm, dpi))
    scale = 1.0
    if task.get("kind") != "calibration":
        # Blank outer paper can fall into the mechanical margins without losing ink.
        # Include cut marks as well as photographs. The stored print image has no preview guides.
        image = task["image"]
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        ink_bounds = ImageChops.invert(rgb).getbbox()
        if ink_bounds:
            x0, y0, x1, y1 = ink_bounds
            l, t, r, b = x0 / rgb.width, y0 / rgb.height, x1 / rgb.width, y1 / rgb.height
            if rotate:
                l, t, r, b = 1 - b, l, 1 - t, r
            off_centre_axes = []
            for axis, (low, high) in enumerate(((l, r), (t, b))):
                start, end = limits[axis]
                if not start < centre[axis] < end:
                    # Some forms expose only one side of a sheet. Ink can still
                    # fall entirely within it without moving the physical centre.
                    off_centre_axes.append((axis, low, high))
                    continue
                if low < 0.5:
                    scale = min(scale, (centre[axis] - start) / (target[axis] * (0.5 - low)))
                if high > 0.5:
                    scale = min(scale, (end - centre[axis]) / (target[axis] * (high - 0.5)))
            for axis, low, high in off_centre_axes:
                start, end = limits[axis]
                # Scaling toward an inaccessible centre can *remove* formerly
                # printable ink. Require both native-size and final bounds to fit.
                # Match the integer destination edges sent to GDI.
                for size_ratio in (1.0, scale):
                    a = round(centre[axis] - target[axis] * size_ratio / 2)
                    b = round(centre[axis] + target[axis] * size_ratio / 2)
                    if a + low * (b-a) < start - 1e-7 or a + high * (b-a) > end + 1e-7:
                        raise ValueError("纸张中心不在可打印区，保留现有定位会裁掉照片或裁切线。"
                                         "请检查驱动纸型、可打印范围或手动偏移")
    # GDI's printer DC starts at the printable origin. Apply the hardware offset exactly once.
    left, top = (round(c - size * scale / 2) for c, size in zip(centre, target))
    right, bottom = (round(c + size * scale / 2) for c, size in zip(centre, target))
    ox, oy = offsets
    return PrintPlacement((left, top, right, bottom), (left - ox, top - oy, right - ox, bottom - oy),
                          rotate, scale)
