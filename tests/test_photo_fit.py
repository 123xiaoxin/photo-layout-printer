import unittest
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw

from photo_layout.layout import LayoutMixin
from photo_layout.photos import PhotosMixin
from photo_layout.photo_fit import fit_photo, inset_size, orient_photo, read_photo
from photo_layout.collage_layout import CollageOptions, build_collage_task
from photo_layout.printer_geometry import print_placement
from photo_layout.specifications import (
    FIT_MODE_ADAPT, FIT_MODE_CROP, FIT_MODE_EQUAL_BORDER, FIT_MODE_NATIVE,
    FIT_MODE_OPTIONS, FIT_MODE_POLAROID, LAYOUT_OPTIONS,
)


class Setting:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class PrintSurface(PhotosMixin, LayoutMixin):
    def __init__(self, layout, dpi):
        self.layout_mode = Setting(layout)
        self.dpi = Setting(dpi)
        self.middle_margin_mm = Setting(3)
        self.margin_mm = Setting(2.5)
        self.enable_margin = Setting(True)
        self.fit_mode = Setting(FIT_MODE_EQUAL_BORDER)
        self.auto_rotate = Setting(True)
        self.draw_cut_line = Setting(True)
        self.show_guides = Setting(True)
        self.original_images = [Image.new("RGB", (52, 37), "black"), Image.new("RGB", (37, 52), "black")]
        self.processed_photos = [None, None]
        self.horizontal_offset = [0, 0]
        self.vertical_offset = [0, 0]
        self.rotation_angles = [0, 0]


def ink_bounds(image):
    return ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()


