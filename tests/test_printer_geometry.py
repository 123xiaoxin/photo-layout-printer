import json
import unittest
from unittest.mock import Mock, mock_open, patch

from PIL import Image, ImageDraw

from photo_layout.configuration import ConfigurationMixin
from photo_layout.printer_geometry import print_placement
from photo_layout.printing import PrintingMixin
from photo_layout.print_orientation import PAPER_ORIENTATION_AUTO
from photo_layout.specifications import PRINT_METHOD_DIRECT, PRINT_METHOD_SYSTEM


def capabilities(paper=(101.6, 152.4), dpi=(300, 300), margins=(0, 0, 0, 0)):
    width, height = [round(length * dots / 25.4) for length, dots in zip(paper, dpi)]
    left, top, right, bottom = margins
    return dict(name="测试驱动", physical_width=width, physical_height=height,
                horzres=width-left-right, vertres=height-top-bottom, offset_x=left,
                offset_y=top, logpixels_x=dpi[0], logpixels_y=dpi[1])


def sheet():
    return dict(paper_mm=(101.6, 152.4), image=Image.new("RGB", (400, 600), "black"), layout="6寸整张")


class PrinterGeometryTests(unittest.TestCase):
    def test_borderless_and_different_axis_resolutions(self):
        task = sheet()
        caps = capabilities(dpi=(600, 300))
        plan = print_placement(task, caps)
        self.assertEqual(plan.device_box, (0, 0, 2400, 1800))
        self.assertEqual(plan.scale, 1.0)
        self.assertFalse(plan.rotate_clockwise)

    def test_asymmetric_hardware_margins_stay_centre_aligned(self):
        caps = capabilities(margins=(40, 12, 8, 100))
        plan = print_placement(sheet(), caps)
        left, top, right, bottom = plan.physical_box
        self.assertEqual(left, caps["physical_width"] - right)
        self.assertEqual(top, caps["physical_height"] - bottom)
        self.assertEqual((left - 40, top - 12, right - 40, bottom - 12), plan.device_box)
        self.assertGreaterEqual(min(plan.device_box), 0)
        self.assertLessEqual(plan.device_box[2], caps["horzres"])
        self.assertLessEqual(plan.device_box[3], caps["vertres"])
        self.assertAlmostEqual(plan.scale, 1600/1800)

    def test_preexisting_blank_paper_is_used_without_shrinking(self):
        task = sheet()
        task["image"].paste("white", (0, 0, 400, 600))
        ImageDraw.Draw(task["image"]).rectangle((20, 20, 379, 579), fill="blue")
        caps = capabilities(margins=(40, 12, 8, 50))
        plan = print_placement(task, caps)
        self.assertEqual(plan.scale, 1.0)
        self.assertEqual(plan.device_box, (-40, -12, 1160, 1788))

    def test_g580_4x6_bordered_and_borderless(self):
        # Canon G580 published standard margins (left/top/right/bottom in mm).
        # This is a driver fixture. Production positioning reads the active DC.
        margins = tuple(round(mm * 600 / 25.4) for mm in (3.4, 3.0, 3.4, 5.0))
        caps = dict(capabilities(dpi=(600, 600), margins=margins), name="Canon G500 series")
        task = sheet()
        plan = print_placement(task, caps)
        x0, y0, x1, y1 = plan.physical_box
        self.assertLessEqual(abs((x0 + x1) - caps["physical_width"]), 1)
        self.assertLessEqual(abs((y0 + y1) - caps["physical_height"]), 1)
        self.assertGreaterEqual(x0, margins[0])
        self.assertGreaterEqual(y0, margins[3])
        task["image"] = Image.new("RGB", (400, 600), "white")
        ImageDraw.Draw(task["image"]).rectangle((22, 22, 377, 577), fill="blue")
        self.assertEqual(print_placement(task, caps).scale, 1.0)
        app = PrintingMixin()
        app.calibration_offsets_for = lambda name, template, paper_mm: (0, 0)
        full_page = dict(capabilities(), name="Canon G580")
        errors, warnings = app.validate_printer_fit(full_page, [task])
        self.assertFalse(errors)
        self.assertFalse(warnings)
        for queue, driver in (("照片店后柜", "Canon G500 series"), ("G500", ""),
                              ("网络照片打印机", "IPP Class Driver"), ("测试队列", "未知型号")):
            with self.subTest(queue=queue):
                renamed = dict(capabilities(), name=queue, driver_name=driver)
                errors, warnings = app.validate_printer_fit(renamed, [task])
                self.assertFalse(errors)
                self.assertFalse(warnings)
                self.assertEqual(renamed["_placements"][id(task)], full_page["_placements"][id(task)])

    def test_opposite_feed_and_manual_registration(self):
        caps = capabilities(paper=(152.4, 101.6), dpi=(600, 300))
        plan = print_placement(dict(sheet(), kind="calibration"), caps, (2.54, -2.54))
        self.assertTrue(plan.rotate_clockwise)
        self.assertEqual(plan.device_box, (60, 30, 3660, 1230))
        self.assertEqual(plan.scale, 1.0)

    def test_approximate_photo_form_and_reject_wrong_media(self):
        plan = print_placement(sheet(), capabilities(paper=(100, 150)))
        self.assertGreater(plan.scale, 0.98)
        with self.assertRaisesRegex(ValueError, "相纸"):
            print_placement(sheet(), capabilities(paper=(210, 297)))
        with self.assertRaisesRegex(ValueError, "驱动"):
            print_placement(sheet(), dict(capabilities(), logpixels_y=0))

    def test_one_job_with_both_orientations_of_the_same_media(self):
        app = PrintingMixin()
        size, errors = app.resolve_print_paper_mm([sheet(), {"paper_mm": (152.4, 101.6)}])
        self.assertEqual(size, (101.6, 152.4))
        self.assertFalse(errors)
        self.assertTrue(app.resolve_print_paper_mm([sheet(), {"paper_mm": (210, 297)}])[1])

    def test_draw_uses_same_rotation_and_rectangle_as_validation(self):
        # Exercise the spooler call sequence without submitting a job.
        app = PrintingMixin()
        app.calibration_offsets_for = lambda name, template, paper_mm: (0, 0)
        app.root, app.status_var = Mock(), Mock()
        task = sheet()
        task["image"].putpixel((0, 0), (255, 0, 0))
        caps = capabilities(paper=(152.4, 101.6), margins=(10, 5, 5, 20))
        errors, warnings = app.validate_printer_fit(caps, [task])
        self.assertFalse(errors)
        self.assertTrue(warnings)
        dc = Mock()
        with patch("PIL.ImageWin.Dib") as dib:
            app.print_tasks_with_win32([task], caps, printer_dc=dc)
            rotated = dib.call_args.args[0]
            self.assertEqual(rotated.size, (600, 400))
            self.assertEqual(rotated.getpixel((599, 0)), (255, 0, 0))
            dib.return_value.draw.assert_called_once_with(dc.GetHandleOutput.return_value,
                                                         caps["_placements"][id(task)].device_box)
        dc.EndDoc.assert_called_once()
        dc.AbortDoc.assert_not_called()

    def test_calibration_profiles_for_different_printers_and_templates(self):
        app = ConfigurationMixin()
        app.printer_calibration = {"喷墨": {"6寸整张": {"x": 1.2, "y": -0.1}}}
        self.assertEqual(app.calibration_offsets_for("喷墨", "6寸整张"), (1.2, -0.1))
        self.assertEqual(app.calibration_offsets_for("热升华", "6寸整张"), (0.0, 0.0))
        self.assertEqual(app.calibration_offsets_for("喷墨", "5寸整张"), (0.0, 0.0))

    def test_load_existing_printer_template_calibration(self):
        app = ConfigurationMixin()
        app.selected_printer_name = Mock()
        app.selected_printer_name.get.return_value = "Canon G500 series"
        app.layout_mode = Mock()
        app.layout_mode.get.return_value = "6寸+4寸"
        app.print_offset_x_mm, app.print_offset_y_mm = Mock(), Mock()
        saved = json.dumps({
            "selected_printer_name": "Canon G500 series",
            "print_offsets_by_template": {"6寸+4寸": {"x": 1.3, "y": -0.7}}
        })
        with patch("photo_layout.configuration.os.path.exists", return_value=True), \
                patch("builtins.open", mock_open(read_data=saved)):
            app.load_config()
        app.print_offset_x_mm.set.assert_called_with(1.3)
        app.print_offset_y_mm.set.assert_called_with(-0.7)
        self.assertEqual(app.calibration_offsets_for("另一台", "6寸+4寸"), (0.0, 0.0))

    def test_failed_page_aborts_job_and_stops_subsequent_sheets(self):
        app = PrintingMixin()
        app.root, app.status_var = Mock(), Mock()
        app.calibration_offsets_for = lambda name, template, paper_mm: (0, 0)
        dc = Mock()
        with patch("PIL.ImageWin.Dib") as dib:
            dib.return_value.draw.side_effect = OSError("驱动丢失连接")
            with self.assertRaises(OSError):
                app.print_tasks_with_win32([sheet(), sheet()], capabilities(), printer_dc=dc)
        dc.StartPage.assert_called_once()
        dc.AbortDoc.assert_called_once()
        dc.EndDoc.assert_not_called()

    @patch("photo_layout.printing.messagebox")
    def test_single_print_uses_selected_frozen_sheet(self, messages):
        app = PrintingMixin()
        task = sheet()
        app.preview_task_index, app.batch_tasks = 0, [task]
        app.prepare_print_context = Mock(return_value=({}, Mock(), None))
        app.close_system_print_context, app.print_tasks_with_win32 = Mock(), Mock()
        app.status_var = Mock()
        app.single_print_current()
        self.assertIs(app.print_tasks_with_win32.call_args.args[0][0], task)

    @patch("photo_layout.printing.messagebox")
    def test_inspect_uses_requested_driver_mode_releases_dc_and_never_spools(self, messages):
        for mode in (PRINT_METHOD_DIRECT, PRINT_METHOD_SYSTEM):
            with self.subTest(mode=mode):
                app = PrintingMixin()
                app.preview_task_index, app.batch_tasks = 0, [sheet()]
                app.print_method, app.status_var = Mock(), Mock()
                app.print_method.get.return_value = mode
                app.selected_printer_name = Mock()
                app.selected_printer_name.get.return_value = "测试驱动"
                app.refresh_printer_list = Mock(return_value=(["测试驱动"], []))
                app.printer_display_name = lambda name: f"前台 · {name}"
                app.calibration_offsets_for = lambda name, template, paper_mm: (0, 0)
                app.open_direct_print_context, app.open_system_print_dialog = Mock(), Mock()
                chosen = app.open_system_print_dialog if mode == PRINT_METHOD_SYSTEM else app.open_direct_print_context
                dc, cleanup = Mock(), Mock()
                caps = dict(capabilities(margins=(40, 12, 8, 100)), driver_name="Canon G500 series")
                chosen.return_value = caps, dc, cleanup, [], False
                report = app.inspect_preview_printer_placement()
                chosen.assert_called_once_with(tasks=app.batch_tasks, paper_orientation=PAPER_ORIENTATION_AUTO)
                dc.StartDoc.assert_not_called()
                dc.StartPage.assert_not_called()
                dc.DeleteDC.assert_called_once()
                cleanup.assert_called_once()
                for detail in ("批次 001", "前台 · ", "Canon G500 series", "驱动页面", "硬边距", "软件排版比例", "驱动公共缩放"):
                    self.assertIn(detail, report)


if __name__ == "__main__":
    unittest.main()
