"""Registration ticks for cuts, kept inside the sheet's requested white border."""
from PIL import ImageDraw


def draw_cut_ticks(sheet, vertical, horizontal, inset_px, dpi, fill):
    pen = ImageDraw.Draw(sheet)
    width, height = sheet.size
    length = max(1, round(2 * dpi / 25.4))

    def ends(span):
        # Leave the full requested margin blank outside the two short marks.
        start = min(inset_px, (span - 1) // 2)
        stop = min(start + length - 1, (span - 1) // 2)
        return ((start, stop), (span - 1 - stop, span - 1 - start))

    for x in vertical:
        for top, bottom in ends(height):
            pen.line((x, top, x, bottom), fill=fill)
    for y in horizontal:
        for left, right in ends(width):
            pen.line((left, y, right, y), fill=fill)
