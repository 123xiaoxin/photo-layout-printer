import json
import unittest
from unittest.mock import Mock, mock_open, patch

from photo_layout.configuration import ConfigurationMixin
from photo_layout.printing import PrintingMixin
from photo_layout.specifications import PRINT_METHOD_DIRECT


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Selection(PrintingMixin, ConfigurationMixin):
    def __init__(self):
        self.printer_combo = Mock()
        self.printer_names = []
        self.printer_names = []
        self.status_var = Value("")
        self.print_method = Value(PRINT_METHOD_DIRECT)
        self.follow_system_printer = Value(True)
        self.selected_printer_name = Value("")
        self.manual_printer_name = ""
        self.legacy_selected_printer = ""
        self.load_template_offsets = Mock()
        self.save_config = Mock()
        self.list_available_printers = Mock(return_value=(["甲", "乙", "PDF"], []))
        self.windows_default_printer = Mock(return_value="乙")
        self.open_direct_print_context = Mock(return_value=({"name": "乙"}, Mock(), None, [], False))
        self.open_system_print_dialog = Mock()
        for key, value in dict(layout_mode="6寸整张", enable_margin=True, margin_mm=3,
                               fit_mode="裁切填满", middle_margin_mm=0, show_guides=True,
                               draw_cut_line=True, auto_rotate=True, dpi=300).items():
            setattr(self, key, Value(value))
        self.rotation_angles = self.horizontal_offset = self.vertical_offset = [0, 0]


