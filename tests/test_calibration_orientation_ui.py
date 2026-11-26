"""Real Tk orientation controls, with printer submission and dialogs isolated."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from photo_layout_printer import PhotoLayoutPrinter
from photo_layout.collage_layout import CollageOptions, PAPERS, build_collage_task
from photo_layout.print_orientation import (
    PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE,
)


def fingerprint(image):
    return image.size, sha256(image.tobytes()).digest()


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


class CalibrationOrientationWindowTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        folder = self.context.enter_context(tempfile.TemporaryDirectory())
        self.context.enter_context(patch("photo_layout.configuration.CONFIG_FILE", str(Path(folder) / "settings.json")))
        self.context.enter_context(patch("photo_layout.configuration.platform.node", return_value="方向测试站"))
        self.context.enter_context(patch.object(PhotoLayoutPrinter, "list_available_printers",
                                               return_value=(["测试照片打印机"], [])))
        self.context.enter_context(patch.object(PhotoLayoutPrinter, "windows_default_printer",
                                               return_value="测试照片打印机"))
        self.context.enter_context(patch("tkinter.messagebox.showinfo"))
        self.errors = self.context.enter_context(patch("tkinter.messagebox.showerror"))
        self.root = None
        self.addCleanup(self.close_window)
        self.start_window()
        path = Path(folder) / "asymmetric.png"
        source = Image.new("RGB", (90, 160), "blue")
        ImageDraw.Draw(source).rectangle((0, 0, 30, 50), fill="red")
        source.save(path)
        options = CollageOptions(paper="7寸", grid="上下双拼", orientation="竖向")
        task = build_collage_task([str(path)] * 2, options, PAPERS["7寸"], 150)
        task["checked_for_print"] = True
        self.app.batch_tasks.append(task)
        self.app.update_task_list()
        self.app.task_listbox._choose(0)
        self.root.update()

    def start_window(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.callback_errors = []
        self.root.report_callback_exception = lambda *details: self.callback_errors.append(details)
        self.app = PhotoLayoutPrinter(self.root)
        self.root.update()

    def close_window(self):
        if self.root is not None:
            self.root.update()
            self.root.destroy()
            self.root = None

    def select_orientation(self, combo, value):
        combo.current(list(combo["values"]).index(value))
        combo.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.root.after(130, self.root.quit)
        self.root.mainloop()
        self.assertFalse(self.callback_errors)

    def button(self, parent, text):
        matches = [w for w in children(parent) if isinstance(w, tk.Button) and w["text"] == text]
        self.assertEqual(len(matches), 1, text)
        return matches[0]

    def test_main_direction_changes_display_without_mutating_frozen_sheet_or_checks(self):
        app = self.app
        task = app.batch_tasks[0]
        frozen = fingerprint(task["image"])
        paper = task["paper_mm"]
        for direction in (PAPER_ORIENTATION_LANDSCAPE, PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_AUTO):
            self.select_orientation(app.paper_orientation_combo, direction)
            self.assertEqual(app.paper_orientation.get(), direction)
            self.assertEqual(fingerprint(task["image"]), frozen)
            self.assertEqual(task["paper_mm"], paper)
            self.assertTrue(task["checked_for_print"])
            self.assertEqual(app.preview_task_index, 0)
            self.assertEqual(app.task_listbox.curselection(), (0,))
            shown = (app.preview_tk.width(), app.preview_tk.height())
            if direction == PAPER_ORIENTATION_LANDSCAPE:
                self.assertGreater(shown[0], shown[1])
            else:
                self.assertLess(shown[0], shown[1])
        self.errors.assert_not_called()

    def test_calibration_switch_keeps_separate_profiles_and_prints_current_preview(self):
        app = self.app
        app.prepare_print_context = Mock(return_value=({"name": "测试照片打印机"}, "dc", None))
        app.print_tasks_with_win32 = Mock()
        app.close_system_print_context = Mock()
        app.open_advanced_calibration()
        self.root.update()
        frozen = fingerprint(app.batch_tasks[0]["image"])
        expected = [(PAPER_ORIENTATION_LANDSCAPE, (177.8, 127.0), (1.2, -0.8)),
                    (PAPER_ORIENTATION_PORTRAIT, (127.0, 177.8), (-2.1, 0.5))]
        for direction, paper, shifts in expected:
            self.select_orientation(app.calibration_orientation_combo, direction)
            self.assertEqual(app.paper_orientation_combo.get(), direction)
            target = app.calibration_active_target
            self.assertEqual((target.printer, target.paper_mm, target.dpi),
                             ("测试照片打印机", paper, 150))
            app.calibration_x_slider.set(shifts[0])
            app.calibration_y_slider.set(shifts[1])
            self.root.update()
            self.assertEqual(app.calibration_offsets_for(target.printer, target.layout, paper), shifts)
            wanted_size = tuple(round(mm * 150 / 25.4) for mm in paper)
            self.assertEqual(app.calibration_preview_image.size, wanted_size)
            before = fingerprint(app.calibration_preview_image)
            for geometry in ("1120x780", "940x680"):
                app.advanced_window.geometry(geometry)
                self.root.update()
                self.assertEqual(fingerprint(app.calibration_preview_image), before)
                canvas = app.calibration_preview_canvas
                items = [i for i in canvas.find_all() if canvas.type(i) == "image"]
                self.assertTrue(items)
                x0, y0, x1, y1 = canvas.bbox(items[0])
                self.assertGreaterEqual(min(x0, y0), 0)
                self.assertLessEqual(x1, canvas.winfo_width())
                self.assertLessEqual(y1, canvas.winfo_height())
            self.button(app.advanced_window, "打印中心十字校准图").invoke()
            self.root.update()
            sent = app.print_tasks_with_win32.call_args.args[0][0]
            self.assertEqual((sent["paper_mm"], sent["dpi"]), (paper, 150))
            self.assertEqual(fingerprint(sent["image"]), before)
            self.assertEqual(fingerprint(app.batch_tasks[0]["image"]), frozen)
        for direction, paper, shifts in expected:
            self.select_orientation(app.calibration_orientation_combo, direction)
            self.assertEqual((app.calibration_x_slider.get(), app.calibration_y_slider.get()), shifts)
            self.assertEqual(app.calibration_active_target.paper_mm, paper)
        self.errors.assert_not_called()
        self.assertFalse(self.callback_errors)

    def test_direction_persists_and_reopened_calibration_uses_current_media(self):
        self.select_orientation(self.app.paper_orientation_combo, PAPER_ORIENTATION_LANDSCAPE)
        self.close_window()
        self.start_window()
        app = self.app
        self.assertEqual(app.paper_orientation.get(), PAPER_ORIENTATION_LANDSCAPE)
        self.assertEqual(app.paper_orientation_combo.get(), PAPER_ORIENTATION_LANDSCAPE)
        app.open_advanced_calibration()
        self.root.update()
        self.assertEqual(app.calibration_orientation_combo.get(), PAPER_ORIENTATION_LANDSCAPE)
        width, height = app.calibration_active_target.paper_mm
        self.assertGreater(width, height)
        self.assertEqual(app.calibration_preview_image.size,
                         tuple(round(mm * app.dpi.get() / 25.4) for mm in (width, height)))
        self.errors.assert_not_called()
        self.assertFalse(self.callback_errors)


if __name__ == "__main__":
    unittest.main()
