"""Explicit offline diagnostics for the portable distribution. Never starts a print job."""
import importlib
import json
import platform
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_self_check(output_path):
    """Write UTF-8 JSON to the requested path; return 0 only when required checks pass."""
    report = {
        "schema": 1,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "bundle_directory": getattr(sys, "_MEIPASS", None),
        "application_directory": str(Path(sys.executable).parent) if getattr(sys, "frozen", False)
                                 else str(Path(__file__).resolve().parents[1]),
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": platform.architecture()[0],
        "modules": {},
        "checks": [],
    }
    state = {}
    root = None
    original_config = None
    configuration = None

    def check(name, operation):
        try:
            details = operation()
            report["checks"].append({"name": name, "status": "passed", "details": details})
        except Exception as error:
            report["checks"].append({
                "name": name, "status": "failed", "error": str(error),
                "exception": type(error).__name__, "traceback": traceback.format_exc(),
            })

    def remember(module):
        report["modules"][module.__name__] = getattr(module, "__file__", None)
        return module

    def app():
        _require("app" in state, "应用初始化失败，无法执行此检查")
        return state["app"]

    try:
        with tempfile.TemporaryDirectory(prefix="photo-layout-self-check-") as workspace:
            scratch = Path(workspace) / "中文路径 自检照片"
            scratch.mkdir()
            report["temporary_workspace"] = str(scratch)

            def pillow():
                from PIL import Image
                remember(importlib.import_module("PIL"))
                remember(Image)
                state["Image"] = Image
                return {"version": Image.__version__}
            check("pillow_import", pillow)

            for format_name, suffix in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("TIFF", "tiff")):
                def codec(name=format_name, extension=suffix):
                    Image = state["Image"]
                    path = scratch / f"色彩图像.{extension}"
                    source = Image.new("RGB", (180, 120), (20, 90, 160))
                    source.paste((220, 10, 30), (0, 0, 45, 60))
                    source.save(path, format=name)
                    with Image.open(path) as decoded:
                        _require(decoded.format == name, f"{name} 格式识别失败")
                        decoded.load()
                        _require(decoded.size == (180, 120), f"{name} 解码尺寸错误")
                        pixels = decoded.convert("RGB")
                        for x, y, expected in ((10, 10, (220, 10, 30)), (130, 90, (20, 90, 160))):
                            _require(max(abs(a - b) for a, b in zip(pixels.getpixel((x, y)), expected)) <= 15,
                                     f"{name} 解码颜色异常")
                    state[name] = str(path)
                    return {"path": str(path), "size": [180, 120], "bytes": path.stat().st_size}
                check(f"decode_{format_name.lower()}_unicode_path", codec)

            def tkdnd():
                nonlocal root
                import tkinter
                import tkinterdnd2
                from tkinterdnd2 import DND_FILES, TkinterDnD
                remember(tkinter)
                remember(tkinterdnd2)
                root = TkinterDnD.Tk()
                root.withdraw()
                callbacks = []
                root.report_callback_exception = lambda *args: callbacks.append(
                    "".join(traceback.format_exception(*args)))
                state["callback_errors"] = callbacks
                root.drop_target_register(DND_FILES)
                root.dnd_bind("<<Drop>>", lambda event: root.tk.splitlist(event.data))
                path = state.get("PNG", str(scratch / "测试.png"))
                _require(tuple(root.tk.splitlist(root.tk.call("list", path))) == (path,),
                         "Tk 中文路径传递失败")
                return {
                    "tcl_version": str(root.tk.call("info", "patchlevel")),
                    "tcl_library": str(root.tk.call("info", "library")),
                    "tk_library": str(root.tk.getvar("tk_library")),
                    "tkdnd_version": str(root.tk.call("package", "require", "tkdnd")),
                    "loaded_libraries": str(root.tk.call("info", "loaded")),
                    "drop_target_registered": True,
                }
            check("tkinter_tkdnd_runtime", tkdnd)

            def application():
                nonlocal configuration, original_config
                _require(root is not None, "TkDND 初始化失败")
                from . import configuration as config_module
                configuration = config_module
                original_config = configuration.CONFIG_FILE
                configuration.CONFIG_FILE = str(scratch / "自检配置.json")
                entry = sys.modules.get("__main__")
                if not hasattr(entry, "PhotoLayoutPrinter"):
                    entry = importlib.import_module("photo_layout_printer")
                remember(entry)
                instance = entry.PhotoLayoutPrinter(root)
                state["app"] = instance
                root.update()
                _require(hasattr(root, "dnd_bind"), "主程序未启用拖放组件")
                _require(not state["callback_errors"], "\n".join(state["callback_errors"]))
                _require(root.state() == "withdrawn", "自检窗口未隐藏")
                return {"class": type(instance).__name__, "config_file": configuration.CONFIG_FILE,
                        "default_config_untouched": True}
            check("application_initialization", application)

            def standard_layouts():
                instance = app()
                from .specifications import LAYOUT_OPTIONS
                instance.dpi.set(150)
                instance.set_image_from_file(state["PNG"], 0)
                instance.set_image_from_file(state["JPEG"], 1)
                sizes = {}
                for layout in LAYOUT_OPTIONS:
                    instance.layout_mode.set(layout)
                    instance.reprocess_all_and_update()
                    task, errors = instance.build_current_task()
                    _require(task is not None, str(errors))
                    _require(instance.validate_position(task)["ok"], "排版校验失败")
                    sizes[layout] = task["image"].size
                root.update()
                return sizes
            check("standard_photo_layouts", standard_layouts)

            def batch_editing():
                instance = app()
                from .specifications import FIT_MODE_EQUAL_BORDER
                instance.layout_mode.set("5寸+3寸")
                instance.on_layout_changed()
                instance.fit_mode.set(FIT_MODE_EQUAL_BORDER)
                instance.enable_margin.set(True)
                instance.margin_mm.set(1)
                instance.middle_margin_mm.set(0)
                instance.on_settings_changed(reprocess=True)
                for _ in range(2):
                    instance.add_task()
                _require(len(instance.batch_tasks) == 2, "照片组未正确加入队列")
                instance.task_listbox._choose(1)
                instance.rotate_photo(0)
                _require(instance.preview_task_index == 1, "旋转后跳离当前照片组")
                _require(instance.batch_tasks[0]["rotations"] == [0, 0], "旋转误改了其他组")
                _require(instance.batch_tasks[1]["rotations"] == [90, 0], "当前组旋转未保存")
                instance.batch_tasks[0]["checked_for_print"] = True
                instance.margin_mm.set(3)
                instance.on_settings_changed(reprocess=True)
                root.update()
                _require(all(task["margin_mm"] == 3 for task in instance.batch_tasks),
                         "批量留白没有更新全部照片组")
                _require(instance.preview_task_index == 1, "批量设置后跳离当前照片组")
                _require(instance.batch_tasks[0]["checked_for_print"], "打印勾选丢失")
                for task in instance.batch_tasks:
                    _require(task["validation"]["ok"], "修改后的照片组校验失败")
                    for slot in task["geometry"]["slots"]:
                        frame, photo = slot["frame"], slot["photo"]
                        edges = (photo[0]-frame[0], photo[1]-frame[1],
                                 frame[2]-photo[2], frame[3]-photo[3])
                        _require(all(abs(edge*25.4/task["dpi"]-3) <= 25.4/task["dpi"] for edge in edges),
                                 "留白数字与实际照片位置不一致")
                instance.task_listbox._choose(0)
                _require(instance.rotation_angles == [0, 0], "切换组后照片状态不对应")
                instance.task_listbox._choose(1)
                _require(instance.rotation_angles == [90, 0], "切回后旋转状态丢失")
                instance.detach_task_editor()
                instance.batch_tasks.clear()
                instance.update_task_list()
                return {"groups": 2, "rotation_follows_selection": True,
                        "all_groups_margin_mm": 3, "print_checks_preserved": True}
            check("selected_group_rotation_and_batch_margins", batch_editing)

            def collage():
                instance = app()
                from .collage_layout import CollageOptions, PAPERS, build_collage_task
                options = CollageOptions(paper="7寸", grid="四宫格", orientation="竖向")
                task = build_collage_task([state["PNG"], state["JPEG"], state["WEBP"], state["TIFF"]],
                                          options, PAPERS["7寸"], 150)
                _require(instance.validate_position(task)["ok"], "多图排版校验失败")
                instance.batch_tasks.append(task)
                instance.update_task_list()
                instance.task_listbox._choose(len(instance.batch_tasks) - 1)
                root.update()
                _require(instance.preview_task_index == len(instance.batch_tasks) - 1, "队列预览切换失败")
                return {"size": task["image"].size, "sources": task["source_count"],
                        "paper_mm": task["paper_mm"]}
            check("collage_and_queue", collage)

            def calibration():
                instance = app()
                from .print_orientation import PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE
                results = {}
                for direction in (PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE):
                    instance.paper_orientation.set(direction)
                    target = instance.calibration_target()
                    task = instance.build_calibration_task(target)
                    expected = tuple(round(mm * target.dpi / 25.4) for mm in target.paper_mm)
                    _require(task["image"].size == expected, "校准图毫米尺寸不匹配")
                    width, height = task["image"].size
                    _require((width > height) == (direction == PAPER_ORIENTATION_LANDSCAPE),
                             "校准图方向不匹配")
                    results[direction] = {"paper_mm": target.paper_mm, "size": expected, "dpi": target.dpi}
                return results
            check("portrait_landscape_calibration", calibration)

            def persistence():
                instance = app()
                from .print_orientation import PAPER_ORIENTATION_PORTRAIT, PAPER_ORIENTATION_LANDSCAPE
                instance.paper_orientation.set(PAPER_ORIENTATION_LANDSCAPE)
                _require(instance.save_config(), getattr(instance, "last_config_error", "配置保存失败"))
                saved = json.loads(Path(configuration.CONFIG_FILE).read_text(encoding="utf-8"))
                _require(saved["paper_orientation"] == PAPER_ORIENTATION_LANDSCAPE, "方向未写入配置")
                instance.paper_orientation.set(PAPER_ORIENTATION_PORTRAIT)
                instance.load_config()
                _require(instance.paper_orientation.get() == PAPER_ORIENTATION_LANDSCAPE, "配置重载方向错误")
                return {"path": configuration.CONFIG_FILE, "orientation": instance.paper_orientation.get(),
                        "bytes": Path(configuration.CONFIG_FILE).stat().st_size}
            check("configuration_save_reload", persistence)

            def printing_import():
                import win32print
                import win32ui
                import pywintypes
                from PIL import ImageWin
                for module in (win32print, win32ui, pywintypes, ImageWin):
                    remember(module)
                queues = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL |
                                                win32print.PRINTER_ENUM_CONNECTIONS, None, 4)
                state["queues"] = [queue["pPrinterName"] for queue in queues]
                return {"queues": state["queues"], "count": len(queues)}
            check("windows_print_runtime_and_enumeration", printing_import)

            if "Microsoft Print to PDF" not in state.get("queues", []):
                report["checks"].append({"name": "pdf_driver_dc", "status": "skipped",
                                         "reason": "系统未枚举到 Microsoft Print to PDF"})
                report["checks"].append({"name": "driver_page_profile_reuse", "status": "skipped",
                                         "reason": "系统未枚举到 Microsoft Print to PDF"})
            else:
                def pdf_driver():
                    import ctypes
                    from ctypes import wintypes
                    import win32ui
                    from .configuration import CalibrationTarget
                    from .printer_geometry import print_placement
                    instance = app()
                    kernel = ctypes.windll.kernel32
                    gdi = ctypes.windll.gdi32
                    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
                    gdi.CreateDCW.restype = wintypes.HDC
                    gdi.DeleteDC.argtypes = [wintypes.HDC]
                    gdi.DeleteDC.restype = wintypes.BOOL
                    results = []
                    name = "Microsoft Print to PDF"
                    for paper in ((210.0, 297.0), (297.0, 210.0)):
                        handle, note = instance.create_target_devmode_handle(name, paper)
                        pointer = kernel.GlobalLock(handle)
                        raw_dc = None
                        dc = None
                        try:
                            _require(pointer, "无法读取纸型设置")
                            raw_dc = gdi.CreateDCW("WINSPOOL", name, None, pointer)
                            _require(raw_dc, "无法创建虚拟打印机 DC")
                            dc = win32ui.CreateDCFromHandle(raw_dc)
                            raw_dc = None
                            caps = instance.get_printer_info_from_dc(dc, name)
                            actual = (caps["physical_width"] * 25.4 / caps["logpixels_x"],
                                      caps["physical_height"] * 25.4 / caps["logpixels_y"])
                            _require(max(abs(a - b) for a, b in zip(actual, paper)) < 0.2,
                                     f"驱动相纸尺寸不匹配 {actual}")
                            task = instance.build_calibration_task(CalibrationTarget(name, "A4 自检", paper, 150))
                            plan = print_placement(task, caps)
                            _require(plan.scale == 1.0, "毫米校准图被缩放")
                            results.append({"requested_mm": paper, "actual_mm": actual, "scale": plan.scale,
                                            "device_box": plan.device_box, "setup": note})
                        finally:
                            if dc is not None:
                                dc.DeleteDC()
                            elif raw_dc:
                                gdi.DeleteDC(raw_dc)
                            if pointer:
                                kernel.GlobalUnlock(handle)
                            kernel.GlobalFree(handle)
                    return {"pages": results, "jobs_submitted": 0}
                check("pdf_driver_dc", pdf_driver)

                def page_profile():
                    from .driver_settings import (target_devmode, driver_identity,
                                                   parse_devmode, validate_target_dc)
                    instance = app()
                    queue, paper = "Microsoft Print to PDF", (89.0, 127.0)
                    data, _ = target_devmode(instance, queue, paper)
                    identity = driver_identity(queue)
                    instance.save_driver_page_profile(queue, paper, data, identity)
                    instance.driver_page_profiles = {}
                    instance.load_config()
                    restored = instance.get_driver_page_profile(queue, paper)
                    _require(restored is not None and restored["devmode_bytes"] == data,
                             "重载后打印机页面设置不完整")
                    _require(instance.get_driver_page_profile(queue, paper[::-1]) is None,
                             "横竖方向混用了同一页面设置")
                    reused, note = target_devmode(instance, queue, paper)
                    _require(note.startswith("采用软件保存"), "打印时未载入保存的页面设置")
                    actual = validate_target_dc(queue, reused, paper)
                    instance.reset_driver_page_profile(queue, paper)
                    return {"bytes": len(data), "private_bytes": parse_devmode(data).dmDriverExtra,
                            "reloaded": True, "actual_mm": actual, "jobs_submitted": 0}
                check("driver_page_profile_reuse", page_profile)

            def runtime_paths():
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.windll.kernel32
                kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
                kernel.GetModuleFileNameW.restype = wintypes.DWORD
                kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
                kernel.GetModuleHandleW.restype = wintypes.HMODULE
                buffer = ctypes.create_unicode_buffer(32768)
                length = kernel.GetModuleFileNameW(ctypes.pythonapi._handle, buffer, len(buffer))
                _require(0 < length < len(buffer), "无法定位 Python 运行时 DLL")
                origins = {"python_dll": buffer.value}
                for name in ("PIL._imaging", "_tkinter", "tkinterdnd2", "win32print", "win32ui"):
                    module = remember(importlib.import_module(name))
                    origins[name] = module.__file__
                for name in ("mfc140u.dll", "vcruntime140.dll", "vcruntime140_1.dll",
                             "msvcp140.dll", "tcl86t.dll", "tk86t.dll"):
                    handle = kernel.GetModuleHandleW(name)
                    if not handle:
                        _require(name != "mfc140u.dll", "win32ui 导入后未加载必需的 mfc140u.dll")
                        continue
                    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
                    _require(0 < length < len(buffer), f"无法定位已加载的 {name}")
                    origins[name] = buffer.value
                if root is not None:
                    origins["tcl_library"] = str(root.tk.call("info", "library"))
                    origins["tk_library"] = str(root.tk.getvar("tk_library"))
                    for filename, package in root.tk.call("info", "loaded"):
                        if filename:
                            origins[f"tcl_extension_{package}"] = filename
                if getattr(sys, "frozen", False):
                    locations = [Path(sys._MEIPASS).resolve(), Path(sys.executable).resolve().parent]
                    outside = {name: path for name, path in origins.items()
                               if not any(Path(path).resolve().is_relative_to(location) for location in locations)}
                    _require(not outside, f"运行时使用了便携包之外的依赖：{outside}")
                return origins
            check("runtime_dependency_paths", runtime_paths)

            if root is not None:
                def callbacks():
                    root.update()
                    _require(not state.get("callback_errors"), "\n".join(state.get("callback_errors", [])))
                    return {"errors": []}
                check("tk_callback_errors", callbacks)
    except Exception as error:
        report["checks"].append({"name": "diagnostic_setup", "status": "failed", "error": str(error),
                                  "traceback": traceback.format_exc()})
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception as error:
                report["checks"].append({"name": "tk_cleanup", "status": "failed", "error": str(error)})
        if configuration is not None and original_config is not None:
            configuration.CONFIG_FILE = original_config
        for name, module in tuple(sys.modules.items()):
            if name.startswith(("photo_layout.", "PIL.", "tkinterdnd2", "win32", "_tkinter")):
                origin = getattr(module, "__file__", None)
                if origin:
                    report["modules"][name] = origin
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        report["success"] = all(check["status"] != "failed" for check in report["checks"])
        destination = Path(output_path).expanduser().resolve()
        report["report_path"] = str(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return 2
    return 0 if report["success"] else 1
