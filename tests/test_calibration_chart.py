import unittest
from unittest.mock import patch

from PIL import ImageDraw

from photo_layout.calibration_chart import BLUE, GRAY, RED, render_calibration_chart
from photo_layout.configuration import CalibrationTarget


PAPERS = ((89, 127), (101.6, 152.4), (127, 177.8), (152.4, 203.2), (210, 297))


class CalibrationChartTests(unittest.TestCase):
    def test_all_papers_orientations_and_dpis_keep_a_clear_physical_centre(self):
        for base in PAPERS:
            for paper in (base, base[::-1]):
                for dpi in (300, 600):
                    with self.subTest(paper=paper, dpi=dpi):
                        image = render_calibration_chart(CalibrationTarget("test", "校准", paper, dpi))
                        px = lambda mm: round(mm * dpi / 25.4)
                        self.assertEqual(image.mode, "RGB")
                        self.assertEqual(image.size, tuple(px(mm) for mm in paper))
                        cx, cy = paper[0] / 2, paper[1] / 2
                        for dx, dy in ((0, 0), (3, 0), (-3, 0), (0, 3), (0, -3)):
                            self.assertEqual(image.getpixel((px(cx + dx), px(cy + dy))), RED)
                        self.assertEqual(image.getpixel((px(10), px(10))), GRAY)
                        # Long axes reach every paper edge; labels and reference objects
                        # stay inside the page independently of hardware-margin clipping.
                        for point in ((0, px(cy)), (image.width - 1, px(cy)),
                                      (px(cx), 0), (px(cx), image.height - 1)):
                            self.assertEqual(image.getpixel(point), BLUE)
                        for dx, dy in ((11, 0), (-11, 0), (0, 11), (0, -11)):
                            self.assertEqual(image.getpixel((px(cx + dx), px(cy + dy))), RED)
                        image.close()

    def test_one_five_and_ten_mm_tick_lengths_and_independent_scale_references(self):
        dpi, paper = 300, (101.6, 152.4)
        image = render_calibration_chart(CalibrationTarget("test", "6寸", paper, dpi))
        px = lambda mm: round(mm * dpi / 25.4)
        cx, cy = paper[0] / 2, paper[1] / 2
        for offset, length in ((6, 0.8), (5, 1.7), (10, 2.4)):
            for sign in (-1, 1):
                x, y = cx + sign * offset, cy
                self.assertNotEqual(image.getpixel((px(x), px(y + length))), (255, 255, 255))
                self.assertEqual(image.getpixel((px(x), px(y + length + 0.4))), (255, 255, 255))
                x, y = cx, cy + sign * offset
                self.assertNotEqual(image.getpixel((px(x - length), px(y))), (255, 255, 255))
                self.assertEqual(image.getpixel((px(x - length - 0.4), px(y))), (255, 255, 255))
        ruler_y = px(paper[1] - 20)
        self.assertEqual(image.getpixel((px(12), ruler_y)), BLUE)
        self.assertEqual(image.getpixel((px(32), ruler_y)), BLUE)
        self.assertAlmostEqual((px(32) - px(12)) * 25.4 / dpi, 20, delta=25.4 / dpi)
        x, y = cx + 11, paper[1] - 24
        for dx, dy in ((0, 0), (10, 0), (0, 10), (10, 10)):
            self.assertEqual(image.getpixel((px(x + dx), px(y + dy))), BLUE)

    def test_small_paper_labels_do_not_overlap_other_labels_or_centre(self):
        original = ImageDraw.ImageDraw.text
        for paper in (PAPERS[0], PAPERS[0][::-1]):
            calls = []

            def record(draw, position, text, *args, **kwargs):
                calls.append((text, draw.textbbox(position, text, font=kwargs["font"],
                                                 anchor=kwargs["anchor"])))
                return original(draw, position, text, *args, **kwargs)

            target = CalibrationTarget("test", "5寸", paper, 300)
            with patch.object(ImageDraw.ImageDraw, "text", record):
                image = render_calibration_chart(target, (10, -10))
            labels = [value for value, _ in calls]
            self.assertIn("横向 · 长边在上" if paper[0] > paper[1] else "纵向 · 短边在上", labels)
            self.assertIn("X +10.00", labels)
            self.assertIn("Y -10.00", labels)
            self.assertIn("图示上边", labels)
            cx, cy = (round(mm * 300 / 25.4 / 2) for mm in paper)
            for index, (value, (l, t, r, b)) in enumerate(calls):
                self.assertFalse(l <= cx < r and t <= cy < b, value)
                self.assertGreaterEqual(l, 0)
                self.assertGreaterEqual(t, 0)
                self.assertLessEqual(r, image.width)
                self.assertLessEqual(b, image.height)
                for other, (l2, t2, r2, b2) in calls[index+1:]:
                    self.assertFalse(l < r2 and r > l2 and t < b2 and b > t2, (value, other))


if __name__ == "__main__":
    unittest.main()
