"""Driver settings validation and saved-job routing; no jobs are submitted."""
import ctypes
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from photo_layout.configuration import CalibrationTarget
from photo_layout import driver_settings as ds
from photo_layout.printing import PrintingMixin


def blob(scale=104, private=b"opaque-borderless-extension", orientation=1):
    data = bytearray(220 + len(private))
    struct.pack_into("<HHHHI", data, 64, 1025, 1539, 220, len(private), 1 | 4 | 8 | 16)
    struct.pack_into("<hhhhh", data, 76, orientation, 0, 1270, 890, scale)
    data[220:] = private
    return bytes(data)


class DriverSettingsTests(unittest.TestCase):
    def test_binary_bounds_reject_truncated_extra_and_trailing_bytes(self):
        good = blob()
        for bad in (b"", good[:-1], good + b"x", good[:68] + b"\x10\0" + good[70:]):
            with self.subTest(length=len(bad)), self.assertRaises(ds.DriverSettingsError):
                ds.parse_devmode(bad)
        self.assertEqual(ds.parse_devmode(good).dmDriverExtra, len(good) - 220)

    def test_private_data_and_valid_public_scale_are_distinct(self):
        self.assertEqual(ds.public_settings(blob())["driver_scale_percent"], 104)
        data = bytearray(blob())
        struct.pack_into("<I", data, 72, 1 | 4 | 8)
        self.assertIsNone(ds.public_settings(bytes(data))["driver_scale_percent"])

    def test_changed_driver_identity_rejected_even_same_queue_and_size(self):
        with self.assertRaisesRegex(ds.DriverSettingsError, "驱动已变化"):
            ds.validate_profile({"driver_identity": {"name": "old"}, "devmode_bytes": blob()}, {"name": "new"})

    def test_saved_job_keeps_private_bytes_and_intentional_scale(self):
        data, identity = blob(), {"name": "Canon G500 series", "sha": "same"}
        app = SimpleNamespace(get_driver_page_profile=Mock(return_value={
            "devmode_bytes": data, "driver_identity": identity}))
        session = Mock(default=blob(scale=100))
        session.merge.return_value = data
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)
        with patch.object(ds, "DriverSession", return_value=context), \
             patch.object(ds, "driver_identity", return_value=identity), \
             patch.object(ds, "validate_target_dc") as validate, \
             patch.object(ds, "apply_media_request") as adapt:
            result, note = ds.target_devmode(app, "店内照片机", (89, 127))
        self.assertEqual(result, data)
        session.merge.assert_called_once_with(data)
        validate.assert_called_once_with("店内照片机", data, (89, 127))
        adapt.assert_not_called()
        self.assertEqual(ds.public_settings(result)["driver_scale_percent"], 104)
        self.assertIn("软件保存", note)

    def test_native_cancel_never_saves_or_validates_output(self):
        app = SimpleNamespace(save_driver_page_profile=Mock())
        target = CalibrationTarget("queue", "layout", (89, 127), 300)
        session = Mock()
        session.merge.return_value = None
        with patch.object(ds, "driver_identity", return_value={"name": "driver"}), \
             patch.object(ds, "target_devmode", return_value=(blob(), "note")), \
             patch.object(ds, "DriverSession") as factory, \
             patch.object(ds, "validate_target_dc") as validate:
            factory.return_value.__enter__.return_value = session
            self.assertFalse(ds.edit_page_settings(app, target))
        app.save_driver_page_profile.assert_not_called()
        validate.assert_not_called()

    def test_native_confirmation_wrong_media_or_direction_never_saves(self):
        app = SimpleNamespace(save_driver_page_profile=Mock())
        target = CalibrationTarget("queue", "layout", (89, 127), 300)
        with patch.object(ds, "driver_identity", return_value={"name": "driver"}), \
             patch.object(ds, "target_devmode", return_value=(blob(), "note")), \
             patch.object(ds, "DriverSession") as factory, \
             patch.object(ds, "validate_target_dc", side_effect=ds.DriverSettingsError("方向不符")):
            factory.return_value.__enter__.return_value.merge.return_value = blob(orientation=2)
            with self.assertRaisesRegex(ds.DriverSettingsError, "方向不符"):
                ds.edit_page_settings(app, target)
        app.save_driver_page_profile.assert_not_called()

    def test_native_confirmation_passes_full_bytes_and_owner_handle(self):
        app, owner = SimpleNamespace(save_driver_page_profile=Mock()), Mock()
        owner.winfo_id.return_value = 123
        target, data = CalibrationTarget("real queue", "layout", (89, 127), 300), blob()
        with patch.object(ds, "driver_identity", return_value={"name": "driver"}), \
             patch.object(ds, "target_devmode", return_value=(blob(scale=100), "note")), \
             patch.object(ds, "DriverSession") as factory, patch.object(ds, "validate_target_dc"):
            factory.return_value.__enter__.return_value.merge.return_value = data
            self.assertTrue(ds.edit_page_settings(app, target, owner))
            factory.assert_called_once_with("real queue", 123)
        app.save_driver_page_profile.assert_called_once_with("real queue", (89, 127), data, {"name": "driver"})

    def test_native_confirmation_save_failure_propagates(self):
        app = SimpleNamespace(save_driver_page_profile=Mock(side_effect=OSError("disk full")))
        target = CalibrationTarget("queue", "layout", (89, 127), 300)
        with patch.object(ds, "driver_identity", return_value={"name": "driver"}), \
             patch.object(ds, "target_devmode", return_value=(blob(), "note")), \
             patch.object(ds, "DriverSession") as factory, patch.object(ds, "validate_target_dc"):
            factory.return_value.__enter__.return_value.merge.return_value = blob()
            with self.assertRaisesRegex(OSError, "disk full"):
                ds.edit_page_settings(app, target)

    def test_document_properties_prompt_flags_never_update_global_defaults(self):
        session = object.__new__(ds.DriverSession)
        session.default, session.capacity = blob(), len(blob())
        def native(output, source, flags):
            self.assertEqual(flags, 4 | 8 | 2)
            self.assertEqual(ctypes.string_at(source, len(blob())), blob())
            ctypes.memmove(output, blob(), len(blob()))
            return 1
        session._call = native
        self.assertEqual(session.merge(blob(), prompt=True), blob())

    def test_saved_failure_never_falls_back_to_default_dc(self):
        app = PrintingMixin()
        app.selected_printer_name = Mock()
        app.selected_printer_name.get.return_value = "real queue"
        app.resolve_print_paper_mm = Mock(return_value=((89, 127), []))
        app.create_target_devmode_handle = Mock(side_effect=OSError("driver rejected"))
        app.get_driver_page_profile = Mock(return_value={"devmode_bytes": blob()})
        with patch("win32ui.CreateDC") as fallback:
            info, dc, cleanup, errors, cancelled = app.open_direct_print_context([])
        self.assertIsNone(info)
        self.assertTrue(errors)
        fallback.assert_not_called()

    def test_system_dialog_reads_final_temporary_scale_without_saving_profile(self):
        app = PrintingMixin()
        app.selected_printer_name = Mock()
        app.selected_printer_name.get.return_value = "real queue"
        app.root, app.status_var = Mock(), Mock()
        app.root.winfo_id.return_value = 0
        app.resolve_print_paper_mm = Mock(return_value=((89, 127), []))
        initial, final = blob(scale=100, private=b"initial"), blob(scale=104, private=b"changed")
        handle = ds.devmode_handle(initial)
        app.create_target_devmode_handle = Mock(return_value=(handle, "采用软件保存的设置"))
        app.create_print_devnames_handle = Mock(return_value=None)
        app.get_printer_name_from_devnames = Mock(return_value="real queue")
        app.get_printer_info_from_dc = Mock(return_value={"name": "real queue"})
        app.save_driver_page_profile, app.save_config = Mock(), Mock()
        def dialog(pointer):
            pd = pointer._obj
            kernel = ds._global_memory()
            ptr = kernel.GlobalLock(pd.hDevMode)
            ctypes.memmove(ptr, final, len(final))
            kernel.GlobalUnlock(pd.hDevMode)
            pd.hDC = 99
            return 1
        with patch("ctypes.windll.comdlg32.PrintDlgW", side_effect=dialog), \
             patch("win32ui.CreateDCFromHandle", return_value=Mock()), \
             patch("photo_layout.printing.confirmed_public_settings", side_effect=lambda queue, data: ds.public_settings(data)) as confirmed:
            info, dc, cleanup, errors, cancelled = app.open_system_print_dialog([])
        self.assertFalse(errors)
        self.assertEqual(info["driver_scale_percent"], 104)
        confirmed.assert_called_once_with("real queue", final)
        app.save_driver_page_profile.assert_not_called()
        app.save_config.assert_not_called()
        dc.StartDoc.assert_not_called()
        cleanup()

    def test_system_dialog_saved_error_does_not_open_with_default_settings(self):
        app = PrintingMixin()
        app.selected_printer_name = Mock()
        app.selected_printer_name.get.return_value = "real queue"
        app.root = Mock()
        app.root.winfo_id.return_value = 0
        app.resolve_print_paper_mm = Mock(return_value=((89, 127), []))
        app.create_print_devnames_handle = Mock(return_value=None)
        app.create_target_devmode_handle = Mock(side_effect=OSError("driver unavailable"))
        app.get_driver_page_profile = Mock(return_value={"devmode_bytes": blob()})
        with patch("ctypes.windll.comdlg32.PrintDlgW") as dialog:
            info, dc, cleanup, errors, cancelled = app.open_system_print_dialog([])
        self.assertIsNone(info)
        self.assertTrue(errors)
        dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
