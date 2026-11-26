"""Application-owned entry point for persistent printer page preferences."""
import tkinter as tk
from tkinter import messagebox

from .print_orientation import paper_orientation_label
from .specifications import PRINT_METHOD_DIRECT, THEME


class PageSettingsMixin:
    def make_page_settings_entry(self, parent):
        self.make_button(parent, "打印机页面设置…", self.open_page_settings,
                         "secondary", compact=True).pack(fill=tk.X, pady=(6, 0))
        self.page_settings_summary_var = tk.StringVar(master=self.root)
        tk.Label(parent, textvariable=self.page_settings_summary_var, bg=THEME["panel"],
                 fg=THEME["muted"], wraplength=260, justify=tk.LEFT, anchor=tk.W,
                 font=("Microsoft YaHei UI", 9)).pack(fill=tk.X, pady=(4, 0))
        for variable in (self.selected_printer_name, self.paper_orientation):
            variable.trace_add("write", lambda *_: self.refresh_page_settings_summary())
        self.refresh_page_settings_summary()

    def page_profile_summary(self, target):
        try:
            profile = self.get_driver_page_profile(target.printer, target.paper_mm)
        except ValueError:
            return "保存的设置需要重新确认"
        return "已保存，打印时自动载入" if profile is not None else "尚未保存，点击上方设置"

    def refresh_page_settings_summary(self):
        variable = getattr(self, "page_settings_summary_var", None)
        if variable is None:
            return
        target = self.calibration_target()
        if not target.printer:
            variable.set("选择打印机后，可保存页面布局和纸张类型")
            return
        w, h = target.paper_mm
        variable.set(f"{w:g} × {h:g} mm · {self.page_profile_summary(target)}")

    def configure_page_profile(self, target, owner):
        """Save the profile and direct-print preference together; Cancel changes neither."""
        previous_method = self.print_method.get()
        self.print_method.set(PRINT_METHOD_DIRECT)
        try:
            saved = self.edit_printer_page_settings(target=target, owner=owner)
        except Exception as error:
            self.print_method.set(previous_method)
            messagebox.showerror("页面设置未保存", str(error), parent=owner)
            return False
        if not saved:
            self.print_method.set(previous_method)
            self.status_var.set("已取消页面设置，原设置保持不变")
            return False
        self.refresh_page_settings_summary()
        self.status_var.set("页面设置已保存，后续直接打印将自动沿用")
        return True

    def reset_page_profile(self, target, owner):
        try:
            removed = self.reset_driver_page_profile(target.printer, target.paper_mm)
        except (OSError, ValueError) as error:
            messagebox.showerror("无法恢复默认设置", str(error), parent=owner)
            return False
        self.refresh_page_settings_summary()
        self.status_var.set("此纸型已恢复使用打印机默认设置" if removed else "此纸型尚未保存页面设置")
        return removed

    def open_page_settings(self):
        existing = getattr(self, "page_settings_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        self.refresh_printer_list(show_status=False, save=False)
        target = self.calibration_target()
        if not target.printer or target.printer not in self.printer_names:
            messagebox.showwarning("请选择打印机", "请先连接并选择需要设置的打印机。", parent=self.root)
            return
        window = tk.Toplevel(self.root)
        self.page_settings_window = window
        window.title("打印机页面设置")
        window.configure(bg=THEME["panel"])
        window.transient(self.root)
        window.resizable(False, False)
        content = tk.Frame(window, bg=THEME["panel"])
        content.pack(fill=tk.BOTH, expand=True, padx=22, pady=20)
        tk.Label(content, text="设置一次，后续打印自动沿用", bg=THEME["panel"],
                 fg=THEME["text"], font=("Microsoft YaHei UI", 15, "bold")).pack(anchor=tk.W)
        w, h = target.paper_mm
        tk.Label(content, text=f"打印机：{self.printer_display_name(target.printer)}\n"
                 f"相纸：{w:g} × {h:g} mm · {paper_orientation_label(target.paper_mm)}",
                 bg=THEME["panel"], fg=THEME["text"], wraplength=490, justify=tk.LEFT,
                 font=("Microsoft YaHei UI", 11)).pack(fill=tk.X, pady=(16, 8))
        summary = tk.StringVar(master=window, value=self.page_profile_summary(target))
        tk.Label(content, textvariable=summary, bg=THEME["panel"], fg=THEME["accent"],
                 wraplength=490, justify=tk.LEFT, font=("Microsoft YaHei UI", 10)).pack(fill=tk.X)
        tk.Label(content, text="点击下方按钮，在当前打印机的设置中选择页面布局、无边距、扩展量、纸张类型及打印质量。可用选项由打印机提供。\n\n"
                 "在打印机窗口点“确定”后，本软件会保存这些设置并切换为直接打印。换纸张规格或横竖方向时，可分别设置。",
                 bg=THEME["panel"], fg=THEME["muted"], wraplength=490, justify=tk.LEFT,
                 font=("Microsoft YaHei UI", 10)).pack(fill=tk.X, pady=16)
        tk.Label(content, text="精确留白提示：Canon G500 使用无边距时，将“扩展量”拉到最左端；避免使用“按页面大小”自动缩放。",
                 bg=THEME["card"], fg=THEME["warning"], wraplength=466, justify=tk.LEFT,
                 padx=12, pady=10, font=("Microsoft YaHei UI", 10)).pack(fill=tk.X, pady=(0, 16))

        def edit():
            if self.configure_page_profile(target, window):
                summary.set("已保存 · 后续直接打印自动沿用")
            else:
                summary.set(self.page_profile_summary(target))
            window.grab_set()

        def reset():
            self.reset_page_profile(target, window)
            summary.set(self.page_profile_summary(target))

        self.make_button(content, "设置页面布局并保存…", edit, "primary").pack(fill=tk.X)
        row = tk.Frame(content, bg=THEME["panel"])
        row.pack(fill=tk.X, pady=(10, 0))
        self.make_button(row, "恢复此纸型默认设置", reset, "secondary", compact=True).pack(side=tk.LEFT)

        def close():
            window.grab_release()
            window.destroy()
            self.page_settings_window = None

        self.make_button(row, "关闭", close, "secondary", compact=True).pack(side=tk.RIGHT)
        window.protocol("WM_DELETE_WINDOW", close)
        window.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width()-window.winfo_width())//2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height()-window.winfo_height())//2)
        window.geometry(f"+{x}+{y}")
        window.grab_set()

