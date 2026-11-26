"""Exercise the Tk controls with real images, substituting only dialogs and printer I/O."""
from hashlib import sha256
from contextlib import ExitStack
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from photo_layout_printer import PhotoLayoutPrinter
from photo_layout import configuration
from photo_layout.collage_layout import CollageOptions, PAPERS, build_collage_task


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.temp = self.context.enter_context(tempfile.TemporaryDirectory())
        self.context.enter_context(patch.object(configuration, "CONFIG_FILE", str(Path(self.temp) / "settings.json")))
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.attributes("-alpha", 0)
        self.app = PhotoLayoutPrinter(self.root)
        self.context.enter_context(patch.object(messagebox, "showinfo"))
        self.context.enter_context(patch.object(messagebox, "showwarning"))
        self.errors = self.context.enter_context(patch.object(messagebox, "showerror"))
        self.app.layout_mode.set("6寸+4寸")
        self.app.dpi.set(300)
        self.files = []
        for i in range(6):
            path = Path(self.temp) / f"测试 照片 {i}.png"
            Image.new("RGB", (90 + i * 4, 140), (20 + i * 35, 60, 125)).save(path)
            self.files.append(str(path))
        with patch("tkinter.filedialog.askopenfilenames", return_value=self.files):
            self.app.select_files_batch()
        self.assertEqual([t["source_paths"] for t in self.app.batch_tasks],
                         [self.files[:2], self.files[2:4], self.files[4:6]])
        self.app.prepare_print_context = Mock(return_value=({"name": "test"}, "dc", None))
        self.app.print_tasks_with_win32 = Mock()
        self.app.close_system_print_context = Mock()

    def test_checked_pages_and_current_preview_are_independent(self):
        app = self.app
        rows = app.task_listbox.rows
        rows[0].winfo_children()[0].invoke()
        rows[2].winfo_children()[0].invoke()
        app.task_listbox._choose(1)
        app.print_checked_button.invoke()
        submitted = app.print_tasks_with_win32.call_args.args[0]
        self.assertEqual([id(t) for t in submitted], [id(app.batch_tasks[i]) for i in (0, 2)])
        self.assertEqual(app.preview_task_index, 1)
        app.single_print_current()
        self.assertIs(app.print_tasks_with_win32.call_args.args[0][0], app.batch_tasks[1])
        app.remove_selected_task()
        self.assertEqual([t["checked_for_print"] for t in app.batch_tasks], [True, True])
        app.check_all_sheets(False)
        self.assertEqual(str(app.print_checked_button["state"]), "disabled")
        app.batch_print_queue()
        self.assertEqual(len(app.print_tasks_with_win32.call_args.args[0]), 2)
        self.errors.assert_not_called()

    def test_resize_and_tk_scaling_preserve_print_pixels(self):
        app = self.app
        def fingerprint(image):
            return image.size, sha256(image.tobytes()).digest()
        task = app.batch_tasks[0]
        base = fingerprint(task["image"])
        for scaling, size in ((1.0, "1120x720"), (1.5, "1320x820"), (2.0, "1260x760")):
            self.root.tk.call("tk", "scaling", scaling)
            self.root.geometry(size)
            self.root.update()
            app.refresh_visible_preview()
            canvas = app.preview_canvas
            image_item = next(item for item in canvas.find_all() if canvas.type(item) == "image")
            left, top, right, bottom = canvas.bbox(image_item)
            self.assertGreaterEqual(min(left, top), 0)
            self.assertLessEqual(right, canvas.winfo_width())
            self.assertLessEqual(bottom, canvas.winfo_height())
            self.assertEqual(fingerprint(task["image"]), base)
            self.assertEqual(app.preview_task_index, 0)
        app.on_layout_changed()
        self.assertIsNone(app.preview_task_index)
        self.assertFalse(app.task_listbox.curselection())
        image = app.combined_image
        app.refresh_visible_preview()
        self.assertIs(app.combined_image, image)
        app.rotate_photo(0)
        self.assertEqual(fingerprint(task["image"]), base)

    def test_odd_batch_blank_and_two_files_dropped_over_existing_photos(self):
        app = self.app
        with patch("tkinter.filedialog.askopenfilenames", return_value=self.files[:1]), \
             patch.object(app, "resolve_odd_batch_photo", return_value=("blank", None)):
            app.select_files_batch()
        last = app.batch_tasks[-1]
        self.assertEqual(last["allow_blank_slot"], 1)
        self.assertTrue(app.validate_position(last)["ok"])
        app.load_demo_images()
        data = self.root.tk.call("list", *self.files[2:4])
        app.on_drop(type("Drop", (), {"data": data})())
        self.assertEqual(app.original_paths, self.files[2:4])
        self.errors.assert_not_called()

    def test_mixed_stock_can_cancel_between_jobs(self):
        app = self.app
        app.layout_mode.set("5寸整张")
        app.on_layout_changed()
        app.add_task()
        with patch.object(messagebox, "askokcancel", return_value=False):
            app.batch_print_queue()
        self.assertEqual(app.print_tasks_with_win32.call_count, 1)
        self.assertEqual(len(app.print_tasks_with_win32.call_args.args[0]), 3)
        self.assertEqual(len(app.batch_tasks), 4)

    def test_advanced_controls_and_file_export(self):
        app = self.app
        app.open_advanced_calibration()
        self.root.update()
        controls = []
        def visit(widget):
            controls.append(widget)
            for child in widget.winfo_children():
                visit(child)
        visit(app.advanced_window)
        sliders = [widget for widget in controls if isinstance(widget, tk.Scale)]
        middle = next(s for s in sliders if str(s["variable"]) == str(app.middle_margin_mm))
        middle.set(3)
        self.root.update()
        task, errors = app.build_current_task()
        self.assertEqual(errors, [])
        self.assertAlmostEqual(task["geometry"]["middle_margin_px"] * 25.4 / task["dpi"], 3, delta=.05)
        app.move_photo(0, 5, -5)
        app.reset_all()
        self.assertEqual(app.horizontal_offset, [0, 0])
        exported = Path(self.temp) / "result.png"
        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(exported)):
            app.save_image()
        with Image.open(exported) as image:
            self.assertEqual(image.size, app.combined_image.size)
            self.assertAlmostEqual(image.info["dpi"][0], 300, delta=.1)
        app.advanced_window.destroy()
        app.clear_all()
        self.assertIsNone(app.combined_image)
        self.assertEqual(len(app.batch_tasks), 3)
        self.errors.assert_not_called()

    def test_mixed_paper_job_does_not_silently_switch_printers(self):
        app = self.app
        app.layout_mode.set("5寸整张")
        app.on_layout_changed()
        app.add_task()
        app.prepare_print_context.side_effect = [
            ({"name": "前台"}, "dc1", None), ({"name": "后室"}, "dc2", None)]
        with patch.object(messagebox, "askokcancel", side_effect=[True, False]) as prompts:
            app.batch_print_queue()
        self.assertEqual(prompts.call_count, 2)
        self.assertEqual(app.print_tasks_with_win32.call_count, 1)
        self.assertEqual(app.close_system_print_context.call_count, 2)
        self.assertIn("3 页", app.status_var.get())

    def test_calibration_save_failure_restores_controls_and_previous_file(self):
        app = self.app
        app.selected_printer_name.set("test")
        target = app.calibration_target()
        app.save_paper_offsets(target.printer, target.paper_mm, 1.2, -0.8)
        saved = Path(configuration.CONFIG_FILE).read_bytes()
        app.open_advanced_calibration()
        self.root.update()
        controls, pending = [], [app.advanced_window]
        while pending:
            widget = pending.pop(0)
            controls.append(widget)
            pending.extend(widget.winfo_children())
        sliders = [w for w in controls if isinstance(w, tk.Scale)]
        reset = next(w for w in controls if isinstance(w, tk.Button) and w["text"] == "重置打印画面微调")
        with patch.object(configuration.os, "replace", side_effect=OSError("测试保存失败")), \
             patch.object(self.root, "report_callback_exception") as callback_errors:
            sliders[0].set(4.3)
            self.root.update()
            self.errors.assert_called_once()
            reset.invoke()
            self.root.update()
            self.assertEqual(self.errors.call_count, 2)
            callback_errors.assert_not_called()
        self.assertEqual(tuple(s.get() for s in sliders[:2]), (1.2, -0.8))
        self.assertEqual(app.calibration_offsets_for(target.printer, target.layout, target.paper_mm), (1.2, -0.8))
        self.assertEqual(Path(configuration.CONFIG_FILE).read_bytes(), saved)
        # Once saving is available again, an ordinary slider change persists normally.
        sliders[1].set(-1.4)
        self.root.update()
        app.printer_calibration.clear()
        app.load_config()
        self.assertEqual(app.calibration_offsets_for(target.printer, target.layout, target.paper_mm), (1.2, -1.4))

    def test_calibration_from_previewed_collage_saves_physical_stock_and_direction(self):
        app = self.app
        app.selected_printer_name.set("test")
        app.printer_calibration = {"test": {"6寸+4寸": {"x": 1, "y": 2}}}
        for stock in ("7寸", "8寸", "A4"):
            opts = CollageOptions(paper=stock, orientation="横向")
            paper = PAPERS[stock][::-1]
            sheet = build_collage_task(self.files[:2], opts, paper, 150)
            app.batch_tasks.append(sheet)
            app.update_task_list()
            app.task_listbox._choose(len(app.batch_tasks) - 1)
            app.open_advanced_calibration()
            self.root.update()

            controls = []
            def collect(widget):
                controls.append(widget)
                for child in widget.winfo_children():
                    collect(child)
            collect(app.advanced_window)
            sliders = [w for w in controls if isinstance(w, tk.Scale)]
            sliders[0].set(1.2)
            sliders[1].set(-0.8)
            self.root.update()
            # Freeze the dialog target even if the controller later displays another sheet.
            app.preview_task_index = 0
            chart = next(w for w in controls if isinstance(w, tk.Button) and w["text"] == "打印中心十字校准图")
            chart.invoke()
            task = app.print_tasks_with_win32.call_args.args[0][0]
            self.assertEqual((task["paper_mm"], task["dpi"], task["size"]), (paper, 150, sheet["size"]))
            self.assertEqual(task["kind"], "calibration")
            self.assertEqual(app.calibration_offsets_for("test", stock+" · 九宫格", paper), (1.2, -0.8))
            self.assertEqual(app.calibration_offsets_for("test", sheet["layout"], paper[::-1]), (0, 0))
            self.assertEqual(app.calibration_offsets_for("另一台", sheet["layout"], paper), (0, 0))
            self.assertEqual(app.calibration_offsets_for("test", "6寸+4寸"), (1, 2))
            # Swapping printers in a driver dialog must not submit the first printer's chart.
            app.prepare_print_context.return_value = ({"name": "另一台"}, "dc", None)
            app.print_tasks_with_win32.reset_mock()
            chart.invoke()
            app.print_tasks_with_win32.assert_not_called()
            app.prepare_print_context.return_value = ({"name": "test"}, "dc", None)
            app.advanced_window.destroy()
        app.printer_calibration.clear()
        app.load_config()
        self.assertEqual(app.calibration_offsets_for("test", "A4 · 四宫格", PAPERS["A4"][::-1]), (1.2, -0.8))
