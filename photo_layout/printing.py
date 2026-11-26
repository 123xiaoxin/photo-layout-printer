"""Windows printer integration and calibration."""
from tkinter import messagebox
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import sys
from datetime import datetime
from .configuration import CalibrationTarget
from .driver_settings import DriverSettingsError, devmode_from_handle, public_settings, confirmed_public_settings
from .printer_geometry import print_placement
from .print_orientation import (PAPER_ORIENTATION_AUTO, orient_paper_size,
                                task_output_paper_size, orient_print_task, paper_orientation_label)
from .specifications import DC_PAPERNAMES, DC_PAPERS, DC_PAPERSIZE, DMORIENT_LANDSCAPE, DMORIENT_PORTRAIT, DMPAPER_USER, DM_IN_BUFFER, DM_ORIENTATION, DM_OUT_BUFFER, DM_PAPERLENGTH, DM_PAPERSIZE, DM_PAPERWIDTH, GMEM_MOVEABLE, GMEM_ZEROINIT, MM_TO_INCH, PRINT_METHOD_DIRECT, PRINT_METHOD_OPTIONS, PRINT_METHOD_SYSTEM

class PrintingMixin:
    """Behavior used by the application controller."""
    def get_pil_font(self, size, bold=False):
        candidates = [
            "msyhbd.ttc" if bold else "msyh.ttc",
            "simhei.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
        ]
        for name in candidates:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()


    def draw_centered_text(self, draw, box, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = box[0] + (box[2] - box[0] - text_w) // 2
        y = box[1] + (box[3] - box[1] - text_h) // 2
        draw.text((x, y), text, font=font, fill=fill)


    def current_paper_orientation(self):
        variable = getattr(self, "paper_orientation", None)
        return variable.get() if variable is not None else PAPER_ORIENTATION_AUTO

    def calibration_target(self, orientation=None):
        index = self.preview_task_index
        if index is not None and 0 <= index < len(self.batch_tasks):
            task = self.batch_tasks[index]
            layout, paper_mm, dpi = task["layout"], task["paper_mm"], task["dpi"]
        else:
            layout, paper_mm, dpi = self.layout_mode.get(), self.get_layout_base()["paper_mm"], self.dpi.get()
        orientation = self.current_paper_orientation() if orientation is None else orientation
        return CalibrationTarget(self.selected_printer_name.get(), layout,
                                 orient_paper_size(paper_mm, orientation), dpi)

    def make_calibration_chart(self, target=None):
        from .calibration_chart import render_calibration_chart
        target = target or self.calibration_target()
        offsets = self.calibration_offsets_for(target.printer, target.layout, target.paper_mm)
        return render_calibration_chart(target, offsets)


    def build_calibration_task(self, target=None):
        target = target or self.calibration_target()
        image = self.make_calibration_chart(target)
        return {
            "image": image,
            "kind": "calibration",
            "layout": target.layout,
            "dpi": target.dpi,
            "paper_mm": target.paper_mm,
            "size": image.size,
            "created": datetime.now().strftime("%H:%M:%S"),
        }


    def print_calibration_chart(self, target=None):
        target = target or self.calibration_target()
        task = self.build_calibration_task(target)
        if self.print_method.get() == PRINT_METHOD_SYSTEM:
            messagebox.showinfo(
                "系统打印设置",
                "接下来会打开 Windows 系统打印对话框。\n\n软件会先按当前相纸尺寸和方向初始化驱动设置；请在对话框里确认相纸尺寸、方向、照片纸类型，并关闭缩放/适应页面。",
            )
        printer_info, printer_dc, cleanup = self.prepare_print_context([task], "校准打印")
        if printer_info is None:
            return

        try:
            if target.printer and printer_info["name"] != target.printer:
                messagebox.showwarning("校准打印机已改变",
                    f"此校准图属于 {target.printer}。请关闭高级校准，在目标打印机上重新打开。")
                return
            self.print_tasks_with_win32([task], printer_info, doc_name="Merchant Pro Calibration Print", printer_dc=printer_dc)
            messagebox.showinfo("校准打印已提交", "校准图已提交到打印机。")
            self.status_var.set("校准打印已提交")
        except Exception as e:
            messagebox.showerror("校准打印失败", str(e))
            self.status_var.set("校准打印失败")
        finally:
            self.close_system_print_context(printer_dc, cleanup)


    def list_available_printers(self):
        if not sys.platform.startswith("win"):
            return [], ["当前系统暂不支持直接批量打印，请在 Windows 上运行"]

        # Method 1: Try pywin32 first
        has_pywin32 = False
        try:
            import win32print
            has_pywin32 = True
        except ImportError:
            has_pywin32 = False

        if has_pywin32:
            try:
                flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                printers = []
                for item in win32print.EnumPrinters(flags, None, 1):
                    name = item.get("pPrinterName") if isinstance(item, dict) else item[2]
                    if name and name not in printers:
                        printers.append(name)
                return printers, []
            except Exception as e:
                # Fall through to ctypes method
                pass

        # Method 2: Fallback using ctypes (no pywin32 required)
        try:
            import ctypes
            from ctypes import wintypes

            PRINTER_ENUM_LOCAL = 0x00000002
            PRINTER_ENUM_CONNECTIONS = 0x00000004

            class PRINTER_INFO_1(ctypes.Structure):
                _fields_ = [
                    ("Flags", wintypes.DWORD),
                    ("pDescription", wintypes.LPWSTR),
                    ("pName", wintypes.LPWSTR),
                    ("pComment", wintypes.LPWSTR),
                ]

            winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
            EnumPrintersW = winspool.EnumPrintersW
            EnumPrintersW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            ]
            EnumPrintersW.restype = wintypes.BOOL

            flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
            cb_needed = wintypes.DWORD(0)
            c_returned = wintypes.DWORD(0)

            # First call to get buffer size
            EnumPrintersW(flags, None, 1, None, 0, ctypes.byref(cb_needed), ctypes.byref(c_returned))
            if cb_needed.value > 0:
                buf = (ctypes.c_byte * cb_needed.value)()
                if EnumPrintersW(
                    flags, None, 1,
                    ctypes.cast(buf, ctypes.c_void_p), cb_needed.value,
                    ctypes.byref(cb_needed), ctypes.byref(c_returned),
                ):
                    p_info_array = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_1))
                    printers = []
                    for i in range(c_returned.value):
                        name = p_info_array[i].pName
                        if name and name not in printers:
                            printers.append(name)

                    if printers:
                        return printers, []
            return [], ["未检测到可用打印机，请检查打印机连接和驱动"]
        except Exception as e:
            return [], [f"无法读取打印机列表 (ctypes fallback): {e}"]


    @staticmethod
    def windows_default_printer():
        import ctypes
        from ctypes import wintypes

        if not sys.platform.startswith("win"):
            return ""
        get_default = ctypes.WinDLL("winspool.drv", use_last_error=True).GetDefaultPrinterW
        get_default.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        get_default.restype = wintypes.BOOL
        size = wintypes.DWORD(0)
        get_default(None, ctypes.byref(size))
        if size.value:
            name = ctypes.create_unicode_buffer(size.value)
            if get_default(name, ctypes.byref(size)):
                return name.value
        return ""

    def refresh_printer_list(self, show_status=True, save=True):
        printers, errors = self.list_available_printers()
        self.printer_names = printers
        default = self.windows_default_printer()
        queues = {name.casefold(): name for name in printers}
        legacy = getattr(self, "legacy_selected_printer", "")
        if legacy and not errors:
            self.follow_system_printer.set(legacy.casefold() == default.casefold())
            self.manual_printer_name = legacy
            self.legacy_selected_printer = ""

        if self.follow_system_printer.get():
            name = queues.get(default.casefold(), "")
            if not default and len(printers) == 1:
                name = printers[0]
            if not name and not errors:
                if default:
                    errors = [f"Windows 默认打印机「{default}」当前不可用，请刷新或手动选择设备。"]
                elif printers:
                    errors = ["检测到多台打印机，但 Windows 未设置默认打印机。请从列表选择本次使用的设备。"]
                else:
                    errors = ["未检测到打印队列，请先在 Windows 中连接打印机。"]
        else:
            pinned = self.manual_printer_name
            name = queues.get(pinned.casefold(), pinned)
            if pinned.casefold() not in queues and not errors:
                errors = [f"固定打印机「{pinned}」当前不可用。请重新连接，或选择其他设备。"]

        self.selected_printer_name.set(name)
        self.load_template_offsets()
        self.sync_printer_selector()
        if save:
            self.save_config()
        if show_status:
            if errors:
                self.status_var.set(errors[0])
            else:
                mode = "自动选择" if self.follow_system_printer.get() else "固定设备"
                self.status_var.set(f"{mode} · {self.printer_display_name(name)}")
        return printers, errors

    def sync_printer_selector(self):
        if self.printer_combo is None:
            return
        # Keep routing tied to the queue behind each row, even when display names change.
        self.printer_choice_queues = tuple(self.printer_names)
        labels = [self.printer_display_name(q) for q in self.printer_choice_queues]
        self.printer_combo.configure(values=labels, state="readonly" if labels else "disabled")
        queue = self.selected_printer_name.get()
        if queue in self.printer_choice_queues:
            self.printer_combo.current(self.printer_choice_queues.index(queue))
        else:
            self.printer_combo.set(self.printer_display_name(queue))

    def select_displayed_printer(self, _event=None):
        index = self.printer_combo.current()
        if 0 <= index < len(self.printer_choice_queues):
            self.selected_printer_name.set(self.printer_choice_queues[index])
            self.on_printer_selected()

    def on_printer_selected(self, _event=None):
        name = self.selected_printer_name.get().strip()
        if name:
            self.follow_system_printer.set(False)
            self.manual_printer_name = name
            self.legacy_selected_printer = ""
            self.load_template_offsets()
            self.save_config()
            self.sync_printer_selector()
            self.status_var.set(f"已固定打印机：{self.printer_display_name(name)}")

    def on_follow_system_printer_changed(self):
        self.legacy_selected_printer = ""
        if not self.follow_system_printer.get() and not self.manual_printer_name:
            self.manual_printer_name = self.selected_printer_name.get().strip()
        self.refresh_printer_list()


    def on_print_method_changed(self, _event=None):
        if self.print_method.get() not in PRINT_METHOD_OPTIONS:
            self.print_method.set(PRINT_METHOD_DIRECT)
        self.save_config()
        self.status_var.set(f"打印方式：{self.print_method.get()}")


    def get_selected_printer_info(self):
        if not sys.platform.startswith("win"):
            return None, ["当前系统暂不支持直接批量打印，请在 Windows 上运行"]
        try:
            import win32print
            import win32ui
        except ImportError:
            return None, ["缺少 pywin32，无法使用批量打印引擎"]

        hdc = None
        try:
            printer_name = self.selected_printer_name.get().strip()
            if not printer_name:
                return None, ["未选择可用打印机"]

            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            return self.get_printer_info_from_dc(hdc, printer_name), []
        except Exception as e:
            return None, [f"无法读取打印机 {self.selected_printer_name.get()}: {e}"]
        finally:
            if hdc is not None:
                try:
                    hdc.DeleteDC()
                except Exception:
                    pass


    def get_default_printer_info(self):
        return self.get_selected_printer_info()


    def get_printer_info_from_dc(self, hdc, printer_name):
        return {
            "name": printer_name,
            "driver_name": self.printer_driver_name(printer_name),
            "horzres": hdc.GetDeviceCaps(8),
            "vertres": hdc.GetDeviceCaps(10),
            "physical_width": hdc.GetDeviceCaps(110),
            "physical_height": hdc.GetDeviceCaps(111),
            "offset_x": hdc.GetDeviceCaps(112),
            "offset_y": hdc.GetDeviceCaps(113),
            "logpixels_x": hdc.GetDeviceCaps(88),
            "logpixels_y": hdc.GetDeviceCaps(90),
        }

    @staticmethod
    def printer_driver_name(printer_name):
        """A renamed/shared queue can have an entirely different display name."""
        import pywintypes
        import win32print
        try:
            handle = win32print.OpenPrinter(printer_name)
            try:
                return win32print.GetPrinter(handle, 2).get("pDriverName") or ""
            finally:
                win32print.ClosePrinter(handle)
        except (OSError, pywintypes.error):
            # Geometry remains available from the negotiated DC even if metadata is restricted.
            return ""


    def resolve_print_paper_mm(self, tasks, paper_orientation=None):
        orientation = self.current_paper_orientation() if paper_orientation is None else paper_orientation
        if tasks:
            papers = [task_output_paper_size(task, orientation) for task in tasks if "paper_mm" in task]
        else:
            papers = [orient_paper_size(self.get_layout_base()["paper_mm"], orientation)]
        if not papers:
            return None, ["未找到本次打印的相纸尺寸"]

        first = papers[0]
        for paper in papers[1:]:
            if any(abs(a - b) > 0.2 for a, b in zip(sorted(first), sorted(paper))):
                return None, [
                    "当前批次包含不同相纸尺寸，请分开打印。",
                    f"检测到 {first[0]:.1f}x{first[1]:.1f}mm 和 {paper[0]:.1f}x{paper[1]:.1f}mm。",
                ]
        return first, []

    def bind_output_tasks(self, printer_info, tasks, orientation, target_paper_mm):
        printer_info["paper_orientation"] = orientation
        printer_info["target_paper_mm"] = target_paper_mm
        printer_info["_output_tasks"] = {id(task): orient_print_task(task, orientation)
                                         for task in (tasks or [])}
        return printer_info


    def find_supported_printer_paper(self, printer_name, paper_mm):
        from .printer_forms import match_paper, read_supported_media
        papers, _fields = read_supported_media(printer_name)
        return match_paper(papers, paper_mm)


    def create_print_devnames_handle(self, printer_name):
        import ctypes
        from ctypes import wintypes
        import win32print

        class DEVNAMES(ctypes.Structure):
            _fields_ = [
                ("wDriverOffset", ctypes.c_ushort),
                ("wDeviceOffset", ctypes.c_ushort),
                ("wOutputOffset", ctypes.c_ushort),
                ("wDefault", ctypes.c_ushort),
            ]

        driver_name = "winspool"
        port_name = ""
        printer_handle = None
        try:
            printer_handle = win32print.OpenPrinter(printer_name)
            info = win32print.GetPrinter(printer_handle, 2)
            driver_name = info.get("pDriverName") or driver_name
            port_name = info.get("pPortName") or ""
        except Exception:
            pass
        finally:
            if printer_handle is not None:
                try:
                    win32print.ClosePrinter(printer_handle)
                except Exception:
                    pass

        strings = [driver_name, printer_name, port_name]
        header_chars = ctypes.sizeof(DEVNAMES) // ctypes.sizeof(ctypes.c_wchar)
        total_chars = header_chars + sum(len(text) + 1 for text in strings)
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, total_chars * ctypes.sizeof(ctypes.c_wchar))
        if not handle:
            raise OSError("无法分配打印机名称内存")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise OSError("无法锁定打印机名称内存")
        try:
            devnames = DEVNAMES.from_address(ptr)
            buffer = (ctypes.c_wchar * total_chars).from_address(ptr)
            pos = header_chars
            offsets = []
            for text in strings:
                offsets.append(pos)
                for char in text:
                    buffer[pos] = char
                    pos += 1
                buffer[pos] = "\x00"
                pos += 1
            devnames.wDriverOffset = offsets[0]
            devnames.wDeviceOffset = offsets[1]
            devnames.wOutputOffset = offsets[2]
            devnames.wDefault = 0
        except Exception:
            kernel32.GlobalUnlock(handle)
            kernel32.GlobalFree(handle)
            raise
        kernel32.GlobalUnlock(handle)
        return handle


    def create_target_devmode_handle(self, printer_name, paper_mm, hwnd_owner=None):
        from .driver_settings import target_devmode, devmode_handle
        blob, note = target_devmode(self, printer_name, paper_mm, hwnd_owner)
        return devmode_handle(blob), note

    def edit_printer_page_settings(self, target=None, owner=None):
        from .driver_settings import edit_page_settings
        target = target or self.calibration_target()
        owner = owner if owner is not None else getattr(self, "root", None)
        return edit_page_settings(self, target, owner)


    def get_printer_name_from_devnames(self, devnames_handle):
        if not devnames_handle:
            return ""
        import ctypes
        from ctypes import wintypes

        class DEVNAMES(ctypes.Structure):
            _fields_ = [
                ("wDriverOffset", ctypes.c_ushort),
                ("wDeviceOffset", ctypes.c_ushort),
                ("wOutputOffset", ctypes.c_ushort),
                ("wDefault", ctypes.c_ushort),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        ptr = kernel32.GlobalLock(devnames_handle)
        if not ptr:
            return ""
        try:
            devnames = DEVNAMES.from_address(ptr)
            address = ptr + devnames.wDeviceOffset * ctypes.sizeof(ctypes.c_wchar)
            return ctypes.wstring_at(address)
        finally:
            kernel32.GlobalUnlock(devnames_handle)


    def open_system_print_dialog(self, tasks=None, paper_orientation=None):
        if not sys.platform.startswith("win"):
            return None, None, None, ["当前系统暂不支持系统打印对话框，请在 Windows 上运行"], False
        try:
            import ctypes
            from ctypes import wintypes
            import win32con
            import win32print
            import win32ui
        except ImportError:
            return None, None, None, ["缺少 pywin32，无法打开系统打印对话框"], False

        orientation = self.current_paper_orientation() if paper_orientation is None else paper_orientation
        target_paper_mm, paper_errors = self.resolve_print_paper_mm(tasks, orientation)
        if paper_errors:
            return None, None, None, paper_errors, False

        class PRINTDLG(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hDevMode", wintypes.HGLOBAL),
                ("hDevNames", wintypes.HGLOBAL),
                ("hDC", wintypes.HDC),
                ("Flags", wintypes.DWORD),
                ("nFromPage", wintypes.WORD),
                ("nToPage", wintypes.WORD),
                ("nMinPage", wintypes.WORD),
                ("nMaxPage", wintypes.WORD),
                ("nCopies", wintypes.WORD),
                ("hInstance", wintypes.HINSTANCE),
                ("lCustData", wintypes.LPARAM),
                ("lpfnPrintHook", wintypes.LPVOID),
                ("lpfnSetupHook", wintypes.LPVOID),
                ("lpPrintTemplateName", wintypes.LPCWSTR),
                ("lpSetupTemplateName", wintypes.LPCWSTR),
                ("hPrintTemplate", wintypes.HGLOBAL),
                ("hSetupTemplate", wintypes.HGLOBAL),
            ]

        pd = PRINTDLG()
        pd.lStructSize = ctypes.sizeof(PRINTDLG)
        try:
            pd.hwndOwner = self.root.winfo_id()
        except Exception:
            pd.hwndOwner = None

        printer_name = self.selected_printer_name.get().strip()
        if printer_name:
            try:
                pd.hDevNames = self.create_print_devnames_handle(printer_name)
            except Exception as error:
                return None, None, None, [f"无法将系统打印窗口定位到「{printer_name}」：{error}"], False
            setup_warning = ""
            try:
                pd.hDevMode, setup_note = self.create_target_devmode_handle(printer_name, target_paper_mm, pd.hwndOwner)
                self.status_var.set(f"已初始化打印设置：{setup_note}")
                self.root.update_idletasks()
            except Exception as e:
                if pd.hDevMode:
                    ctypes.windll.kernel32.GlobalFree(pd.hDevMode)
                    pd.hDevMode = None
                try:
                    getter = getattr(self, "get_driver_page_profile", None)
                    saved_settings = bool(getter and getter(printer_name, target_paper_mm))
                except (ValueError, TypeError):
                    saved_settings = True
                if saved_settings or isinstance(e, DriverSettingsError):
                    ctypes.windll.kernel32.GlobalFree(pd.hDevNames)
                    return None, None, None, [str(e)], False
                setup_note = ""
                setup_warning = f"自动初始化打印设置失败，请在对话框中手动选择相纸：{e}"
                pd.hDevMode = None
        else:
            return None, None, None, ["请先选择可用打印机"], False

        pd.nFromPage = 1
        pd.nToPage = 1
        pd.nMinPage = 1
        pd.nMaxPage = 1
        pd.nCopies = 1
        pd.Flags = (
            win32con.PD_RETURNDC
            | win32con.PD_USEDEVMODECOPIES
            | win32con.PD_NOSELECTION
            | win32con.PD_NOPAGENUMS
            | win32con.PD_HIDEPRINTTOFILE
        )

        comdlg32 = ctypes.windll.comdlg32
        kernel32 = ctypes.windll.kernel32
        comdlg32.PrintDlgW.argtypes = [ctypes.POINTER(PRINTDLG)]
        comdlg32.PrintDlgW.restype = wintypes.BOOL
        comdlg32.CommDlgExtendedError.restype = wintypes.DWORD
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        ctypes.windll.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        ctypes.windll.gdi32.DeleteDC.restype = wintypes.BOOL

        def free_dialog_handles():
            seen = set()
            for handle in (pd.hDevMode, pd.hDevNames):
                if not handle:
                    continue
                key = handle.value if hasattr(handle, "value") else int(handle)
                if key in seen:
                    continue
                seen.add(key)
                kernel32.GlobalFree(handle)

        if not comdlg32.PrintDlgW(ctypes.byref(pd)):
            error_code = comdlg32.CommDlgExtendedError()
            free_dialog_handles()
            if error_code == 0:
                return None, None, None, [], True
            return None, None, None, [f"系统打印对话框打开失败，错误码: {error_code}"], False

        cleanup_handles = [pd.hDevMode, pd.hDevNames]

        def cleanup():
            for handle in cleanup_handles:
                if handle:
                    kernel32.GlobalFree(handle)

        try:
            requested = printer_name
            printer_name = self.get_printer_name_from_devnames(pd.hDevNames)
            if not printer_name:
                raise ValueError("系统未返回确认后的打印机名称")
            hdc = win32ui.CreateDCFromHandle(pd.hDC)
            printer_info = self.get_printer_info_from_dc(hdc, printer_name)
            printer_info.update(confirmed_public_settings(printer_name, devmode_from_handle(pd.hDevMode)))
            self.bind_output_tasks(printer_info, tasks, orientation, target_paper_mm)
            printer_info["paper_setup_note"] = "采用本次系统窗口确认的页面设置（临时修改不会自动保存）"
            printer_info["paper_setup_warning"] = setup_warning
            if printer_name.casefold() != requested.casefold():
                self.selected_printer_name.set(printer_name)
                self.on_printer_selected()
            return printer_info, hdc, cleanup, [], False
        except Exception as e:
            try:
                if pd.hDC:
                    ctypes.windll.gdi32.DeleteDC(pd.hDC)
            finally:
                cleanup()
            return None, None, None, [f"无法读取系统打印设置: {e}"], False


    def open_direct_print_context(self, tasks=None, paper_orientation=None):
        if not sys.platform.startswith("win"):
            return None, None, None, ["当前系统暂不支持直接打印，请在 Windows 上运行"], False
        try:
            import ctypes
            from ctypes import wintypes
            import win32print
            import win32ui
        except ImportError:
            return None, None, None, ["缺少 pywin32，无法使用直接打印"], False

        orientation = self.current_paper_orientation() if paper_orientation is None else paper_orientation
        target_paper_mm, paper_errors = self.resolve_print_paper_mm(tasks, orientation)
        if paper_errors:
            return None, None, None, paper_errors, False

        printer_name = self.selected_printer_name.get().strip()
        if not printer_name:
            return None, None, None, ["未找到可用打印机"], False

        kernel32 = ctypes.windll.kernel32
        gdi32 = ctypes.windll.gdi32
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        gdi32.CreateDCW.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        devmode_handle = None
        devmode_ptr = None
        hdc_handle = None
        hdc = None
        saved_settings = False
        try:
            devmode_handle, setup_note = self.create_target_devmode_handle(printer_name, target_paper_mm, None)
            saved_settings = setup_note.startswith("采用软件保存")
            settings = public_settings(devmode_from_handle(devmode_handle))
            devmode_ptr = kernel32.GlobalLock(devmode_handle)
            if not devmode_ptr:
                raise OSError("无法锁定打印设置")

            hdc_handle = gdi32.CreateDCW("WINSPOOL", printer_name, None, devmode_ptr)
            kernel32.GlobalUnlock(devmode_handle)
            devmode_ptr = None
            if not hdc_handle:
                raise OSError("无法创建直接打印页面")

            hdc = win32ui.CreateDCFromHandle(hdc_handle)
            hdc_handle = None
            printer_info = self.get_printer_info_from_dc(hdc, printer_name)
            printer_info.update(settings)
            self.bind_output_tasks(printer_info, tasks, orientation, target_paper_mm)
            printer_info["paper_setup_note"] = setup_note
            printer_info["paper_setup_warning"] = ""
            self.status_var.set(f"直接打印设置：{setup_note}")
            self.root.update_idletasks()

            def cleanup():
                if devmode_handle:
                    kernel32.GlobalFree(devmode_handle)

            return printer_info, hdc, cleanup, [], False
        except Exception as e:
            if devmode_ptr and devmode_handle:
                kernel32.GlobalUnlock(devmode_handle)
            if hdc is not None:
                try:
                    hdc.DeleteDC()
                except Exception:
                    pass
            elif hdc_handle:
                gdi32.DeleteDC(hdc_handle)
            if devmode_handle:
                kernel32.GlobalFree(devmode_handle)
            try:
                getter = getattr(self, "get_driver_page_profile", None)
                saved_settings = saved_settings or bool(getter and getter(printer_name, target_paper_mm))
            except (ValueError, TypeError):
                saved_settings = True
            if saved_settings or isinstance(e, DriverSettingsError):
                return None, None, None, [f"已保存的打印机页面设置无法使用，请重新打开页面设置：{e}"], False
            # Fixed-media photo and label drivers may reject programmatic DEVMODE edits.
            # Read their active form. The same physical-size check still runs before StartDoc.
            fallback_dc = win32ui.CreateDC()
            try:
                fallback_dc.CreatePrinterDC(printer_name)
                info = self.get_printer_info_from_dc(fallback_dc, printer_name)
                self.bind_output_tasks(info, tasks, orientation, target_paper_mm)
                info["paper_setup_warning"] = "此驱动采用设备当前纸型，已改用驱动报告的页面验证并定位。"
                return info, fallback_dc, None, [], False
            except Exception as fallback_error:
                try:
                    fallback_dc.DeleteDC()
                except Exception:
                    pass
                return None, None, None, [f"无法初始化打印机 {printer_name}：{e}；读取默认页面也失败：{fallback_error}"], False


    def validate_printer_fit(self, printer_info, tasks=None):
        errors = []
        warnings = []
        if printer_info is None:
            errors.append("未找到可用打印机")
            return errors, warnings

        tasks = tasks if tasks is not None else self.batch_tasks
        placements = {}
        output_tasks = printer_info.setdefault("_output_tasks", {})
        orientation = printer_info.setdefault("paper_orientation", self.current_paper_orientation())
        for idx, task in enumerate(tasks, 1):
            try:
                if id(task) not in output_tasks:
                    output_tasks[id(task)] = orient_print_task(task, orientation)
                plan = self.placement_for_task(output_tasks[id(task)], printer_info)
            except (KeyError, ValueError) as error:
                errors.append(f"批次 {idx:02d}：{error}")
                continue
            placements[id(task)] = plan
            if plan.scale < 0.995:
                warnings.append(f"批次 {idx:02d}：为保留完整照片和裁切线，按原比例缩小到 {plan.scale:.1%}，并以纸张中心定位")
        printer_info["_placements"] = placements
        requested = printer_info.get("target_paper_mm")
        dx, dy = printer_info.get("logpixels_x", 0), printer_info.get("logpixels_y", 0)
        if requested and min(dx, dy) > 0:
            actual = (printer_info["physical_width"] * 25.4 / dx,
                      printer_info["physical_height"] * 25.4 / dy)
            if (paper_orientation_label(requested) != paper_orientation_label(actual)
                    and max(abs(a - b) for a, b in zip(sorted(requested), sorted(actual))) <= 3):
                warnings.insert(0,
                    f"本次请求{paper_orientation_label(requested)} {requested[0]:g} × {requested[1]:g} mm，"
                    f"驱动实际返回{paper_orientation_label(actual)} {actual[0]:.2f} × {actual[1]:.2f} mm。"
                    "将按驱动实际页面旋转整张版面；请核对纸张方向后再继续。")
        return errors, warnings

    def placement_for_task(self, task, printer_info):
        calibration = self.calibration_offsets_for(printer_info["name"], task.get("layout", ""), task["paper_mm"])
        return print_placement(task, printer_info, calibration)

    def print_tasks_with_win32(self, tasks, printer_info, doc_name="Merchant Pro Batch Print", printer_dc=None):
        from PIL import ImageWin

        hdc = printer_dc
        if hdc is None:
            raise ValueError("请先按本次纸型和方向创建并校验打印页面")
        output_tasks = printer_info.setdefault("_output_tasks", {})
        orientation = printer_info.setdefault("paper_orientation", self.current_paper_orientation())
        try:
            hdc.StartDoc(doc_name)
            for index, task in enumerate(tasks, 1):
                if id(task) not in output_tasks:
                    output_tasks[id(task)] = orient_print_task(task, orientation)
                output = output_tasks[id(task)]
                plan = printer_info.get("_placements", {}).get(id(task))
                if plan is None:
                    plan = self.placement_for_task(output, printer_info)
                img = output["image"]
                if plan.rotate_clockwise:
                    img = img.transpose(Image.Transpose.ROTATE_270)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                box = plan.device_box
                # Downsample with a filter only when necessary. Let GDI map native pixels
                # to higher-resolution device dots without allocating an oversized bitmap.
                draw_size = (min(img.width, box[2] - box[0]), min(img.height, box[3] - box[1]))
                if img.size != draw_size:
                    img = img.resize(draw_size, Image.Resampling.LANCZOS)
                dib = ImageWin.Dib(img)
                hdc.StartPage()
                dib.draw(hdc.GetHandleOutput(), box)
                hdc.EndPage()
                self.status_var.set(f"正在提交批次 {index}/{len(tasks)} 到打印机")
                self.root.update_idletasks()
            hdc.EndDoc()
        except Exception:
            try:
                hdc.AbortDoc()
            except Exception:
                pass
            raise


    def close_system_print_context(self, printer_dc, cleanup):
        try:
            if printer_dc is not None:
                printer_dc.DeleteDC()
        finally:
            if cleanup is not None:
                cleanup()


    def open_selected_print_context(self, tasks, paper_orientation=None):
        # Resolve the Windows queue at the point of use, including after hot-plug.
        orientation = self.current_paper_orientation() if paper_orientation is None else paper_orientation
        previous = self.selected_printer_name.get().strip()
        queues, errors = self.refresh_printer_list(show_status=False, save=False)
        if errors:
            return None, None, None, errors, False
        current = self.selected_printer_name.get().strip()
        if previous and current.casefold() != previous.casefold() and previous.casefold() not in {
            name.casefold() for name in queues
        }:
            return None, None, None, [
                f"原打印机「{previous}」已断开。现在显示的设备是「{current}」，请核对后重新操作。"
            ], False
        if self.print_method.get() == PRINT_METHOD_SYSTEM:
            return self.open_system_print_dialog(tasks=tasks, paper_orientation=orientation)
        return self.open_direct_print_context(tasks=tasks, paper_orientation=orientation)

    def prepare_print_context(self, tasks, label, paper_orientation=None):
        printer_info, printer_dc, cleanup, printer_errors, cancelled = self.open_selected_print_context(
            tasks, paper_orientation=paper_orientation)
        if cancelled:
            self.status_var.set(f"已取消{label}")
            return None, None, None
        if printer_errors:
            messagebox.showerror("打印机不可用", "\n".join(printer_errors))
            self.status_var.set(f"打印机不可用，{label}已取消")
            return None, None, None

        fit_errors, fit_warnings = self.validate_printer_fit(printer_info, tasks=tasks)
        if fit_errors:
            self.close_system_print_context(printer_dc, cleanup)
            messagebox.showerror("打印机页面校验失败", "\n".join(fit_errors[:8]))
            self.status_var.set(f"打印机页面校验失败，{label}已取消")
            return None, None, None

        if fit_warnings:
            warning_text = "\n".join(fit_warnings[:6])
            if not messagebox.askyesno("打印区域提示", f"{warning_text}\n\n仍然继续打印吗？"):
                self.close_system_print_context(printer_dc, cleanup)
                self.status_var.set(f"已取消{label}")
                return None, None, None

        return printer_info, printer_dc, cleanup


    def prepare_system_print_context(self, tasks, label):
        return self.prepare_print_context(tasks, label)


    def previewed_print_task(self):
        index = self.preview_task_index
        if index is not None and 0 <= index < len(self.batch_tasks):
            return self.batch_tasks[index], []
        return self.build_current_task()

    def inspect_preview_printer_placement(self):
        """Inspect the chosen printer DC and release it without starting a spool job."""
        task, errors = self.previewed_print_task()
        if task is None and any(photo is not None for photo in self.original_images):
            messagebox.showerror("当前版面无法检查", "\n".join(errors))
            return
        if task is None:
            task = self.build_calibration_task()
            source = "当前纸型的校准图（未导入照片，刻度固定为原尺寸）"
        elif self.preview_task_index is not None:
            source = f"批次 {self.preview_task_index + 1:03d} · {task['layout']}"
        else:
            source = f"当前版面 · {task['layout']}"
        caps, dc, cleanup, driver_errors, cancelled = self.open_selected_print_context([task])
        try:
            if cancelled:
                self.status_var.set("已取消打印定位检查")
                return
            if driver_errors or caps is None:
                messagebox.showerror("无法读取打印机", "\n".join(driver_errors) or "驱动未返回页面信息")
                return
            errors, warnings = self.validate_printer_fit(caps, [task])
            output = caps["_output_tasks"].get(id(task), task)
            requested = caps.get("target_paper_mm", output["paper_mm"])
            source_w, source_h = task["paper_mm"]
            lines = [source, f"设备　{self.printer_display_name(caps['name'])}", f"驱动　{caps.get('driver_name') or '未提供名称'}",
                     f"原版面　{source_w:g} × {source_h:g} mm",
                     f"请求纸张　{paper_orientation_label(requested)} · {requested[0]:g} × {requested[1]:g} mm"]
            dx, dy = caps["logpixels_x"], caps["logpixels_y"]
            if min(dx, dy) > 0:
                pw, ph = caps["physical_width"], caps["physical_height"]
                ox, oy = caps["offset_x"], caps["offset_y"]
                left, right = ox * 25.4 / dx, (pw - ox - caps["horzres"]) * 25.4 / dx
                top, bottom = oy * 25.4 / dy, (ph - oy - caps["vertres"]) * 25.4 / dy
                actual = (pw*25.4/dx, ph*25.4/dy)
                lines.extend([f"驱动页面　{paper_orientation_label(actual)} · {actual[0]:.2f} × {actual[1]:.2f} mm",
                              f"硬边距　左 {left:.2f}　右 {right:.2f}　上 {top:.2f}　下 {bottom:.2f} mm"])
                if max(left, right, top, bottom) <= 0.1:
                    lines.append("驱动报告整页可打印。若实体照片的边缘被裁去，可检查驱动的无边距扩展设置。")
            plan = caps["_placements"].get(id(task))
            if plan:
                requested_rotation = output.get("_output_rotation_degrees", 0)
                driver_rotation = 90 if plan.rotate_clockwise else 0
                total_rotation = (requested_rotation + driver_rotation) % 360
                lines.extend([f"版面方向　相对原版面顺时针 {total_rotation}°"
                              f"（方向选择 {requested_rotation}°，驱动适配 {driver_rotation}°）",
                              f"软件排版比例　{plan.scale:.2%}"])
            driver_scale = caps.get("driver_scale_percent")
            lines.append(f"驱动公共缩放　{driver_scale}%" if driver_scale is not None else "驱动公共缩放　未公开")
            lines.append("无边距扩展等私有设置以打印机页面设置窗口为准，软件排版比例不代表这些设置已关闭。")
            if caps.get("paper_setup_warning"):
                warnings.insert(0, caps["paper_setup_warning"])
            lines.extend(["", *errors, *warnings] if errors or warnings else ["", "当前版面与驱动的纸型、可打印范围匹配。"])
            report = "\n".join(lines)
            self.status_var.set("已检查驱动定位，未提交打印")
            messagebox.showinfo("打印定位检查 · 不出纸", report)
            return report
        finally:
            self.close_system_print_context(dc, cleanup)

    def single_print_current(self):
        task, errors = self.previewed_print_task()
        if task is None:
            if not errors:
                errors = ["请先导入两张照片或载入演示素材"]
            messagebox.showerror("单独打印校验失败", "\n".join(errors))
            self.status_var.set("单独打印校验失败")
            return

        printer_info, printer_dc, cleanup = self.prepare_print_context([task], "单独打印")
        if printer_info is None:
            return

        try:
            self.print_tasks_with_win32([task], printer_info, printer_dc=printer_dc)
            messagebox.showinfo("单独打印已提交", "当前版面已提交到打印机。")
            self.status_var.set("单独打印已提交")
        except Exception as e:
            messagebox.showerror("单独打印失败", str(e))
            self.status_var.set("单独打印失败")
        finally:
            self.close_system_print_context(printer_dc, cleanup)


    def batch_print_queue(self):
        return self.dispatch_queue_tasks(list(self.batch_tasks))

    def print_image(self):
        self.single_print_current()


