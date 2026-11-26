"""Persistence of complete per-machine, per-queue, per-paper driver settings."""
import base64
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from photo_layout import configuration
from photo_layout.configuration import ConfigurationMixin, MAX_DRIVER_DEVMODE_BYTES, paper_profile_key
from photo_layout.specifications import FIT_MODE_CROP, PRINT_METHOD_DIRECT


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Config(ConfigurationMixin):
    def __init__(self):
        for key, value in dict(layout_mode="5寸+3寸", enable_margin=True, margin_mm=3.5,
                               fit_mode=FIT_MODE_CROP, middle_margin_mm=0, show_guides=True,
                               draw_cut_line=True, auto_rotate=True, dpi=300,
                               print_method=PRINT_METHOD_DIRECT, paper_orientation="自动",
                               selected_printer_name="Canon G580", follow_system_printer=True,
                               print_offset_x_mm=0, print_offset_y_mm=0).items():
            setattr(self, key, Value(value))
        self.rotation_angles = [0, 0]
        self.horizontal_offset = [0, 0]
        self.vertical_offset = [0, 0]
        self.printer_calibration = {}
        self.load_config()


class DriverProfileTests(unittest.TestCase):
    queue = "Canon G580"
    paper = (127, 88.9)
    identity = {"driver_name": "Canon G580 series", "driver_version": 1234,
                "files": {"config": "C:\\驱动目录\\page.dll", "sha256": "a" * 64}}
    # Opaque bytes deliberately include zero and non-UTF8 values. Only the
    # native layer interprets their public/private DEVMODE contents.
    devmode = bytes(range(256)) * 4

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name) / "中文设置"
        folder.mkdir()
        self.path = folder / "打印配置.json"
        self.config_path = patch.object(configuration, "CONFIG_FILE", str(self.path))
        self.config_path.start()
        self.addCleanup(self.config_path.stop)
        self.host = patch.object(configuration.platform, "node", return_value="Shop-A")
        self.host_mock = self.host.start()
        self.addCleanup(self.host.stop)
        self.app = Config()

    def save(self, queue=None, paper=None, data=None, identity=None):
        return self.app.save_driver_page_profile(queue or self.queue, paper or self.paper,
                                                self.devmode if data is None else data,
                                                self.identity if identity is None else identity)

    def read_json(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_complete_binary_round_trip_and_defensive_identity_copies(self):
        identity = copy.deepcopy(self.identity)
        self.assertTrue(self.save(identity=identity))
        identity["files"]["sha256"] = "caller modified"
        data = self.read_json()
        record = data["driver_page_profiles"]["shop-a"]["canon g580"][paper_profile_key(self.paper)]
        self.assertEqual(base64.b64decode(record["devmode_base64"], validate=True), self.devmode)
        self.assertIsNotNone(datetime.fromisoformat(record["saved_at"]).tzinfo)
        restored = Config().get_driver_page_profile(" CANON g580 ", self.paper)
        self.assertEqual(restored["devmode_bytes"], self.devmode)
        self.assertEqual(restored["driver_identity"], self.identity)
        restored["driver_identity"]["files"]["sha256"] = "reader modified"
        self.assertEqual(self.app.get_driver_page_profile(self.queue, self.paper)["driver_identity"], self.identity)

    def test_host_queue_stock_and_direction_are_independent_of_aliases(self):
        self.app.printer_aliases = {"canon g580": "前台照片机"}
        self.app.printer_calibration = {self.queue: {paper_profile_key(self.paper): {"x": 1.1, "y": -0.2}}}
        self.save()
        self.assertIsNone(self.app.get_driver_page_profile("前台照片机", self.paper))
        self.assertIsNone(self.app.get_driver_page_profile("Canon G680", self.paper))
        self.assertIsNone(self.app.get_driver_page_profile(self.queue, self.paper[::-1]))
        self.assertIsNone(self.app.get_driver_page_profile(self.queue, (152.4, 101.6)))
        self.save(paper=self.paper[::-1], data=b"portrait")
        self.save(queue="Canon G680", data=b"other queue")
        self.host_mock.return_value = "Shop-B"
        self.assertIsNone(Config().get_driver_page_profile(self.queue, self.paper))
        self.save(data=b"same queue on another computer")
        self.host_mock.return_value = "SHOP-A"
        restored = Config()
        self.assertEqual(restored.get_driver_page_profile(self.queue, self.paper)["devmode_bytes"], self.devmode)
        self.assertEqual(restored.get_driver_page_profile(self.queue, self.paper[::-1])["devmode_bytes"], b"portrait")
        self.assertEqual(restored.printer_aliases["canon g580"], "前台照片机")
        self.assertEqual(restored.printer_calibration, self.app.printer_calibration)
        self.host_mock.return_value = "Shop-B"
        self.assertEqual(Config().get_driver_page_profile(self.queue, self.paper)["devmode_bytes"],
                         b"same queue on another computer")

    def test_save_and_reset_failures_roll_back_memory_and_atomic_file(self):
        self.save()
        saved = self.path.read_bytes()
        previous = self.app.driver_page_profiles
        with patch.object(configuration.os, "replace", side_effect=OSError("磁盘写入失败")):
            for action in (lambda: self.save(data=b"changed"),
                           lambda: self.save(paper=self.paper[::-1]),
                           lambda: self.app.reset_driver_page_profile(self.queue, self.paper)):
                with self.assertRaisesRegex(OSError, "磁盘写入失败"):
                    action()
                self.assertIs(self.app.driver_page_profiles, previous)
                self.assertEqual(self.path.read_bytes(), saved)
                self.assertEqual(list(self.path.parent.glob(".photo-layout-*.tmp")), [])
        self.assertEqual(self.app.get_driver_page_profile(self.queue, self.paper)["devmode_bytes"], self.devmode)

    def test_reset_removes_only_exact_profile_and_missing_reset_does_not_write(self):
        self.save()
        self.save(paper=self.paper[::-1], data=b"portrait")
        self.save(queue="Canon G680", data=b"other")
        self.assertTrue(self.app.reset_driver_page_profile(self.queue, self.paper))
        restored = Config()
        self.assertIsNone(restored.get_driver_page_profile(self.queue, self.paper))
        self.assertEqual(restored.get_driver_page_profile(self.queue, self.paper[::-1])["devmode_bytes"], b"portrait")
        self.assertEqual(restored.get_driver_page_profile("Canon G680", self.paper)["devmode_bytes"], b"other")
        before = self.path.read_bytes()
        with patch.object(configuration, "write_config_file") as write:
            self.assertFalse(restored.reset_driver_page_profile(self.queue, self.paper))
            write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_payloads_fail_explicitly_and_can_be_reset_without_losing_other_scopes(self):
        self.save()
        self.save(paper=self.paper[::-1], data=b"valid other direction")
        clean = self.read_json()
        key = paper_profile_key(self.paper)
        good = clean["driver_page_profiles"]["shop-a"]["canon g580"][key]
        variants = [None, [], {**good, "version": True}, {**good, "version": 99},
                    {**good, "devmode_base64": "not base64!"},
                    {**good, "devmode_base64": "YQ==\n"},
                    {**good, "devmode_base64": ""},
                    {**good, "driver_identity": {"version": float("nan")}},
                    {**good, "driver_identity": {"values": [1, 2]}},
                    {**good, "saved_at": "2026-11-25T10:00:00"}]
        for bad in variants:
            with self.subTest(bad=bad):
                config = copy.deepcopy(clean)
                config["driver_page_profiles"]["shop-a"]["canon g580"][key] = bad
                self.path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                restored = Config()
                self.assertTrue(restored.driver_page_profile_errors)
                with self.assertRaises(ValueError):
                    restored.get_driver_page_profile(self.queue, self.paper)
                self.assertEqual(restored.get_driver_page_profile(self.queue, self.paper[::-1])["devmode_bytes"],
                                 b"valid other direction")
                restored.save_config()
                # Ordinary preference saves do not silently delete a broken profile.
                self.assertIn(key, self.read_json()["driver_page_profiles"]["shop-a"]["canon g580"])
                self.assertTrue(restored.reset_driver_page_profile(self.queue, self.paper))
                self.assertIsNone(restored.get_driver_page_profile(self.queue, self.paper))
                self.assertFalse(restored.driver_page_profile_errors)

    def test_malformed_scope_structure_is_reported_and_never_treated_as_no_profile(self):
        for broken in (None, [], {"shop-a": []}, {"shop-a": {"canon g580": []}},
                       {"shop-a": {"canon g580": {"paper:0x889": {}}}}, {"SHOP-A": {}}):
            with self.subTest(broken=broken):
                self.path.write_text(json.dumps({"driver_page_profiles": broken}), encoding="utf-8")
                app = Config()
                self.assertTrue(app.driver_page_profile_errors)
                with self.assertRaises(ValueError):
                    app.get_driver_page_profile(self.queue, self.paper)

    def test_invalid_save_is_rejected_before_persistence_and_identity_is_not_semantically_rewritten(self):
        with patch.object(configuration, "write_config_file") as write:
            for payload in (b"", "text", bytearray(b"mutable"), b"x" * (MAX_DRIVER_DEVMODE_BYTES + 1)):
                with self.subTest(payload_type=type(payload), length=len(payload)), self.assertRaises(ValueError):
                    self.save(data=payload)
            for paper in ((0, 88.9), (-1, 88.9), (float("nan"), 88.9), (True, 88.9)):
                with self.subTest(paper=paper), self.assertRaises(ValueError):
                    self.save(paper=paper)
            for identity in ({}, {"value": object()}, {"value": None}, {"value": float("inf")}):
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    self.save(identity=identity)
            write.assert_not_called()
        identity = {"driver_name": "unrecognized vendor", "signature": {"version": 42}}
        self.save(identity=identity)
        self.assertEqual(self.app.get_driver_page_profile(self.queue, self.paper)["driver_identity"], identity)


if __name__ == "__main__":
    unittest.main()
