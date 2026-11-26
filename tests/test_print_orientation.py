"""Whole-sheet direction, driver negotiation and calibration, without printing."""
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from photo_layout.batches import BatchesMixin
from photo_layout.configuration import ConfigurationMixin, paper_profile_key
from photo_layout.print_orientation import (
    PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE,
    orient_paper_size, orient_print_task,
)
from photo_layout.printing import PrintingMixin


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def sheet():
    image = Image.new("RGB", (12, 18), "white")
    ImageDraw.Draw(image).rectangle((3, 4, 8, 13), fill="blue")
    image.putpixel((3, 4), (255, 0, 0))
    return dict(image=image, paper_mm=(101.6, 152.4), size=image.size,
                layout="6寸整张", dpi=300)


def caps(paper):
    width, height = (round(mm * 10) for mm in paper)
    return dict(name="Canon G500 series", physical_width=width, physical_height=height,
                horzres=width, vertres=height, offset_x=0, offset_y=0,
                logpixels_x=254, logpixels_y=254)


class App(PrintingMixin, ConfigurationMixin, BatchesMixin):
    def __init__(self, orientation=PAPER_ORIENTATION_LANDSCAPE):
        self.paper_orientation = Value(orientation)
        self.selected_printer_name = Value("Canon G500 series")
        self.status_var = Value("")
        self.root = Mock()
        self.root.winfo_id.return_value = 0
        self.printer_calibration = {
            "Canon G500 series": {
                paper_profile_key((101.6, 152.4)): {"x": 1, "y": 2},
                paper_profile_key((152.4, 101.6)): {"x": 3, "y": 4},
            },
        }


