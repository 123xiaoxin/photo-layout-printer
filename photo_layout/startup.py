"""Show the packaged logo animation once before revealing the main window."""

from bisect import bisect_right
import ctypes
from math import ceil
from pathlib import Path
import sys
from time import monotonic
import tkinter as tk

from PIL import Image, ImageSequence, ImageTk


STARTUP_IMAGE = Path(__file__).with_name("assets") / "startup.png"


def _animations_enabled():
    if sys.platform != "win32":
        return True
    enabled = ctypes.c_int()
    # SPI_GETCLIENTAREAANIMATION follows Windows' Animation effects preference.
    known = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    return bool(enabled.value) if known else True


def reveal_with_startup(root):
    if not _animations_enabled():
        root.deiconify()
        return

    frames = []
    ends_ms = []
    elapsed = 0
    try:
        with Image.open(STARTUP_IMAGE) as animation:
            for frame in ImageSequence.Iterator(animation):
                elapsed += max(1, round(frame.info.get("duration", 40)))
                ends_ms.append(elapsed)
                frames.append(ImageTk.PhotoImage(frame.convert("RGB"), master=root))
    except (OSError, ValueError, EOFError, SyntaxError):
        root.deiconify()
        return

    splash = tk.Toplevel(root)
    splash.withdraw()
    splash.title("照片排版工具 · 启动")
    splash.overrideredirect(True)
    width, height = frames[0].width(), frames[0].height()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    splash.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
    screen = tk.Label(splash, image=frames[0], bg="#DCE3D7", borderwidth=0, highlightthickness=0)
    screen.pack(fill="both", expand=True)
    timer = None

    def finish(_event=None):
        nonlocal timer
        if timer is not None:
            splash.after_cancel(timer)
            timer = None
        root.deiconify()
        splash.destroy()
        frames.clear()

    def advance():
        nonlocal timer
        timer = None
        elapsed_ms = (monotonic() - started) * 1000
        index = bisect_right(ends_ms, elapsed_ms)
        if index == len(frames):
            finish()
            return
        screen.configure(image=frames[index])
        timer = splash.after(max(1, ceil(ends_ms[index] - elapsed_ms)), advance)

    splash.bind("<Button-1>", finish)
    splash.bind("<Escape>", finish)
    splash.protocol("WM_DELETE_WINDOW", finish)
    splash.deiconify()
    splash.lift()
    splash.update_idletasks()
    splash.focus_force()
    started = monotonic()
    advance()
