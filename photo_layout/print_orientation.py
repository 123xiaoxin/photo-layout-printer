"""Orient complete output sheets without changing their saved layout."""
from PIL import Image


PAPER_ORIENTATION_AUTO = "自动（跟随版面）"
PAPER_ORIENTATION_PORTRAIT = "纵向（短边在上）"
PAPER_ORIENTATION_LANDSCAPE = "横向（长边在上）"
PAPER_ORIENTATION_OPTIONS = (
    PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE,
)


def orient_paper_size(paper_mm, orientation=PAPER_ORIENTATION_AUTO):
    width, height = paper_mm
    if orientation not in PAPER_ORIENTATION_OPTIONS:
        raise ValueError("请选择有效的相纸横竖方向")
    if orientation == PAPER_ORIENTATION_AUTO:
        return width, height
    short, long = sorted((width, height))
    return (short, long) if orientation == PAPER_ORIENTATION_PORTRAIT else (long, short)


def task_output_paper_size(task, orientation=PAPER_ORIENTATION_AUTO):
    # A calibration chart's axes and profile are fixed when its window is opened.
    if task.get("kind") == "calibration":
        return tuple(task["paper_mm"])
    return orient_paper_size(task["paper_mm"], orientation)


def orient_print_task(task, orientation=PAPER_ORIENTATION_AUTO):
    paper = task_output_paper_size(task, orientation)
    output = dict(task, paper_mm=paper, _output_rotation_degrees=0)
    if paper != tuple(task["paper_mm"]):
        output["image"] = task["image"].transpose(Image.Transpose.ROTATE_270)
        output["size"] = output["image"].size
        output["_output_rotation_degrees"] = 90
    return output


def paper_orientation_label(paper_mm):
    width, height = paper_mm
    if abs(width - height) < 0.1:
        return "正方形"
    return PAPER_ORIENTATION_LANDSCAPE if width > height else PAPER_ORIENTATION_PORTRAIT
