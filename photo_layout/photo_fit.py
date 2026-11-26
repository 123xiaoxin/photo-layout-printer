"""Fit source photographs to the physical print raster; independent of screen size."""
from PIL import Image, ImageOps

from .specifications import (
    FIT_MODE_ADAPT, FIT_MODE_CROP, FIT_MODE_NATIVE, FIT_MODE_POLAROID, normalize_fit_mode,
)


def read_photo(path):
    """Load all pixels and honor camera rotation before releasing the source file."""
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source)


def inset_size(slot_size, margin_mm, dpi):
    """Inset each of the four cut edges by the same whole number of print pixels."""
    width, height = slot_size
    margin = min(max(0, round(margin_mm * dpi / 25.4)), (min(width, height) - 1) // 2)
    return width - 2 * margin, height - 2 * margin


def orient_photo(image, target_size, auto_rotate, rotation):
    """Choose the orientation retaining most source area, then apply user rotation."""
    width, height = image.size
    target_w, target_h = target_size
    # The closer aspect ratios maximize the occupied area for 'contain' and the
    # retained area for 'cover'. Pairing long edges is optimal for either metric.
    turn = rotation % 360
    if auto_rotate and (width - height) * (target_w - target_h) < 0:
        turn = (turn + 90) % 360
    transpose = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                 270: Image.Transpose.ROTATE_90}
    if turn in transpose:
        return image.transpose(transpose[turn])
    if turn:
        return image.rotate(-turn, expand=True)
    return image


def fit_photo(image, target_size, fit_mode, auto_rotate=True, rotation=0):
    """Return a white-backed RGB print cell with a single aspect-preserving resize."""
    image = orient_photo(image, target_size, auto_rotate, rotation)
    if image.mode != "RGB":
        if "A" in image.getbands() or "transparency" in image.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = image.convert("RGB")
    width, height = image.size
    target_w, target_h = target_size
    mode = normalize_fit_mode(fit_mode)
    square = min(width, height) >= max(width, height) * 0.95
    contain = mode in (FIT_MODE_ADAPT, FIT_MODE_NATIVE) or (
        square and mode in (FIT_MODE_CROP, FIT_MODE_POLAROID)
    )
    if not contain:
        if image.size == target_size:
            return image
        # Fit samples the source crop directly; no oversized intermediate panorama.
        return ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS)

    scale = min(target_w / width, target_h / height)
    if mode == FIT_MODE_NATIVE:
        scale = min(1.0, scale)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    photo = image if size == image.size else image.resize(size, Image.Resampling.LANCZOS)
    if photo.size == target_size:
        return photo
    spare_x, spare_y = target_w - size[0], target_h - size[1]
    x, y = spare_x // 2, spare_y // 2
    if mode == FIT_MODE_POLAROID:
        if target_h >= target_w:
            y = min(round(target_h * 0.05), spare_y)
        else:
            x = min(round(target_w * 0.05), spare_x)
    result = Image.new("RGB", target_size, "white")
    result.paste(photo, (x, y))
    return result
