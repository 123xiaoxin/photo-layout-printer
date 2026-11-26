"""Physical-millimetre calibration chart, independent of the window and printer DC."""
from math import floor, isfinite

from PIL import Image, ImageDraw, ImageFont


BLACK = (30, 30, 30)
GRAY = (125, 125, 125)
RED = (205, 35, 35)
BLUE = (25, 80, 165)


def _font(pixels, bold=False):
    for name in ("msyhbd.ttc" if bold else "msyh.ttc", "simhei.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, pixels)
        except OSError:
            continue
    return ImageFont.load_default(size=pixels)


def render_calibration_chart(target, offsets_mm=(0, 0)):
    """Render the target's actual orientation, with a centre origin and positive right/down axes."""
    width_mm, height_mm = target.paper_mm
    dpi = target.dpi
    if not all(isfinite(value) for value in (width_mm, height_mm, dpi, *offsets_mm)):
        raise ValueError("校准图的纸张尺寸、分辨率和补偿必须为有限数值")
    if min(width_mm, height_mm) < 85 or not 72 <= dpi <= 1200:
        raise ValueError("校准图需要短边至少 85 mm 的纸张及 72 至 1200 DPI")

    def px(mm):
        return round(mm * dpi / 25.4)

    width, height = px(width_mm), px(height_mm)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    thin = max(1, px(0.10))

    def line(points, color=BLACK, thickness=0.12):
        draw.line(tuple(px(value) for value in points), fill=color, width=max(1, px(thickness)))

    def text(x, y, value, size=2.2, color=BLACK, bold=False, anchor="lt"):
        draw.text((px(x), px(y)), value, font=_font(max(1, px(size)), bold),
                  fill=color, anchor=anchor)

    cx, cy = width_mm / 2, height_mm / 2
    # The reference frame stays inset. Extend the axes to the sheet edges so
    # their alignment is visible wherever the printer's printable region ends.
    draw.rectangle((px(10), px(10), px(width_mm - 10), px(height_mm - 10)),
                   outline=GRAY, width=thin)
    # Measure from the physical paper edge to this frame. Axis endpoints are
    # clipped by hardware margins and therefore cannot locate the paper centre.
    marker_x, marker_y = cx - 7, cy + 8
    for frame_y in (10, height_mm - 10):
        line((marker_x - 2, frame_y, marker_x + 2, frame_y), BLUE, 0.25)
    for frame_x in (10, width_mm - 10):
        line((frame_x, marker_y - 2, frame_x, marker_y + 2), BLUE, 0.25)
    text(marker_x, 11.5, "上", size=1.8, color=BLUE, anchor="mt")
    text(marker_x, height_mm - 12.7, "下", size=1.6, color=BLUE, anchor="mt")
    text(11.5, marker_y, "左", size=1.8, color=BLUE, anchor="lm")
    text(width_mm - 11.5, marker_y, "右", size=1.8, color=BLUE, anchor="rm")
    axis_width = max(1, px(0.2))
    draw.line((0, px(cy), width - 1, px(cy)), fill=BLUE, width=axis_width)
    draw.line((px(cx), 0, px(cx), height - 1), fill=BLUE, width=axis_width)
    for axis, half_size in (("x", cx), ("y", cy)):
        extent = floor(half_size - 1)
        for mm in range(-extent, extent + 1):
            if mm == 0:
                continue
            length = 2.4 if mm % 10 == 0 else 1.7 if mm % 5 == 0 else 0.8
            if axis == "x":
                line((cx + mm, cy - length, cx + mm, cy + length))
                if mm % 10 == 0 and abs(mm) <= half_size - 12:
                    text(cx + mm, cy + 3.4, f"{mm:+d}", anchor="mt")
            else:
                line((cx - length, cy + mm, cx + length, cy + mm))
                if mm % 10 == 0 and abs(mm) <= half_size - 12:
                    text(cx + 3.4, cy + mm, f"{mm:+d}", anchor="lm")

    line((cx - 12, cy, cx + 12, cy), RED, 0.3)
    line((cx, cy - 12, cx, cy + 12), RED, 0.3)
    text(cx + 3, cy - 6, "0", size=2.8, color=RED, bold=True)
    # Axis arrows distinguish clockwise rotations on the printed sheet.
    line((width_mm - 14, cy - 1, width_mm - 12, cy, width_mm - 14, cy + 1), BLUE)
    line((cx - 1, height_mm - 14, cx, height_mm - 12, cx + 1, height_mm - 14), BLUE)
    text(width_mm - 13, cy - 6, "+X", color=BLUE, anchor="rt")
    text(cx - 3, height_mm - 15, "+Y", color=BLUE, anchor="rt")

    # Text lives in quadrants, leaving an uninterrupted cross and both axes.
    text(12, 13, "中心校准图", size=3, bold=True)
    text(12, 19, f"宽 {width_mm:g} mm")
    text(12, 23.5, f"高 {height_mm:g} mm")
    portrait = width_mm <= height_mm
    text(12, 28, "纵向 · 短边在上" if portrait else "横向 · 长边在上")
    text(12, 32.5, f"{dpi:g} DPI")

    right_x = cx + 11
    text(right_x, 13, "图示上边", color=BLUE)
    arrow_x = width_mm - 14
    line((arrow_x, 21, arrow_x, 13), BLUE, 0.2)
    line((arrow_x - 1.3, 15, arrow_x, 13, arrow_x + 1.3, 15), BLUE, 0.2)
    text(right_x, 23.5, "当前补偿 / mm")
    text(right_x, 28, f"X {offsets_mm[0]:+.2f}")
    text(right_x, 32.5, f"Y {offsets_mm[1]:+.2f}")

    # Reference objects expose both uniform scaling and single-axis distortion.
    ruler_y = height_mm - 20
    line((12, ruler_y, 32, ruler_y), BLUE, 0.2)
    for mm in range(21):
        length = 1.8 if mm in (0, 20) else 1.2 if mm % 5 == 0 else 0.6
        line((12 + mm, ruler_y - length, 12 + mm, ruler_y + length), BLUE)
    text(12, ruler_y - 6, "20 mm 校验尺")
    text(12, height_mm - 16, "量纸边到灰框", size=2)
    text(12, height_mm - 13, "四边各 10 mm", size=2)

    text(right_x, cy + 12, "右 +X / 下 +Y", color=BLUE, size=2)
    text(right_x, cy + 16, "线端截断不代表偏移", size=1.7, color=BLUE)
    square_top = height_mm - 24
    draw.rectangle((px(right_x), px(square_top), px(right_x + 10), px(square_top + 10)),
                   outline=BLUE, width=thin)
    text(right_x, height_mm - 13, "10 × 10 mm", size=2)
    return image
