import unittest

from PIL import Image

from photo_layout.printer_geometry import print_placement


class OffsetFormTests(unittest.TestCase):
    """Exercise partial-width forms through the same placement code used by GDI."""

    def setUp(self):
        self.sheet = Image.new("RGB", (1000, 1500), "white")
        self.task = {"image": self.sheet, "paper_mm": (100, 150)}
        # The 100 mm page has a reported printable band from x=65 to x=95 mm.
        self.caps = dict(logpixels_x=254, logpixels_y=254, physical_width=1000,
                         physical_height=1500, offset_x=650, offset_y=0,
                         horzres=300, vertres=1500)

    def test_ink_entirely_inside_offset_form_can_print_without_reposition(self):
        self.sheet.paste("black", (650, 100, 950, 400))
        plan = print_placement(self.task, self.caps)
        self.assertEqual(plan.scale, 1.0)
        self.assertEqual(plan.physical_box, (0, 0, 1000, 1500))
        self.assertEqual(plan.device_box, (-650, 0, 350, 1500))

    def test_inaccessible_ink_stays_an_error_without_a_silent_recentering(self):
        self.sheet.paste("black", (649, 100, 750, 400))
        with self.assertRaisesRegex(ValueError, "裁掉"):
            print_placement(self.task, self.caps)

    def test_orthogonal_shrink_cannot_clip_previously_reachable_ink(self):
        self.sheet.paste("black", (660, 0, 850, 1500))
        self.caps.update(offset_y=250, vertres=1000)
        with self.assertRaisesRegex(ValueError, "裁掉"):
            print_placement(self.task, self.caps)

    def test_nonintersecting_device_caps_rejected_even_on_blank_page(self):
        self.caps.update(offset_x=1001)
        with self.assertRaisesRegex(ValueError, "没有交集"):
            print_placement(self.task, self.caps)

    def test_transposed_page_and_unequal_driver_dpis_keep_ink_in_the_band(self):
        self.task["paper_mm"] = (150, 100)
        landscape = Image.new("RGB", (1500, 1000), "white")
        landscape.paste("black", (300, 50, 400, 350))
        self.task["image"] = landscape
        self.caps.update(logpixels_x=508, physical_width=2000, offset_x=1300, horzres=600)
        plan = print_placement(self.task, self.caps)
        self.assertTrue(plan.rotate_clockwise)
        self.assertEqual(plan.scale, 1.0)
        self.assertEqual(plan.device_box, (-1300, 0, 700, 1500))


if __name__ == "__main__":
    unittest.main()
