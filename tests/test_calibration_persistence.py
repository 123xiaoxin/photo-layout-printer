import copy
import unittest
from unittest.mock import Mock

from photo_layout.configuration import ConfigurationMixin, paper_profile_key
from photo_layout.specifications import LAYOUT_OPTIONS


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class CalibrationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.app = ConfigurationMixin()
        self.paper = LAYOUT_OPTIONS["6寸整张"]["paper_mm"]
        self.key = paper_profile_key(self.paper)
        self.app.selected_printer_name = Value("Canon G500 series")
        self.app.layout_mode = Value("6寸整张")
        self.app.print_offset_x_mm = Value(1.2)
        self.app.print_offset_y_mm = Value(-0.8)
        self.app.printer_calibration = {
            "Canon G500 series": {self.key: {"x": 1.2, "y": -0.8},
                                 "5寸整张": {"x": 0.4, "y": 0.5}},
            "EPSON L805 Series": {self.key: {"x": 2, "y": 3}},
        }
        self.app.printer_aliases = {"canon g500 series": "前台相片机"}
        self.app.follow_system_printer = Value(False)
        self.app.manual_printer_name = "Canon G500 series"
        self.app.save_config = Mock(return_value=True)

    def test_success_saves_only_target_profile_and_keeps_previous_snapshot(self):
        app = self.app
        previous = app.printer_calibration
        snapshot = copy.deepcopy(previous)
        self.assertTrue(app.save_paper_offsets("Canon G500 series", self.paper, 2.5, -1.5))
        self.assertEqual(previous, snapshot)
        self.assertEqual(app.calibration_offsets_for("Canon G500 series", "6寸整张"), (2.5, -1.5))
        self.assertEqual(app.calibration_offsets_for("EPSON L805 Series", "6寸整张"), (2, 3))
        self.assertEqual(app.calibration_offsets_for("Canon G500 series", "5寸整张"), (0.4, 0.5))
        self.assertEqual((app.print_offset_x_mm.get(), app.print_offset_y_mm.get()), (2.5, -1.5))
        self.assertEqual(app.printer_aliases, {"canon g500 series": "前台相片机"})
        self.assertFalse(app.follow_system_printer.get())
        self.assertEqual(app.manual_printer_name, "Canon G500 series")
        app.save_config.assert_called_once()

    def test_failed_save_restores_memory_and_editor_offsets(self):
        app = self.app
        previous = app.printer_calibration
        snapshot = copy.deepcopy(previous)
        app.last_config_error = "磁盘已满"
        app.save_config.return_value = False
        app.print_offset_x_mm.set(7)
        app.print_offset_y_mm.set(8)
        app.get_layout_base = Mock(return_value={"paper_mm": self.paper})
        with self.assertRaisesRegex(OSError, "磁盘已满"):
            app.save_template_offsets()
        self.assertIs(app.printer_calibration, previous)
        self.assertEqual(app.printer_calibration, snapshot)
        self.assertEqual((app.print_offset_x_mm.get(), app.print_offset_y_mm.get()), (1.2, -0.8))

    def test_save_exception_does_not_leave_new_printer_profile(self):
        app = self.app
        previous = app.printer_calibration
        app.save_config.side_effect = RuntimeError("无法替换配置文件")
        with self.assertRaisesRegex(OSError, "无法替换配置文件"):
            app.save_paper_offsets("新打印机", self.paper, 4, 5)
        self.assertIs(app.printer_calibration, previous)
        self.assertNotIn("新打印机", app.printer_calibration)
        self.assertEqual((app.print_offset_x_mm.get(), app.print_offset_y_mm.get()), (1.2, -0.8))


if __name__ == "__main__":
    unittest.main()
