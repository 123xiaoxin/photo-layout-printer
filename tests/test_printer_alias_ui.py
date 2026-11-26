"""Drive printer naming through the Tk controls, using isolated Windows queues and settings."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from photo_layout_printer import PhotoLayoutPrinter


class PrinterAliasWindowTests(unittest.TestCase):
    first = "EPSON L805 Series"
    second = "Canon G500 series (Copy 1)"

    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        folder = self.context.enter_context(tempfile.TemporaryDirectory())
        self.context.enter_context(patch("photo_layout.configuration.CONFIG_FILE", str(Path(folder) / "settings.json")))
        self.context.enter_context(patch("photo_layout.configuration.platform.node", return_value="测试工作站"))
        self.queues = self.context.enter_context(patch.object(
            PhotoLayoutPrinter, "list_available_printers", return_value=([self.first, self.second], [])))
        self.default = self.context.enter_context(patch.object(
            PhotoLayoutPrinter, "windows_default_printer", return_value=self.first))
        self.root = None
        self.addCleanup(self.close_window)
        self.start_window()

    def close_window(self):
        if self.root is not None:
            self.root.update()
            self.root.destroy()
            self.root = None

    def start_window(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.app = PhotoLayoutPrinter(self.root)
        self.root.update()

    def name_current_queue(self, name):
        widgets = [self.root]
        while widgets:
            widget = widgets.pop()
            if isinstance(widget, tk.Button) and widget["text"] == "命名":
                self.assertTrue(widget.winfo_ismapped())
                with patch("tkinter.simpledialog.askstring", return_value=name) as prompt:
                    widget.invoke()
                    self.root.update()
                    prompt.assert_called_once()
                return
            widgets.extend(widget.winfo_children())
        self.fail("打印机设置缺少可操作的命名按钮")

    def choose(self, label):
        combo = self.app.printer_combo
        combo.current(list(combo["values"]).index(label))
        combo.event_generate("<<ComboboxSelected>>")
        self.root.update()

    def test_rename_preserves_follow_and_windows_default_can_switch(self):
        app = self.app
        self.assertTrue(app.follow_system_printer.get())
        self.assertEqual(app.printer_combo.get(), self.first)
        self.name_current_queue("前台相片机")
        self.assertEqual(app.printer_combo.get(), f"前台相片机 · {self.first}")
        self.assertTrue(app.follow_system_printer.get())
        self.assertEqual(app.selected_printer_name.get(), self.first)

        self.default.return_value = self.second
        app.refresh_printer_list()
        self.assertTrue(app.follow_system_printer.get())
        self.assertEqual(app.selected_printer_name.get(), self.second)
        self.name_current_queue("后柜彩印")
        self.assertEqual(app.printer_combo.get(), f"后柜彩印 · {self.second}")
        self.assertTrue(app.follow_system_printer.get())
        self.assertIn(f"前台相片机 · {self.first}", app.printer_combo["values"])

    def test_select_named_queue_pin_restart_cancel_and_clear(self):
        self.name_current_queue("柜台一")
        self.choose(self.second)
        self.name_current_queue("柜台二")
        label = f"柜台二 · {self.second}"
        self.choose(f"柜台一 · {self.first}")
        self.choose(label)
        self.assertFalse(self.app.follow_system_printer.get())
        self.assertEqual(self.app.selected_printer_name.get(), self.second)
        # Queue enumeration order can change. Re-opening the project must still pick the exact queue.
        self.queues.return_value = ([self.second, self.first], [])
        self.close_window()
        self.start_window()
        app = self.app
        self.assertEqual(app.printer_combo.get(), label)
        self.assertFalse(app.follow_system_printer.get())
        self.assertEqual(app.manual_printer_name, self.second)
        with patch.object(app, "open_direct_print_context",
                          side_effect=lambda tasks, **kwargs: app.selected_printer_name.get()) as direct:
            self.assertEqual(app.open_selected_print_context([{}]), self.second)
            direct.assert_called_once()

        self.name_current_queue(None)
        self.assertEqual(app.printer_combo.get(), label)
        self.name_current_queue("")
        self.assertEqual(app.printer_combo.get(), self.second)
        self.assertFalse(app.follow_system_printer.get())
        self.close_window()
        self.start_window()
        self.assertEqual(self.app.printer_combo.get(), self.second)
        self.assertEqual(self.app.selected_printer_name.get(), self.second)
        self.assertIn(f"柜台一 · {self.first}", self.app.printer_combo["values"])


if __name__ == "__main__":
    unittest.main()
