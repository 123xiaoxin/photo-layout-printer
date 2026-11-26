"""Real Tk regression coverage for batch editing and shared page settings."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from photo_layout import configuration
from photo_layout.collage_layout import CollageOptions, build_collage_task
from photo_layout.specifications import FIT_MODE_EQUAL_BORDER, FIT_MODE_ADAPT
from photo_layout_printer import PhotoLayoutPrinter


def fingerprint(image):
    return image.size, sha256(image.tobytes()).digest()


def controls(widget):
    for child in widget.winfo_children():
        yield child
        yield from controls(child)


class BatchEditingUiTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.temp = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.context.enter_context(patch.object(configuration, "CONFIG_FILE", str(self.temp / "settings.json")))
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.attributes("-alpha", 0)
        self.callback_errors = self.context.enter_context(patch.object(self.root, "report_callback_exception"))
        self.errors = self.context.enter_context(patch.object(messagebox, "showerror"))
        self.context.enter_context(patch.object(messagebox, "showwarning"))
        self.context.enter_context(patch.object(messagebox, "showinfo"))
        self.app = PhotoLayoutPrinter(self.root)
        self.app.layout_mode.set("5寸+3寸")
        self.app.margin_mm.set(1)
        self.app.on_layout_changed()
        self.files = []
        for i in range(6):
            path = self.temp / f"中文照片 {i}.png"
            image = Image.new("RGB", (110 + 7 * i, 170), (20 + i * 30, 55, 95))
            ImageDraw.Draw(image).rectangle((0, 0, 45, 60), fill=(220, 180 - i * 20, 35))
            image.save(path)
            self.files.append(str(path))
        with patch("tkinter.filedialog.askopenfilenames", return_value=self.files):
            self.app.select_files_batch()
        self.app.prepare_print_context = Mock(return_value=({"name": "test"}, "dc", None))
        self.app.print_tasks_with_win32 = Mock()
        self.app.close_system_print_context = Mock()
        self.root.update()

    def tearDown(self):
        self.callback_errors.assert_not_called()
        self.errors.assert_not_called()

    def test_second_group_rotation_and_replacement_stay_on_that_group(self):
        app = self.app
        before = [fingerprint(task["image"]) for task in app.batch_tasks]
        app.batch_tasks[0]["checked_for_print"] = True
        app.batch_tasks[2]["checked_for_print"] = True
        app.update_task_list()
        app.task_listbox._choose(1)
        self.assertEqual(app.original_paths, self.files[2:4])
        self.assertIn("中文照片 2", app.photo_meta_vars[0].get())
        rotate = next(w for w in controls(app.drop1_frame)
                      if isinstance(w, tk.Button) and w["text"] == "旋转")
        rotate.invoke()
        self.assertEqual(app.preview_task_index, 1)
        self.assertEqual(app.task_listbox.curselection(), (1,))
        self.assertEqual([t["rotations"] for t in app.batch_tasks], [[0, 0], [90, 0], [0, 0]])
        self.assertNotEqual(fingerprint(app.batch_tasks[1]["image"]), before[1])
        self.assertEqual([fingerprint(app.batch_tasks[i]["image"]) for i in (0, 2)],
                         [before[i] for i in (0, 2)])
        # Returning to a group uses its retained source pixels, even if the
        # originally imported file has moved or been removed.
        Path(self.files[2]).unlink()
        for index in (0, 2, 1):
            app.task_listbox._choose(index)
            self.root.update()
            self.assertEqual(app.original_paths, self.files[index * 2:index * 2 + 2])
        self.assertEqual(app.rotation_angles, [90, 0])
        self.assertEqual([t.get("checked_for_print", False) for t in app.batch_tasks], [True, False, True])
        app.load_image(self.files[4], 1)
        self.assertEqual(app.batch_tasks[1]["source_paths"], [self.files[2], self.files[4]])
        self.assertEqual(app.batch_tasks[1]["rotations"], [90, 0])
        self.assertEqual(app.preview_task_index, 1)

    def test_shared_three_mm_updates_every_group_and_preserves_print_selection(self):
        app = self.app
        tasks = app.batch_tasks[:]
        app.task_listbox.rows[0].winfo_children()[0].invoke()
        app.task_listbox.rows[2].winfo_children()[0].invoke()
        app.task_listbox._choose(1)
        app.rotate_photo(0)
        app.fit_mode.set(FIT_MODE_EQUAL_BORDER)
        app.on_fit_mode_changed()
        app.margin_slider.set(3)
        self.root.update()
        self.assertEqual(app.margin_slider.value_label["text"], "3.0 mm")
        self.assertEqual(app.preview_task_index, 1)
        self.assertEqual(app.task_listbox.curselection(), (1,))
        self.assertEqual([t["rotations"] for t in tasks], [[0, 0], [90, 0], [0, 0]])
        for i, task in enumerate(tasks):
            self.assertIs(task, app.batch_tasks[i])
            self.assertEqual(task["margin_mm"], 3)
            self.assertEqual(task["fit_mode"], FIT_MODE_EQUAL_BORDER)
            self.assertTrue(task["validation"]["ok"])
            for slot in task["geometry"]["slots"]:
                frame, photo = slot["frame"], slot["photo"]
                for pixels in (photo[0] - frame[0], photo[1] - frame[1],
                               frame[2] - photo[2], frame[3] - photo[3]):
                    self.assertAlmostEqual(pixels * 25.4 / task["dpi"], 3, delta=.09)
        app.print_checked_sheets()
        self.assertEqual([id(t) for t in app.print_tasks_with_win32.call_args.args[0]],
                         [id(tasks[0]), id(tasks[2])])
        app.single_print_current()
        self.assertIs(app.print_tasks_with_win32.call_args.args[0][0], tasks[1])
        for index in (0, 1):
            app.task_listbox._choose(index)
            self.root.update()
            self.assertEqual(app.margin_mm.get(), 3)
            self.assertEqual(app.margin_slider.value_label["text"], "3.0 mm")
        self.assertEqual(app.rotation_angles, [90, 0])

    def test_only_changed_settings_propagate_and_restoring_controls_never_propagates(self):
        app = self.app
        # Create a second template through the normal new-draft action. Its
        # different DPI/fit are independent of the setting changed afterward.
        app.layout_mode.set("5寸整张")
        app.on_layout_changed()
        app.dpi.set(600)
        app.fit_mode.set(FIT_MODE_ADAPT)
        app.margin_mm.set(4)
        app.reprocess_all_and_update()
        app.add_task()
        single = app.batch_tasks[-1]
        app.task_listbox._choose(1)
        self.root.update()
        self.assertEqual(app.margin_slider.value_label["text"], "1.0 mm")
        self.assertEqual(single["margin_mm"], 4)
        before = [fingerprint(t["image"]) for t in app.batch_tasks]
        for index in (3, 1, 3, 1):
            app.task_listbox._choose(index)
            self.root.update()
        self.assertEqual([fingerprint(t["image"]) for t in app.batch_tasks], before)
        app.move_photo(0, 5, 0)
        self.assertEqual(app.batch_tasks[1]["offsets"][0], (5, 0))
        self.assertEqual(app.batch_tasks[0]["offsets"][0], (0, 0))
        app.margin_mm.set(3)
        app.on_settings_changed(reprocess=True)
        self.assertEqual(app.batch_tasks[1]["offsets"][0], (5, 0))
        self.assertEqual(single["margin_mm"], 3)
        self.assertEqual((single["layout"], single["dpi"], single["fit_mode"]),
                         ("5寸整张", 600, FIT_MODE_ADAPT))
        self.assertEqual(app.preview_task_index, 1)
        app.auto_rotate.set(False)
        app.enable_margin.set(False)
        app.middle_margin_mm.set(1)
        app.draw_cut_line.set(False)
        app.show_guides.set(False)
        app.on_settings_changed(reprocess=True)
        for task in app.batch_tasks:
            self.assertFalse(task["auto_rotate"])
            self.assertFalse(task["enable_margin"])
            self.assertFalse(task["draw_cut_line"])
            self.assertFalse(task["show_guides"])
            self.assertEqual(task["middle_margin_mm"], 1)
        app.task_listbox._choose(3)
        self.assertIsNone(app.original_images[1])
        self.assertIsNone(app.processed_photos[1])
        self.assertEqual(app.original_paths[1], "")
        self.assertEqual(app.photo_state_vars[1].get(), "不使用")
        self.assertEqual(app.drop2_label["text"], "本规格只使用照片 1")
        buttons = [w for w in controls(app.drop2_frame) if isinstance(w, tk.Button)]
        self.assertTrue(all(str(w["state"]) == "disabled" for w in buttons))
        one_before = fingerprint(single["image"])
        app.load_image(self.files[1], 1)
        app.rotate_photo(1)
        self.assertEqual(fingerprint(single["image"]), one_before)
        app.rotate_photo(0)
        self.assertEqual(single["source_count"], 1)

    def test_blank_slot_collage_and_new_draft_keep_their_own_content(self):
        app = self.app
        with patch("tkinter.filedialog.askopenfilenames", return_value=self.files[:1]), \
             patch.object(app, "resolve_odd_batch_photo", return_value=("blank", None)):
            app.select_files_batch()
        blank = app.batch_tasks[-1]
        app.rotate_photo(0)
        self.assertIsNone(app.original_images[1])
        self.assertEqual(app.photo_state_vars[1].get(), "等待导入")
        self.assertEqual(app.drop2_label["text"], "拖入或选择照片 2")
        self.assertEqual(blank["allow_blank_slot"], 1)
        self.assertTrue(blank["validation"]["ok"])
        collage = build_collage_task(self.files[:3], CollageOptions(), (127, 88.9), 150)
        app.batch_tasks.append(collage)
        app.update_task_list()
        app.task_listbox._choose(4)
        before = fingerprint(collage["image"])
        self.assertTrue(all(image is None for image in app.original_images))
        self.assertEqual(str(app.margin_slider["state"]), "disabled")
        app.rotate_photo(0)
        app.load_image(self.files[0], 0)
        app.update_preview()
        self.assertEqual(app.preview_task_index, 4)
        self.assertEqual(fingerprint(collage["image"]), before)
        app.task_listbox._choose(3)
        app.margin_slider.set(3)
        self.root.update()
        self.assertTrue(blank["validation"]["ok"])
        self.assertEqual(blank["allow_blank_slot"], 1)
        self.assertEqual(fingerprint(collage["image"]), before)
        app.load_image(self.files[1], 1)
        self.assertIsNone(blank["allow_blank_slot"])
        self.assertEqual(blank["source_count"], 2)
        frozen = [fingerprint(t["image"]) for t in app.batch_tasks]
        app.clear_all()
        self.assertIsNone(app.preview_task_index)
        self.assertFalse(app.task_listbox.curselection())
        self.assertIsNone(app.combined_image)
        app.load_demo_images()
        self.assertIsNone(app.preview_task_index)
        self.assertEqual([fingerprint(t["image"]) for t in app.batch_tasks], frozen)


if __name__ == "__main__":
    unittest.main()