class PrintOrientationTests(unittest.TestCase):
    def test_explicit_orientation_rotates_exact_pixels_without_mutating_queue(self):
        original = sheet()
        before = original["image"].tobytes()
        output = orient_print_task(original, PAPER_ORIENTATION_LANDSCAPE)
        self.assertEqual(output["paper_mm"], (152.4, 101.6))
        self.assertEqual(output["size"], (18, 12))
        self.assertEqual(output["image"].tobytes(), original["image"].transpose(Image.Transpose.ROTATE_270).tobytes())
        self.assertEqual(original["paper_mm"], (101.6, 152.4))
        self.assertEqual(original["size"], (12, 18))
        self.assertEqual(original["image"].tobytes(), before)
        self.assertEqual(orient_paper_size((152.4, 101.6), PAPER_ORIENTATION_PORTRAIT), (101.6, 152.4))
        self.assertEqual(orient_paper_size((152.4, 101.6), PAPER_ORIENTATION_AUTO), (152.4, 101.6))

    def test_calibration_chart_keeps_frozen_direction(self):
        chart = dict(sheet(), kind="calibration")
        output = orient_print_task(chart, PAPER_ORIENTATION_LANDSCAPE)
        self.assertEqual(output["paper_mm"], chart["paper_mm"])
        self.assertIs(output["image"], chart["image"])
        self.assertEqual(App().resolve_print_paper_mm([chart])[0], chart["paper_mm"])

    def test_calibration_target_can_choose_global_or_original_preview_axes(self):
        app = App()
        app.preview_task_index, app.batch_tasks = 0, [sheet()]
        self.assertEqual(app.calibration_target().paper_mm, (152.4, 101.6))
        self.assertEqual(app.calibration_target(PAPER_ORIENTATION_AUTO).paper_mm, (101.6, 152.4))

    def test_photo_and_chart_use_same_output_profile_when_driver_turns_page(self):
        for actual in ((152.4, 101.6), (101.6, 152.4)):
            with self.subTest(actual=actual):
                app = App()
                photo = sheet()
                chart = dict(orient_print_task(photo, PAPER_ORIENTATION_LANDSCAPE), kind="calibration")
                info = app.bind_output_tasks(caps(actual), [photo, chart], PAPER_ORIENTATION_LANDSCAPE,
                                             (152.4, 101.6))
                errors, _ = app.validate_printer_fit(info, [photo, chart])
                self.assertFalse(errors)
                photo_plan, chart_plan = (info["_placements"][id(task)] for task in (photo, chart))
                self.assertEqual(photo_plan, chart_plan)
                self.assertEqual(photo_plan.scale, 1)
                left, top, right, bottom = photo_plan.physical_box
                centre_shift = ((left + right - info["physical_width"]) / 2,
                                (top + bottom - info["physical_height"]) / 2)
                self.assertEqual(centre_shift, (-40, 30) if photo_plan.rotate_clockwise else (30, 40))
                with patch("PIL.ImageWin.Dib") as dib:
                    app.print_tasks_with_win32([photo, chart], info, printer_dc=Mock())
                printed_images = [call.args[0] for call in dib.call_args_list]
                expected_turn = Image.Transpose.ROTATE_180 if photo_plan.rotate_clockwise else Image.Transpose.ROTATE_270
                expected = photo["image"].transpose(expected_turn)
                self.assertTrue(all(image.size == expected.size and image.tobytes() == expected.tobytes()
                                    for image in printed_images))

    def test_legacy_portrait_profile_does_not_leak_into_selected_landscape(self):
        app = App()
        app.printer_calibration = {"Canon G500 series": {"6寸整张": {"x": 9, "y": 8}}}
        self.assertEqual(app.calibration_offsets_for("Canon G500 series", "6寸整张", (101.6, 152.4)), (9, 8))
        self.assertEqual(app.calibration_offsets_for("Canon G500 series", "6寸整张", (152.4, 101.6)), (0, 0))

    def test_draw_reuses_validated_output_after_user_changes_selection(self):
        app, original = App(), sheet()
        info = app.bind_output_tasks(caps((152.4, 101.6)), [original], PAPER_ORIENTATION_LANDSCAPE,
                                     (152.4, 101.6))
        self.assertFalse(app.validate_printer_fit(info, [original])[0])
        app.paper_orientation.set(PAPER_ORIENTATION_PORTRAIT)
        dc = Mock()
        with patch("PIL.ImageWin.Dib") as dib:
            app.print_tasks_with_win32([original], info, printer_dc=dc)
        rendered = dib.call_args.args[0]
        self.assertEqual(rendered.size, (18, 12))
        self.assertEqual(rendered.tobytes(), original["image"].transpose(Image.Transpose.ROTATE_270).tobytes())
        self.assertEqual(original["size"], (12, 18))

    def test_driver_direction_mismatch_can_cancel_before_startdoc(self):
        app, original = App(), sheet()
        info = app.bind_output_tasks(caps((101.6, 152.4)), [original], PAPER_ORIENTATION_LANDSCAPE,
                                     (152.4, 101.6))
        dc, cleanup = Mock(), Mock()
        app.open_selected_print_context = Mock(return_value=(info, dc, cleanup, [], False))
        with patch("photo_layout.printing.messagebox.askyesno", return_value=False) as prompt:
            self.assertEqual(app.prepare_print_context([original], "测试"), (None, None, None))
        self.assertIn("驱动实际返回纵向", prompt.call_args.args[1])
        self.assertIn("本次请求横向", prompt.call_args.args[1])
        dc.StartDoc.assert_not_called()
        dc.DeleteDC.assert_called_once()
        cleanup.assert_called_once()

    def test_batch_freezes_orientation_for_later_stock_groups(self):
        app = App()
        app.batch_tasks = [sheet(), dict(sheet(), paper_mm=(89, 127))]
        app.validate_batch_queue = Mock(return_value=True)
        def prepare(tasks, label, paper_orientation):
            app.paper_orientation.set(PAPER_ORIENTATION_PORTRAIT)
            return {"name": "Canon G500 series"}, Mock(), None
        app.prepare_print_context = Mock(side_effect=prepare)
        app.print_tasks_with_win32, app.close_system_print_context = Mock(), Mock()
        with patch("photo_layout.batches.messagebox.askokcancel", return_value=True), \
                patch("photo_layout.batches.messagebox.showinfo"):
            app.dispatch_queue_tasks(app.batch_tasks)
        self.assertEqual(app.prepare_print_context.call_count, 2)
        self.assertTrue(all(call.kwargs["paper_orientation"] == PAPER_ORIENTATION_LANDSCAPE
                            for call in app.prepare_print_context.call_args_list))

    def test_auto_direction_separates_portrait_and_landscape_into_driver_contexts(self):
        app = App(PAPER_ORIENTATION_AUTO)
        app.batch_tasks = [sheet(), orient_print_task(sheet(), PAPER_ORIENTATION_LANDSCAPE)]
        app.validate_batch_queue = Mock(return_value=True)
        app.prepare_print_context = Mock(return_value=({"name": "Canon G500 series"}, Mock(), None))
        app.print_tasks_with_win32, app.close_system_print_context = Mock(), Mock()
        with patch("photo_layout.batches.messagebox.askokcancel", return_value=True), \
                patch("photo_layout.batches.messagebox.showinfo"):
            app.dispatch_queue_tasks(app.batch_tasks)
        self.assertEqual(app.prepare_print_context.call_count, 2)
        self.assertEqual([len(call.args[0]) for call in app.prepare_print_context.call_args_list], [1, 1])

    def test_direct_fallback_keeps_requested_paper_and_output_direction(self):
        app, original = App(), sheet()
        app.create_target_devmode_handle = Mock(side_effect=OSError("驱动不接受设置"))
        app.get_printer_info_from_dc = Mock(return_value=caps((101.6, 152.4)))
        with patch("win32ui.CreateDC", return_value=Mock()):
            info, dc, cleanup, errors, cancelled = app.open_direct_print_context([original])
        app.create_target_devmode_handle.assert_called_once_with("Canon G500 series", (152.4, 101.6), None)
        self.assertFalse(errors)
        self.assertFalse(cancelled)
        self.assertEqual(info["target_paper_mm"], (152.4, 101.6))
        self.assertEqual(info["_output_tasks"][id(original)]["paper_mm"], (152.4, 101.6))
        self.assertTrue(app.validate_printer_fit(info, [original])[1])
        dc.StartDoc.assert_not_called()
        app.close_system_print_context(dc, cleanup)

    def test_system_dialog_initializes_requested_size_before_cancel(self):
        app, original = App(), sheet()
        app.create_print_devnames_handle = Mock(return_value=None)
        app.create_target_devmode_handle = Mock(return_value=(None, "设置完成"))
        with patch("ctypes.windll.comdlg32.PrintDlgW", return_value=0), \
                patch("ctypes.windll.comdlg32.CommDlgExtendedError", return_value=0):
            result = app.open_system_print_dialog([original])
        self.assertTrue(result[-1])
        app.create_target_devmode_handle.assert_called_once()
        queue, paper, owner = app.create_target_devmode_handle.call_args.args
        self.assertEqual((queue, paper), ("Canon G500 series", (152.4, 101.6)))
        self.assertEqual(app.create_target_devmode_handle.call_args.kwargs, {})
        # ctypes exposes a null HWND as None; integer-backed mocks may retain 0.
        self.assertIn(owner, (None, 0))


if __name__ == "__main__":
    unittest.main()
