import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from photo_layout.collage import CollageEditor
from photo_layout.collage_layout import (
    GRIDS, PAPERS, CollageOptions, build_collage_task, choose_paper, grid_boxes, validate_collage,
)
from photo_layout.layout import LayoutMixin
from photo_layout.specifications import FIT_MODE_EQUAL_BORDER, FIT_MODE_NATIVE


class CollageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = []
        for i in range(9):
            path = Path(temp.name) / f"{i}.png"
            Image.new("RGB", (80, 60), self.color(i)).save(path)
            self.paths.append(str(path))

    @staticmethod
    def color(i):
        return 20 * i, 20, 255 - 20 * i

    def test_five_papers_six_grids_each_sheet_fills_without_overlap(self):
        for paper_name, paper in PAPERS.items():
            for name, grid in GRIDS.items():
                with self.subTest(paper=paper_name, pattern=name):
                    options = CollageOptions(paper=paper_name, grid=name, fit_mode=FIT_MODE_EQUAL_BORDER)
                    task = build_collage_task(self.paths[:options.capacity], options, paper, 80)
                    self.assertTrue(LayoutMixin().validate_position(task)["ok"])
                    w, h = task["image"].size
                    boxes = grid_boxes((w, h), grid, round(80 * options.border_mm / 25.4))
                    self.assertEqual(sum((r-x)*(b-y) for (x, y, r, b), _ in boxes), w*h)
                    for i, ((x,y,r,b), (l,t,u,v)) in enumerate(boxes):
                        self.assertEqual((l-x,t-y,r-u,b-v), (6,)*4)
                        self.assertEqual(task["image"].getpixel((l,t)), self.color(i))
                        self.assertEqual(task["image"].getpixel((u-1,v-1)), self.color(i))
                        self.assertEqual(task["image"].getpixel((l-1,t)), (255,255,255))
                        self.assertEqual(task["image"].getpixel((u,v-1)), (255,255,255))

    def test_short_last_page_and_corrupt_cell(self):
        opts = CollageOptions()
        task = build_collage_task(self.paths[:1], opts, PAPERS["6寸"], 300)
        self.assertTrue(validate_collage(task)["warnings"])
        for slot in task["geometry"]["slots"][1:]:
            x,y,r,b = slot["frame"]
            self.assertEqual(task["image"].getpixel(((x+r)//2,(y+b)//2)), (255,255,255))
        task["geometry"]["slots"][0]["frame"] = (0,0,1,1)
        self.assertFalse(validate_collage(task)["ok"])

    def test_landscape_and_portrait_auto_with_manual_override(self):
        opts = CollageOptions(grid="四宫格")
        self.assertEqual(choose_paper(opts, [(900,600)]), PAPERS["6寸"][::-1])
        self.assertEqual(choose_paper(opts, [(600,900)]), PAPERS["6寸"])
        self.assertEqual(choose_paper(CollageOptions(orientation="横向"), [(600,900)]), PAPERS["6寸"][::-1])

    def test_native_pixels_at_300_and_600_dpi(self):
        opts = CollageOptions(fit_mode=FIT_MODE_NATIVE, cut_marks=False, auto_rotate=False)
        for dpi in (300, 600):
            task = build_collage_task(self.paths[:1], opts, PAPERS["6寸"], dpi)
            plane = task["image"].getchannel("R")
            # Source is black on the red channel, white elsewhere.
            self.assertEqual(plane.histogram()[0], 80 * 60)
            self.assertEqual(task["size"], tuple(round(mm*dpi/25.4) for mm in PAPERS["6寸"]))

    def test_enqueue_pages_then_late_file_error_is_atomic(self):
        app = Mock()
        app.batch_tasks = []
        app.dpi.get.return_value = 120
        app.validate_position.side_effect = LayoutMixin().validate_position
        editor = SimpleNamespace(app=app, photos=[(p, (80,60)) for p in self.paths[:5]],
                                 options=CollageOptions, close=Mock())
        CollageEditor.commit(editor)
        self.assertEqual([p["source_count"] for p in app.batch_tasks], [4,1])
        self.assertEqual([s for t in app.batch_tasks for s in t["source_paths"]], self.paths[:5])
        app.task_listbox.selection_set.assert_called_with(0)
        original = list(app.batch_tasks)
        editor.photos[-1] = (self.paths[4] + ".missing", (80,60))
        with patch("photo_layout.collage.messagebox.showerror") as error:
            CollageEditor.commit(editor)
            error.assert_called_once()
        self.assertEqual(app.batch_tasks, original)


if __name__ == "__main__":
    unittest.main()
