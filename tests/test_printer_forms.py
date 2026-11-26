"""Driver capability negotiation without starting a print job."""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from photo_layout.printer_forms import (
    DC_FIELDS, DM_FORMNAME, DM_SCALE, DriverPaper, apply_media_request,
    driver_substituted_size, match_paper, media_requests, read_supported_media,
)
from photo_layout.specifications import (
    DC_PAPERS, DC_PAPERNAMES, DC_PAPERSIZE, DM_ORIENTATION, DM_PAPERSIZE,
    DM_PAPERWIDTH, DM_PAPERLENGTH, DMORIENT_LANDSCAPE, DMORIENT_PORTRAIT,
)


class PrinterFormsTests(unittest.TestCase):
    stock = (152.4, 101.6)
    native = DriverPaper(312, "6x4 Wide", stock)

    def mode(self):
        return SimpleNamespace(dmFields=DM_SCALE | DM_FORMNAME | DM_PAPERSIZE | DM_PAPERWIDTH | DM_PAPERLENGTH,
                               dmPaperWidth=2100, dmPaperLength=2970, dmPaperSize=9, dmFormName="A4",
                               dmOrientation=2, dmScale=80)

    def test_native_wide_stock_uses_unrotated_driver_orientation(self):
        for target, expected in [(self.stock, DMORIENT_PORTRAIT), (self.stock[::-1], DMORIENT_LANDSCAPE)]:
            mode = self.mode()
            match = match_paper([self.native], target)
            apply_media_request(mode, target, match, None, "code")
            self.assertEqual((mode.dmPaperSize, mode.dmOrientation), (312, expected))
            self.assertEqual((mode.dmPaperWidth, mode.dmPaperLength, mode.dmFormName, mode.dmScale), (0, 0, "", 100))
            self.assertFalse(mode.dmFields & (DM_FORMNAME | DM_PAPERWIDTH | DM_PAPERLENGTH))

    def test_driver_advertises_name_only_or_non_configurable_feed(self):
        mode = self.mode()
        match = match_paper([self.native], self.stock)
        self.assertEqual(list(media_requests(match, DM_FORMNAME)), ["form"])
        apply_media_request(mode, self.stock, match, DM_FORMNAME, "form")
        self.assertEqual(mode.dmFormName, "6x4 Wide")
        self.assertEqual(mode.dmPaperSize, 0)
        self.assertFalse(mode.dmFields & DM_ORIENTATION)
        self.assertEqual(list(media_requests(None, 0)), [])

    def test_custom_dimensions_use_zero_code_and_preserve_other_fields(self):
        mode = self.mode()
        mode.dmFields |= 0x02000000
        flags = DM_PAPERWIDTH | DM_PAPERLENGTH | DM_ORIENTATION
        self.assertEqual(list(media_requests(None, flags)), ["dimensions"])
        apply_media_request(mode, self.stock, None, flags, "dimensions")
        self.assertEqual((mode.dmPaperWidth, mode.dmPaperLength, mode.dmPaperSize), (1016, 1524, 0))
        self.assertEqual(mode.dmFormName, "")
        self.assertFalse(mode.dmFields & (DM_FORMNAME | DM_PAPERSIZE))
        self.assertTrue(mode.dmFields & 0x02000000)
        self.assertEqual(mode.dmOrientation, DMORIENT_LANDSCAPE)

    def test_driver_can_substitute_media_despite_success(self):
        mode = self.mode()
        self.assertTrue(driver_substituted_size(mode, [], self.stock, True))
        mode.dmFields = DM_PAPERSIZE
        mode.dmPaperSize = 9
        catalog = [self.native, DriverPaper(9, "A4", (210, 297))]
        self.assertTrue(driver_substituted_size(mode, catalog, self.stock, True))
        mode.dmPaperSize = 312
        self.assertFalse(driver_substituted_size(mode, catalog, self.stock[::-1], True))
        mode.dmFields = DM_FORMNAME
        mode.dmFormName = self.native.name
        self.assertFalse(driver_substituted_size(mode, catalog, self.stock, True))

    def test_lookup_respects_queue_ports_and_optional_names(self):
        import win32print as spool
        def query(name, port, cap, mode):
            self.assertEqual((name, mode), ("Shared photo queue", "settings"))
            if port == "offline":
                return -1
            self.assertEqual(port, "USB002")
            return {DC_FIELDS: DM_PAPERSIZE, DC_PAPERS: (312,), DC_PAPERNAMES: -1,
                    DC_PAPERSIZE: ({"x": 1524, "y": 1016},)}[cap]
        with patch.object(spool, "OpenPrinter", return_value=123), patch.object(spool, "ClosePrinter") as close, \
             patch.object(spool, "GetPrinter", return_value={"pPortName":"offline,USB002", "pDevMode":"settings"}), \
             patch.object(spool, "DeviceCapabilities", side_effect=query):
            forms, fields = read_supported_media("Shared photo queue")
        close.assert_called_once_with(123)
        self.assertEqual((forms, fields), ([DriverPaper(312, "", self.stock)], DM_PAPERSIZE))

    def test_enumforms_fallback_uses_only_device_advertised_form_names(self):
        import win32print as spool
        responses = {DC_FIELDS: DM_FORMNAME, DC_PAPERS: (), DC_PAPERSIZE: (), DC_PAPERNAMES: ("Label stock",)}
        forms = [{"Name": name, "Size": {"cx": 100000, "cy": 150000}} for name in ("System only", "Label stock")]
        with patch.object(spool, "OpenPrinter", return_value=123), patch.object(spool, "ClosePrinter"), \
             patch.object(spool, "GetPrinter", return_value={"pPortName":"WSD-123"}), \
             patch.object(spool, "DeviceCapabilities", side_effect=lambda n,p,c,m: responses[c]), \
             patch.object(spool, "EnumForms", return_value=forms):
            catalog, fields = read_supported_media("Network queue")
        self.assertEqual((catalog, fields), ([DriverPaper(0, "Label stock", (100,150))], DM_FORMNAME))

    def test_real_windows_virtual_driver_dc_for_three_requested_pages(self):
        import win32print
        import win32ui
        from photo_layout.printing import PrintingMixin
        name = "Microsoft Print to PDF"
        queues = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 4)
        if name not in {q["pPrinterName"] for q in queues}:
            self.skipTest("需安装 Windows PDF 虚拟打印机")
        handle = win32print.OpenPrinter(name)
        try:
            port = win32print.GetPrinter(handle, 2)["pPortName"]
            physical_sizes = {tuple(sorted((s["x"], s["y"])))
                              for s in win32print.DeviceCapabilities(name, port, DC_PAPERSIZE)}
        finally:
            win32print.ClosePrinter(handle)
        app = PrintingMixin()
        gdi = ctypes.windll.gdi32
        kernel = ctypes.windll.kernel32
        gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        gdi.CreateDCW.restype = wintypes.HDC
        for target in [(210, 297), (297, 210), (101.6, 152.4)]:
            with self.subTest(target=target):
                if tuple(sorted(round(mm * 10) for mm in target)) not in physical_sizes:
                    self.skipTest("此驱动版本未通告该纸型")
                self.assertIsNotNone(app.find_supported_printer_paper(name, target))
                handle, _ = app.create_target_devmode_handle(name, target)
                ptr = kernel.GlobalLock(handle)
                try:
                    dc = win32ui.CreateDCFromHandle(gdi.CreateDCW("WINSPOOL", name, None, ptr))
                    try:
                        for mm, extent, resolution in zip(target, (110,111), (88,90)):
                            self.assertAlmostEqual(dc.GetDeviceCaps(extent)*25.4/dc.GetDeviceCaps(resolution),
                                                   mm, delta=0.1)
                    finally:
                        dc.DeleteDC()
                finally:
                    kernel.GlobalUnlock(handle)
                    kernel.GlobalFree(handle)


if __name__ == "__main__":
    unittest.main()
