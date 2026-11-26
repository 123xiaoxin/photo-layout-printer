"""Check page-profile UI transactions without opening a physical printer dialog."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox
import unittest
from unittest.mock import patch

from photo_layout import configuration
from photo_layout.print_orientation import PAPER_ORIENTATION_LANDSCAPE
from photo_layout.specifications import PRINT_METHOD_DIRECT, PRINT_METHOD_SYSTEM
from photo_layout_printer import PhotoLayoutPrinter


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class PageSettingsUiTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        folder = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.config = folder / "settings.json"
        self.context.enter_context(patch.object(configuration, "CONFIG_FILE", str(self.config)))
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        self.errors = self.context.enter_context(patch.object(messagebox, "showerror"))
        self.app = PhotoLayoutPrinter(self.root)
        self.app.selected_printer_name.set("测试相片机")
        self.app.printer_names = ["测试相片机"]
        self.app.print_method.set(PRINT_METHOD_SYSTEM)
        self.app.save_config()
        self.target = self.app.calibration_target()

    def save_fake_profile(self, target, owner):
        return self.app.save_driver_page_profile(target.printer, target.paper_mm,
                                                b"fixture-private-driver-settings", {"driver": "fixture"})

    def test_save_also_persists_direct_print_and_cancel_leaves_both_unchanged(self):
        app = self.app
        with patch.object(app, "edit_printer_page_settings", side_effect=self.save_fake_profile):
            self.assertTrue(app.configure_page_profile(self.target, self.root))
        self.assertEqual(app.print_method.get(), PRINT_METHOD_DIRECT)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["print_method"], PRINT_METHOD_DIRECT)
        self.assertIn("已保存", app.page_settings_summary_var.get())
        saved = self.config.read_bytes()
        app.print_method.set(PRINT_METHOD_SYSTEM)
        with patch.object(app, "edit_printer_page_settings", return_value=False):
            self.assertFalse(app.configure_page_profile(self.target, self.root))
        self.assertEqual(app.print_method.get(), PRINT_METHOD_SYSTEM)
        self.assertEqual(self.config.read_bytes(), saved)
        self.errors.assert_not_called()

    def test_failed_atomic_save_restores_ui_mode_and_original_file(self):
        saved = self.config.read_bytes()
        with patch.object(self.app, "edit_printer_page_settings", side_effect=self.save_fake_profile), \
             patch.object(configuration.os, "replace", side_effect=OSError("测试写入失败")):
            self.assertFalse(self.app.configure_page_profile(self.target, self.root))
        self.assertEqual(self.app.print_method.get(), PRINT_METHOD_SYSTEM)
        self.assertIsNone(self.app.get_driver_page_profile(self.target.printer, self.target.paper_mm))
        self.assertEqual(self.config.read_bytes(), saved)
        self.errors.assert_called_once()

    def test_status_tracks_printer_and_direction_without_reusing_another_profile(self):
        self.save_fake_profile(self.target, self.root)
        self.app.refresh_page_settings_summary()
        self.assertIn("已保存", self.app.page_settings_summary_var.get())
        self.app.paper_orientation.set(PAPER_ORIENTATION_LANDSCAPE)
        self.assertIn("尚未保存", self.app.page_settings_summary_var.get())
        self.app.selected_printer_name.set("另一台相片机")
        self.assertIn("尚未保存", self.app.page_settings_summary_var.get())
        self.assertTrue(self.app.reset_page_profile(self.target, self.root))
        self.assertIsNone(self.app.get_driver_page_profile(self.target.printer, self.target.paper_mm))

    def test_dialog_keeps_the_target_shown_when_it_opened(self):
        app = self.app
        with patch.object(app, "refresh_printer_list"):
            app.open_page_settings()
        window = app.page_settings_window
        self.assertTrue(window.winfo_exists())
        edit = next(w for w in descendants(window)
                    if isinstance(w, tk.Button) and w["text"] == "设置页面布局并保存…")
        # Even an unrelated programmatic change must not redirect the displayed dialog.
        app.selected_printer_name.set("另一台相片机")
        with patch.object(app, "edit_printer_page_settings", side_effect=self.save_fake_profile) as native:
            edit.invoke()
        self.assertEqual(native.call_args.kwargs["target"], self.target)
        self.assertIs(native.call_args.kwargs["owner"], window)
        self.assertIsNotNone(app.get_driver_page_profile(self.target.printer, self.target.paper_mm))
        self.assertIsNone(app.get_driver_page_profile("另一台相片机", self.target.paper_mm))
        self.errors.assert_not_called()