class PrinterSelectionTests(unittest.TestCase):
    def setUp(self):
        self.app = Selection()

    def test_auto_uses_true_default_regardless_of_enumeration_order(self):
        app = self.app
        app.refresh_printer_list()
        self.assertEqual(app.selected_printer_name.get(), "乙")
        app.windows_default_printer.return_value = "甲"
        app.open_selected_print_context([{}])
        self.assertEqual(app.selected_printer_name.get(), "甲")
        app.open_direct_print_context.assert_called_once()

    def test_pinned_printer_never_changes_on_refresh_or_at_submit(self):
        app = self.app
        app.selected_printer_name.set("甲")
        app.on_printer_selected()
        self.assertFalse(app.follow_system_printer.get())
        app.list_available_printers.return_value = (["乙", "PDF"], [])
        _, _, _, errors, _ = app.open_selected_print_context([{}])
        self.assertTrue(errors)
        self.assertEqual(app.selected_printer_name.get(), "甲")
        app.open_direct_print_context.assert_not_called()
        app.list_available_printers.return_value = (["乙", "甲"], [])
        app.open_selected_print_context([{}])
        self.assertEqual(app.selected_printer_name.get(), "甲")
        app.open_direct_print_context.assert_called_once()

    def test_disappearing_previous_default_does_not_redirect_pending_job(self):
        app = self.app
        app.refresh_printer_list()
        app.list_available_printers.return_value = (["PDF"], [])
        app.windows_default_printer.return_value = "PDF"
        _, _, _, errors, _ = app.open_selected_print_context([{}])
        self.assertTrue(errors)
        app.open_direct_print_context.assert_not_called()
        self.assertEqual(app.selected_printer_name.get(), "PDF")
        app.open_selected_print_context([{}])
        app.open_direct_print_context.assert_called_once()

    def test_no_default_uses_only_unambiguous_single_queue(self):
        app = self.app
        app.windows_default_printer.return_value = ""
        self.assertTrue(app.refresh_printer_list()[1])
        self.assertEqual(app.selected_printer_name.get(), "")
        app.list_available_printers.return_value = (["甲"], [])
        self.assertFalse(app.refresh_printer_list()[1])
        self.assertEqual(app.selected_printer_name.get(), "甲")

    def test_auto_manual_toggle_restores_last_explicit_choice(self):
        app = self.app
        app.selected_printer_name.set("甲")
        app.on_printer_selected()
        app.follow_system_printer.set(True)
        app.on_follow_system_printer_changed()
        self.assertEqual(app.selected_printer_name.get(), "乙")
        app.follow_system_printer.set(False)
        app.on_follow_system_printer_changed()
        self.assertEqual(app.selected_printer_name.get(), "甲")

    def load(self, data, host):
        app = Selection()
        with patch("photo_layout.configuration.platform.node", return_value=host), \
                patch("photo_layout.configuration.os.path.exists", return_value=True), \
                patch("builtins.open", mock_open(read_data=json.dumps(data))):
            app.load_config()
        app.refresh_printer_list()
        return app

    def test_legacy_preference_equal_to_default_becomes_automatic(self):
        app = self.load({"selected_printer_name": "乙"}, "PC")
        self.assertTrue(app.follow_system_printer.get())
        app = self.load({"selected_printer_name": "甲"}, "PC")
        self.assertFalse(app.follow_system_printer.get())
        self.assertEqual(app.selected_printer_name.get(), "甲")

    def test_copied_project_uses_new_hosts_default(self):
        data = {"selected_printer_name": "甲",
                "printer_preferences": {"shop-a": {"follow_default": False, "fixed_queue": "甲"}}}
        old = self.load(data, "SHOP-A")
        self.assertFalse(old.follow_system_printer.get())
        self.assertEqual(old.selected_printer_name.get(), "甲")
        new = self.load(data, "SHOP-B")
        self.assertTrue(new.follow_system_printer.get())
        self.assertEqual(new.selected_printer_name.get(), "乙")

    def test_manual_choice_persists_across_restart_and_auto_keeps_its_memory(self):
        app = self.load({}, "SHOP")
        app.selected_printer_name.set("甲")
        app.on_printer_selected()
        for follow in (False, True):
            app.follow_system_printer.set(follow)
            app.on_follow_system_printer_changed()
            with patch("photo_layout.configuration.platform.node", return_value="SHOP"), \
                    patch("photo_layout.configuration.write_config_file") as write:
                ConfigurationMixin.save_config(app)
            saved = write.call_args.args[0]
            restored = self.load(saved, "SHOP")
            self.assertEqual(restored.follow_system_printer.get(), follow)
            self.assertEqual(restored.selected_printer_name.get(), "乙" if follow else "甲")
            self.assertEqual(restored.manual_printer_name, "甲")

    def test_aliases_are_local_to_host_and_clear_back_to_real_name(self):
        app = self.load({"printer_preferences": {"shop-b": {"aliases": {"pdf": "乙店归档"}}}}, "SHOP-A")
        app.save_config = ConfigurationMixin.save_config.__get__(app)
        with patch("photo_layout.configuration.platform.node", return_value="SHOP-A"), \
                patch("photo_layout.configuration.write_config_file") as write:
            app.set_printer_alias("PDF", "   前台校样   ")
            saved = write.call_args.args[0]
            self.assertEqual(self.load(saved, "SHOP-A").printer_display_name("PDF"), "前台校样 · PDF")
            self.assertEqual(self.load(saved, "SHOP-B").printer_alias_for("PDF"), "乙店归档")
            self.assertEqual(self.load(saved, "SHOP-C").printer_display_name("PDF"), "PDF")
            self.assertEqual(app.selected_printer_name.get(), "乙")
            app.set_printer_alias("pdf", " ")
            self.assertEqual(self.load(write.call_args.args[0], "SHOP-A").printer_display_name("PDF"), "PDF")

    def test_alias_cannot_hide_another_queue_or_reuse_its_alias(self):
        app = self.load({}, "SHOP")
        app.set_printer_alias("甲", "Desk Printer")
        for conflict in ("DESK PRINTER", " pdf "):
            with self.subTest(conflict=conflict), self.assertRaises(ValueError):
                app.set_printer_alias("乙", conflict)
        self.assertEqual(app.printer_alias_for("甲"), "Desk Printer")
        self.assertEqual(app.printer_alias_for("乙"), "")

    def test_failed_disk_save_leaves_previous_alias_and_host_preferences(self):
        app = self.load({"printer_preferences": {"shop": {"aliases": {"pdf": "原名"}}}}, "SHOP")
        app.save_config = ConfigurationMixin.save_config.__get__(app)
        with patch("photo_layout.configuration.platform.node", return_value="SHOP"), \
                patch("photo_layout.configuration.write_config_file", side_effect=OSError("磁盘已满")), \
                self.assertRaisesRegex(OSError, "磁盘已满"):
            app.set_printer_alias("PDF", "新名")
        self.assertEqual(app.printer_alias_for("PDF"), "原名")
        self.assertEqual(app.printer_preferences["shop"]["aliases"]["pdf"], "原名")
