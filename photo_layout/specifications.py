"""Paper formats, print settings, and application palette."""
import os
import sys

# 排版选项定义
LAYOUT_OPTIONS = {
    "5寸整张": {
        "paper_mm": (89, 127),
        "photo_mm": (89, 127),
        "direction": "single",
        "slot_count": 1,
    },
    "5寸+3寸": {
        "paper_mm": (89, 127),
        "photo_mm": (89, 63.5),
        "direction": "vertical",
        "slot_count": 2,
    },
    "6寸整张": {
        "paper_mm": (101.6, 152.4),
        "photo_mm": (101.6, 152.4),
        "direction": "single",
        "slot_count": 1,
    },
    "6寸+4寸": {
        "paper_mm": (101.6, 152.4),
        "photo_mm": (101.6, 76.2),
        "direction": "vertical",
        "slot_count": 2,
    },
    "6寸左右双栏": {
        "paper_mm": (152.4, 101.6),
        "photo_mm": (76.2, 101.6),
        "direction": "horizontal",
        "slot_count": 2,
    },
}

DPI = 300
MM_TO_INCH = 1 / 25.4

FIT_MODE_CROP = "裁切填满"
FIT_MODE_ADAPT = "适应留白"
FIT_MODE_POLAROID = "拍立得风"
FIT_MODE_EQUAL_BORDER = "等边裁切"
FIT_MODE_NATIVE = "原始像素优先"
FIT_MODE_OPTIONS = [FIT_MODE_CROP, FIT_MODE_EQUAL_BORDER, FIT_MODE_ADAPT, FIT_MODE_NATIVE, FIT_MODE_POLAROID]

PRINT_METHOD_DIRECT = "默认直接打印"
PRINT_METHOD_SYSTEM = "使用系统打印设置"
PRINT_METHOD_OPTIONS = [PRINT_METHOD_DIRECT, PRINT_METHOD_SYSTEM]

SIZE_5INCH_MM = (89, 127)
SIZE_6INCH_MM = (101.6, 152.4)

SIZE_5INCH_PX = (int(SIZE_5INCH_MM[0] * DPI * MM_TO_INCH), int(SIZE_5INCH_MM[1] * DPI * MM_TO_INCH))
SIZE_6INCH_PX = (int(SIZE_6INCH_MM[0] * DPI * MM_TO_INCH), int(SIZE_6INCH_MM[1] * DPI * MM_TO_INCH))

PREVIEW_SCALE = 0.35
PREVIEW_5INCH_PX = (int(SIZE_5INCH_PX[0] * PREVIEW_SCALE), int(SIZE_5INCH_PX[1] * PREVIEW_SCALE))
PREVIEW_6INCH_PX = (int(SIZE_6INCH_PX[0] * PREVIEW_SCALE), int(SIZE_6INCH_PX[1] * PREVIEW_SCALE))

# Keep portable settings next to the executable, outside bundled runtime files.
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "photo_layout_config.json")

THEME = {
    "bg": "#060806",
    "panel": "#111511",
    "card": "#1a1f1a",
    "card_soft": "#222820",
    "border": "#323a30",
    "text": "#f3f7ef",
    "muted": "#b9c7b7",
    "subtle": "#798577",
    "accent": "#d9ff8a",
    "accent_2": "#2f7df6",
    "success": "#63e58f",
    "warning": "#f4c866",
    "danger": "#ff6b6b",
    "paper": "#ffffff",
}

DM_ORIENTATION = 0x00000001
DM_PAPERSIZE = 0x00000002
DM_PAPERLENGTH = 0x00000004
DM_PAPERWIDTH = 0x00000008
DM_MEDIATYPE = 0x02000000
DM_IN_BUFFER = 0x00000008
DM_OUT_BUFFER = 0x00000002
DMORIENT_PORTRAIT = 1
DMORIENT_LANDSCAPE = 2
DMPAPER_USER = 256
DMMEDIA_GLOSSY = 3
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
DC_PAPERS = 2
DC_PAPERSIZE = 3
DC_PAPERNAMES = 16


def normalize_fit_mode(value):
    if isinstance(value, bool):
        return FIT_MODE_CROP if value else FIT_MODE_ADAPT
    if value is None:
        return FIT_MODE_CROP

    text = str(value).strip()
    if text in FIT_MODE_OPTIONS:
        return text
    aliases = {
        "1": FIT_MODE_CROP,
        "true": FIT_MODE_CROP,
        "crop": FIT_MODE_CROP,
        "fit": FIT_MODE_CROP,
        "裁剪填满照片框": FIT_MODE_CROP,
        "裁切填满": FIT_MODE_CROP,
        "0": FIT_MODE_ADAPT,
        "false": FIT_MODE_ADAPT,
        "adapt": FIT_MODE_ADAPT,
        "letterbox": FIT_MODE_ADAPT,
        "contain": FIT_MODE_ADAPT,
        "不裁剪": FIT_MODE_ADAPT,
        "适应留白": FIT_MODE_ADAPT,
        "polaroid": FIT_MODE_POLAROID,
        "拍立得": FIT_MODE_POLAROID,
        "拍立得风": FIT_MODE_POLAROID,
    }
    return aliases.get(text.lower(), aliases.get(text, FIT_MODE_CROP))