class PhotoFitTests(unittest.TestCase):
    def test_selects_orientation_with_the_least_crop_and_honors_manual_turn(self):
        landscape = Image.new("RGB", (800, 100), "red")
        self.assertEqual(orient_photo(landscape, (300, 200), True, 0).size, (800, 100))
        portrait = landscape.transpose(Image.Transpose.ROTATE_90)
        self.assertEqual(orient_photo(portrait, (300, 200), True, 0).size, (800, 100))
        self.assertEqual(orient_photo(portrait, (300, 200), True, 90).size, (100, 800))
        self.assertEqual(orient_photo(portrait, (300, 200), False, 0).size, (100, 800))

    def test_fit_preserves_shape_and_handles_thin_alpha_and_small_images(self):
        wide = Image.new("RGB", (200, 100), "white")
        ImageDraw.Draw(wide).rectangle((80, 30, 119, 69), fill="black")
        for mode in (FIT_MODE_ADAPT, FIT_MODE_CROP, FIT_MODE_EQUAL_BORDER, FIT_MODE_NATIVE):
            bounds = ink_bounds(fit_photo(wide, (120, 120), mode))
            self.assertLessEqual(abs((bounds[2] - bounds[0]) - (bounds[3] - bounds[1])), 1)
        thin = fit_photo(Image.new("RGB", (1, 2000), "red"), (12, 12), FIT_MODE_ADAPT)
        self.assertEqual(ink_bounds(thin), (5, 0, 6, 12))
        alpha = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        for mode in FIT_MODE_OPTIONS:
            self.assertIsNone(ink_bounds(fit_photo(alpha, (16, 8), mode)))
        tiny = Image.new("RGB", (4, 2), "red")
        self.assertEqual(ink_bounds(fit_photo(tiny, (10, 10), FIT_MODE_NATIVE)), (3, 4, 7, 6))

    def test_square_protection_and_explicit_equal_border_have_distinct_behavior(self):
        square = Image.new("RGB", (40, 40), "blue")
        self.assertEqual(ink_bounds(fit_photo(square, (80, 100), FIT_MODE_CROP)), (0, 10, 80, 90))
        self.assertEqual(ink_bounds(fit_photo(square, (80, 100), FIT_MODE_EQUAL_BORDER)), (0, 0, 80, 100))
        self.assertEqual(ink_bounds(fit_photo(square, (80, 100), FIT_MODE_POLAROID)), (0, 5, 80, 85))

    def test_exif_rotated_photo_detached_from_file(self):
        with BytesIO() as source:
            raw = Image.new("RGB", (60, 40))
            exif = Image.Exif()
            exif[274] = 6
            raw.save(source, format="JPEG", exif=exif)
            source.seek(0)
            photo = read_photo(source)
        self.assertEqual(photo.size, (40, 60))
        self.assertEqual(photo.getpixel((0, 0)), (0, 0, 0))
        self.assertNotEqual(photo.getexif().get(274), 6)

    def test_printed_cell_borders_and_gutter_cut_lines_at_both_resolutions(self):
        for layout in LAYOUT_OPTIONS:
            for dpi in (300, 600):
                with self.subTest(layout=layout, dpi=dpi):
                    app = PrintSurface(layout, dpi)
                    for index in range(2):
                        app.reprocess_photo(index)
                    sheet = app.combine_images()
                    geo = app.build_layout_geometry()
                    expected = tuple(round(mm * dpi / 25.4) for mm in geo["paper_mm"])
                    self.assertEqual(sheet.size, expected)
                    margin = round(2.5 * dpi / 25.4)
                    for slot in geo["slots"]:
                        frame = slot["frame"]
                        cell = sheet.crop(frame)
                        self.assertEqual(ink_bounds(cell),
                                         (margin, margin, cell.width - margin, cell.height - margin))
                    if geo["slot_count"] == 2:
                        a, b = (slot["frame"] for slot in geo["slots"])
                        points = [(a[2], margin), (b[0] - 1, margin)] if geo["direction"] == "horizontal" else [
                            (margin, a[3]), (margin, b[1] - 1)]
                        self.assertTrue(all(sheet.getpixel(point) == (120, 120, 120) for point in points))
                    app.show_guides.value = False
                    self.assertEqual(ImageChops.difference(sheet, app.combine_images()).getbbox(), None)

    def test_five_inch_two_photos_have_three_mm_borders_and_six_mm_middle(self):
        source = Image.new("RGB", (800, 600), "red")
        ImageDraw.Draw(source).rectangle((340, 240, 459, 359), fill="black")
        for dpi, paper_size, photo_size, border in (
            (300, (1051, 1500), (981, 680), 35),
            (600, (2102, 3000), (1960, 1358), 71),
        ):
            with self.subTest(dpi=dpi):
                app = PrintSurface("5寸+3寸", dpi)
                app.margin_mm.value = 3.0
                app.middle_margin_mm.value = 0
                app.original_images = [source, source.transpose(Image.Transpose.ROTATE_90)]
                for index in range(2):
                    app.reprocess_photo(index)
                    photo = app.processed_photos[index]
                    self.assertEqual(photo.size, photo_size)
                    # A square inside a nonsquare source remains square after
                    # orientation, uniform scaling, and centre cropping.
                    square = photo.getchannel("R").point(lambda value: 255 if value < 128 else 0)
                    l, t, r, b = square.getbbox()
                    self.assertLessEqual(abs((r-l) - (b-t)), 1)
                output = app.combine_images(for_preview=False)
                self.assertEqual(output.size, paper_size)
                slots = app.build_layout_geometry()["slots"]
                for slot in slots:
                    cell = output.crop(slot["frame"])
                    # Red photographs and their black square have a zero blue
                    # channel. Gray registration ticks lie on the cutting edge.
                    photo_mask = cell.getchannel("B").point(lambda value: 255 if value < 64 else 0)
                    self.assertEqual(photo_mask.getbbox(),
                                     (border, border, cell.width-border, cell.height-border))
                    self.assertAlmostEqual(border * 25.4 / dpi, 3.0, delta=25.4 / dpi)
                upper, lower = slots
                gap = lower["photo"][1] - upper["photo"][3]
                self.assertEqual(gap, 2 * border)
                self.assertAlmostEqual(gap * 25.4 / dpi, 6.0, delta=2 * 25.4 / dpi)
                x = output.width // 2
                self.assertTrue(all(output.getpixel((x, y)) == (255, 255, 255)
                                    for y in range(upper["photo"][3], lower["photo"][1])))
                before = output.tobytes()
                preview = app.combine_images(for_preview=True)
                self.assertEqual(preview.size, output.size)
                self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
                self.assertNotEqual(preview.getpixel((0, 0)), (255, 255, 255))
                self.assertNotEqual(preview.tobytes(), before)
                self.assertEqual(app.combine_images(for_preview=False).tobytes(), before)

    def test_reducing_margin_rebounds_old_manual_offsets(self):
        app = PrintSurface("6寸+4寸", 300)
        app.horizontal_offset[0] = 25
        app.vertical_offset[0] = -25
        app.enable_margin.value = False
        app.reprocess_photo(0)
        self.assertEqual((app.horizontal_offset[0], app.vertical_offset[0]), (0, 0))
        self.assertEqual(app.processed_photos[0].size, app.get_layout_base()["photo_px"])
        self.assertEqual(inset_size((10, 20), 20, 300), (2, 12))

    def test_guides_and_cut_marks_can_be_disabled_independently(self):
        app = PrintSurface("6寸+4寸", 300)
        for index in range(2):
            app.reprocess_photo(index)
        app.draw_cut_line.value = False
        output = app.combine_images()
        self.assertIsNotNone(ImageChops.difference(output, app.combine_images(for_preview=True)).getbbox())
        app.show_guides.value = False
        self.assertIsNone(ImageChops.difference(output, app.combine_images(for_preview=True)).getbbox())

    def test_g580_six_mm_border_preserves_full_size_with_cut_marks(self):
        # G580 4x6 bordered-print fixture. Both photo rasters and guide ticks
        # must survive the real placement path without a reduction in size.
        dpi = 600
        w, h = 2400, 3600
        left, top, right, bottom = (round(mm * dpi / 25.4) for mm in (3.4, 3, 3.4, 5))
        caps = dict(physical_width=w, physical_height=h, offset_x=left, offset_y=top,
                    horzres=w-left-right, vertres=h-top-bottom, logpixels_x=dpi, logpixels_y=dpi)
        raw = BytesIO()
        Image.new("RGB", (64, 40), "black").save(raw, format="PNG")
        options = CollageOptions(border_mm=6, fit_mode=FIT_MODE_EQUAL_BORDER, cut_marks=True)
        collage = build_collage_task([BytesIO(raw.getvalue()) for _ in range(4)],
                                    options, (101.6, 152.4), dpi)
        inset = round(6 * dpi / 25.4)
        self.assertEqual(collage["image"].getpixel((w//2, inset)), (140, 140, 140))
        self.assertEqual(collage["image"].getpixel((inset, h//2)), (140, 140, 140))
        app = PrintSurface("6寸+4寸", dpi)
        app.margin_mm.value = 6
        for i in range(2):
            app.reprocess_photo(i)
        template = {"image": app.combine_images(), "paper_mm": (101.6, 152.4)}
        for task in (collage, template):
            l, t, r, b = ink_bounds(task["image"])
            # Splitting an odd gutter can leave one rounding pixel outside a slot.
            for margin in (l, t, w-r, h-b):
                self.assertIn(margin, (inset, inset+1))
            plan = print_placement(task, caps)
            self.assertEqual(plan.scale, 1.0)
            self.assertEqual(plan.physical_box, (0, 0, w, h))


if __name__ == "__main__":
    unittest.main()
