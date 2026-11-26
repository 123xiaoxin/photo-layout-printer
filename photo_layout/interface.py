"""Desktop controls and application layout."""
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, simpledialog, ttk
from PIL import Image
from PIL import ImageTk
from .specifications import FIT_MODE_OPTIONS, LAYOUT_OPTIONS, PRINT_METHOD_OPTIONS, THEME
from .print_orientation import PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_OPTIONS, orient_paper_size

class BatchList(tk.Frame):
    """Scrollable batch previews with the selection API used by the queue."""
    def __init__(self, parent, on_select, on_check):
        super().__init__(parent, bg=THEME["panel"])
        self.on_select = on_select
        self.on_check = on_check
        self.selected = None
        self.rows = []
        self.images = []
        self.canvas = tk.Canvas(self, width=1, height=1, bg=THEME["panel"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.content = tk.Frame(self.canvas, bg=THEME["panel"])
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def curselection(self):
        return () if self.selected is None else (self.selected,)

    def selection_clear(self, *_args):
        self.selected = None
        self._paint()

    def selection_set(self, index):
        if index == tk.END:
            index = len(self.rows) - 1
        self.selected = int(index) if 0 <= int(index) < len(self.rows) else None
        self._paint()

    def activate(self, _index):
        if self.selected is None:
            return
        self.update_idletasks()
        row = self.rows[self.selected]
        height = max(1, self.content.winfo_height())
        start = row.winfo_y()
        end = start + row.winfo_height()
        top = self.canvas.canvasy(0)
        visible_height = self.canvas.winfo_height()
        if start < top:
            self.canvas.yview_moveto(start / height)
        elif end > top + visible_height:
            self.canvas.yview_moveto(max(0, end - visible_height) / height)

    def delete(self, *_args):
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.images.clear()
        self.selected = None

    def add_task(self, task, index, sources):
        row = tk.Frame(self.content, bg=THEME["panel"], cursor="hand2")
        row.pack(fill=tk.X, pady=(0, 2))
        checked = tk.BooleanVar(master=row, value=task.get("checked_for_print", False))
        def mark():
            task["checked_for_print"] = checked.get()
            self.on_check()
        tk.Checkbutton(row, variable=checked, command=mark, bg=THEME["panel"],
                       selectcolor=THEME["card_soft"], fg=THEME["accent"],
                       activebackground=THEME["panel"], takefocus=True).pack(side=tk.LEFT)
        preview = task["preview_image"].copy()
        preview.thumbnail((70, 88), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(preview)
        self.images.append(photo)
        thumb = tk.Label(row, image=photo, bg=THEME["panel"], padx=8, pady=8)
        thumb.pack(side=tk.LEFT)
        details = tk.Frame(row, bg=THEME["panel"])
        details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 4), pady=8)
        title = tk.Label(details, text=f"批次 {index + 1:03d}   ·   {task['layout']}", bg=THEME["panel"], fg=THEME["text"], anchor="w", font=("Microsoft YaHei UI", 10, "bold"))
        title.pack(fill=tk.X)
        names = tk.Label(details, text=sources, bg=THEME["panel"], fg=THEME["muted"], anchor="w", wraplength=175, justify=tk.LEFT, font=("Microsoft YaHei UI", 9))
        names.pack(fill=tk.X, pady=(5, 3))
        ok = task.get("validation", {}).get("ok", False)
        status = tk.Label(details, text="校验通过 · 待打印" if ok else "需要检查", bg=THEME["panel"], fg=THEME["accent"] if ok else THEME["warning"], anchor="w", font=("Microsoft YaHei UI", 9))
        status.pack(fill=tk.X)
        self.rows.append(row)
        for widget in (row, thumb, details, title, names, status):
            widget.bind("<Button-1>", lambda e, i=index: self._choose(i))

    def _choose(self, index):
        self.selection_set(index)
        self.on_select()

    def _paint(self):
        def paint(widget, color):
            try:
                widget.configure(bg=color)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                paint(child, color)
        for index, row in enumerate(self.rows):
            paint(row, "#293c22" if index == self.selected else THEME["panel"])


class InterfaceMixin:
    """Behavior used by the application controller."""
    def rename_selected_printer(self):
        queue = self.selected_printer_name.get()
        if not queue:
            messagebox.showinfo("打印机命名", "请先选择一台打印机。", parent=self.root)
            return
        alias = simpledialog.askstring(
            "打印机命名", f"Windows 打印机：{queue}\n在本工具中显示的名称（留空恢复系统名称）：",
            initialvalue=self.printer_alias_for(queue), parent=self.root)
        if alias is None:
            return
        try:
            self.set_printer_alias(queue, alias)
        except (ValueError, OSError) as error:
            messagebox.showerror("无法保存打印机名称", str(error), parent=self.root)
            return
        self.sync_printer_selector()
        self.status_var.set(f"打印机名称已更新：{self.printer_display_name(queue)}")

    def configure_theme(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Merchant.TCombobox",
            fieldbackground=THEME["card_soft"],
            background=THEME["card_soft"],
            foreground=THEME["text"],
            bordercolor=THEME["border"],
            arrowcolor=THEME["accent"],
            padding=6,
        )
        style.map(
            "Merchant.TCombobox",
            fieldbackground=[("readonly", THEME["card_soft"])],
            foreground=[("readonly", THEME["text"])],
        )


    def make_panel(self, parent, **grid):
        frame = tk.Frame(parent, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        if grid:
            frame.grid(**grid)
        return frame


    def make_button(self, parent, text, command, kind="secondary", width=None, compact=False):
        colors = {
            "primary": (THEME["accent"], "#101510", "#c8f66f"),
            "blue": (THEME["accent_2"], THEME["text"], "#1f68d9"),
            "danger": (THEME["danger"], "#101010", "#e45858"),
            "secondary": (THEME["card_soft"], THEME["text"], "#2b3329"),
        }
        bg, fg, active = colors[kind]
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            bd=0,
            relief=tk.FLAT,
            padx=10 if compact else 14,
            pady=4 if compact else 8,
            width=width,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9 if compact else 10, "bold"),
        )
        return btn


    def make_section_title(self, parent, title, subtitle=None):
        tk.Label(parent, text=title, bg=THEME["panel"], fg=THEME["text"], font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        if subtitle:
            tk.Label(parent, text=subtitle, bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, pady=(3, 0))


    def make_photo_adjust_controls(self, parent):
        self.make_section_title(parent, "照片微调", "单张旋转与位置偏移")
        adjust = tk.Frame(parent, bg=THEME["panel"])
        adjust.pack(fill=tk.X, pady=(8, 4))
        for idx in range(2):
            row = tk.Frame(adjust, bg=THEME["panel"])
            row.pack(fill=tk.X, pady=(2, 2))
            tk.Label(row, text=f"照片 {idx + 1}", bg=THEME["panel"], fg=THEME["text"], font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT)
            rotate = self.make_button(row, "旋转", lambda i=idx: self.rotate_photo(i), "secondary", compact=True)
            self.register_photo_edit_control(rotate, idx)
            rotate.pack(side=tk.RIGHT)
            nudge = tk.Frame(adjust, bg=THEME["panel"])
            nudge.pack(fill=tk.X, pady=(0, 6))
            for text, dx, dy in [("左", -5, 0), ("右", 5, 0), ("上", 0, -5), ("下", 0, 5)]:
                button = self.make_button(nudge, text, lambda i=idx, x=dx, y=dy: self.move_photo(i, x, y), "secondary", compact=True)
                self.register_photo_edit_control(button, idx)
                button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        utility = tk.Frame(parent, bg=THEME["panel"])
        utility.pack(fill=tk.X, pady=(2, 0))
        reset = self.make_button(utility, "复位", self.reset_all, "secondary", compact=True)
        self.register_photo_edit_control(reset)
        reset.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.make_button(utility, "清空照片", self.clear_all, "danger", compact=True).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))


    def make_advanced_calibration_controls(self, parent, target):
        active_target = replace(target, paper_mm=tuple(orient_paper_size(target.paper_mm, self.paper_orientation.get())))
        self.calibration_active_target = active_target
        self.make_section_title(parent, "十字刻度与打印校准")
        details = tk.StringVar(parent)
        tk.Label(parent, textvariable=details, bg=THEME["panel"], fg=THEME["muted"],
                 font=("Microsoft YaHei UI", 9), wraplength=330, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 10))
        tk.Label(parent, text="相纸放置方向", bg=THEME["panel"], fg=THEME["text"],
                 font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(0, 5))
        self.calibration_orientation_combo = ttk.Combobox(parent, textvariable=self.paper_orientation,
            values=PAPER_ORIENTATION_OPTIONS, state="readonly", style="Merchant.TCombobox")
        self.calibration_orientation_combo.pack(fill=tk.X)
        tk.Label(parent, text="此选择也用于正式照片打印。纵向短边在上，横向长边在上；进纸方式按纸盒要求。",
                 bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 9),
                 wraplength=330, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 6))
        x, y = self.calibration_offsets_for(active_target.printer, active_target.layout, active_target.paper_mm)
        shift_x, shift_y = tk.DoubleVar(parent, x), tk.DoubleVar(parent, y)
        self.calibration_shift_x, self.calibration_shift_y = shift_x, shift_y

        def refresh_chart():
            self.calibration_preview_image = self.make_calibration_chart(active_target)
            self.draw_calibration_preview()

        def refresh_target(_event=None):
            nonlocal active_target
            if _event is not None:
                self.on_paper_orientation_changed()
            active_target = replace(target, paper_mm=tuple(orient_paper_size(target.paper_mm, self.paper_orientation.get())))
            self.calibration_active_target = active_target
            width, height = active_target.paper_mm
            direction = "横向" if width > height else "纵向"
            details.set(f"{self.printer_display_name(target.printer) or '未选择打印机'}\n"
                        f"{target.layout} · {width:g} × {height:g} mm · {direction} · {target.dpi} DPI")
            x, y = self.calibration_offsets_for(active_target.printer, active_target.layout, active_target.paper_mm)
            x_slider.set(x)
            y_slider.set(y)
            refresh_chart()

        self.calibration_orientation_combo.bind("<<ComboboxSelected>>", refresh_target)

        def save():
            previous = self.calibration_offsets_for(active_target.printer, active_target.layout, active_target.paper_mm)
            requested = (shift_x.get(), shift_y.get())
            if requested == previous:
                return
            try:
                self.save_paper_offsets(active_target.printer, active_target.paper_mm, *requested)
            except OSError as error:
                # Scale.set also refreshes the value labels on the next UI callback.
                # The unchanged-value check prevents those callbacks from saving again.
                x_slider.set(previous[0])
                y_slider.set(previous[1])
                self.status_var.set("校准未保存，已恢复原来的补偿值")
                messagebox.showerror("无法保存打印校准", f"已恢复原来的补偿值。\n\n{error}",
                                     parent=parent.winfo_toplevel())
            refresh_chart()

        def reset():
            x_slider.set(0)
            y_slider.set(0)
            save()
        tk.Label(
            parent,
            text="这里移动的是最终打印画面，不会改变照片在版面里的排版。正数向右/向下，负数向左/向上。",
            bg=THEME["card"],
            fg=THEME["muted"],
            justify=tk.LEFT,
            wraplength=360,
            padx=12,
            pady=10,
            font=("Microsoft YaHei UI", 9),
        ).pack(fill=tk.X, pady=(10, 8))
        print_chart = self.make_button(parent, "打印中心十字校准图", lambda: self.print_calibration_chart(active_target),
                                       "primary")
        print_chart.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            parent,
            text=("按 100% 原尺寸打印，先用实尺检查 20 mm 校验尺；测得不是 20 mm 时，先检查驱动缩放设置。\n\n"
                  "普通打印的轴线会被不可打印区截断，不要比较轴线端点。请从实际纸边量到灰色参考框的四边，"
                  "记录左距、右距、上距、下距。参考框设计上距纸张四边各 10 mm。\n\n"
                  "新 X＝当前 X＋（右距－左距）÷2\n"
                  "新 Y＝当前 Y＋（下距－上距）÷2\n"
                  "以上距离和补偿均用 mm；纵向、横向分别校准并保存。"),
            bg=THEME["panel"],
            fg=THEME["muted"],
            justify=tk.LEFT,
            wraplength=360,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor=tk.W, pady=(0, 10))
        x_slider = self.make_slider(parent, "整张画面左右微调", shift_x, -10, 10, 0.1, save)
        y_slider = self.make_slider(parent, "整张画面上下微调", shift_y, -10, 10, 0.1, save)
        self.calibration_x_slider, self.calibration_y_slider = x_slider, y_slider
        reset_button = self.make_button(parent, "重置打印画面微调", reset, "secondary")
        reset_button.pack(fill=tk.X, pady=(8, 4))
        if not target.printer:
            for control in (print_chart, x_slider, y_slider, reset_button):
                control.configure(state=tk.DISABLED)
        self.make_section_title(parent, "当前编辑版面设置")
        self.make_slider(parent, "中缝留白", self.middle_margin_mm, 0, 8, 0.5, lambda: self.on_settings_changed(reprocess=True))
        tk.Label(parent, text="辅助选项", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(14, 6))
        self.make_check(parent, "启用边部留白", self.enable_margin, lambda: self.on_settings_changed(reprocess=True)).pack(anchor=tk.W, pady=2)
        self.make_check(parent, "智能横竖旋转", self.auto_rotate, lambda: self.on_settings_changed(reprocess=True)).pack(anchor=tk.W, pady=2)
        self.make_check(parent, "预览安全线", self.show_guides, lambda: self.on_settings_changed(reprocess=False)).pack(anchor=tk.W, pady=2)
        self.make_check(parent, "打印裁切标记", self.draw_cut_line, lambda: self.on_settings_changed(reprocess=False)).pack(anchor=tk.W, pady=2)
        self.sync_photo_edit_controls()
        refresh_target()


    def draw_calibration_preview(self, _event=None):
        canvas = getattr(self, "calibration_preview_canvas", None)
        source = getattr(self, "calibration_preview_image", None)
        if canvas is None or source is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if min(width, height) <= 1:
            return
        preview = source.copy()
        preview.thumbnail((max(1, width - 24), max(1, height - 24)), Image.Resampling.LANCZOS)
        self.calibration_preview_tk = ImageTk.PhotoImage(preview)
        canvas.create_image(width // 2, height // 2, image=self.calibration_preview_tk)


    def make_check(self, parent, text, variable, command):
        check = tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=THEME["panel"],
            fg=THEME["text"],
            selectcolor=THEME["card"],
            activebackground=THEME["panel"],
            activeforeground=THEME["accent"],
            bd=0,
            font=("Microsoft YaHei UI", 10),
        )
        if any(variable is getattr(self, name) for name in
               ("enable_margin", "auto_rotate", "show_guides", "draw_cut_line")):
            self.register_photo_edit_control(check)
        return check

    def register_photo_edit_control(self, control, photo_index=None, enabled_state=tk.NORMAL):
        if not hasattr(self, "_photo_edit_controls"):
            self._photo_edit_controls = []
        self._photo_edit_controls.append((control, photo_index, enabled_state))

    def sync_photo_edit_controls(self):
        editable = self.page_editor_available()
        count = self.get_layout_base()["slot_count"]
        live = []
        for control, index, enabled_state in getattr(self, "_photo_edit_controls", []):
            if control.winfo_exists():
                enabled = editable and (index is None or index < count)
                control.configure(state=enabled_state if enabled else tk.DISABLED)
                live.append((control, index, enabled_state))
        self._photo_edit_controls = live


    def make_slider(self, parent, label, variable, from_, to, resolution, command):
        row = tk.Frame(parent, bg=THEME["panel"])
        row.pack(fill=tk.X, pady=(8, 2))
        value_label = tk.Label(row, text="", bg=THEME["panel"], fg=THEME["accent"], font=("Microsoft YaHei UI", 10, "bold"))
        tk.Label(row, text=label, bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        value_label.pack(side=tk.RIGHT)

        last_command_value = variable.get()

        def update_value(*_args):
            nonlocal last_command_value
            value_label.config(text=f"{variable.get():.1f} mm")
            if getattr(self, "_restoring_task_editor", False):
                last_command_value = variable.get()

        def changed(_value):
            nonlocal last_command_value
            value = variable.get()
            update_value()
            if value != last_command_value:
                last_command_value = value
                command()

        scale = tk.Scale(
            parent,
            from_=from_,
            to=to,
            resolution=resolution,
            orient=tk.HORIZONTAL,
            variable=variable,
            command=changed,
            bg=THEME["panel"],
            fg=THEME["muted"],
            troughcolor=THEME["card_soft"],
            activebackground=THEME["accent"],
            highlightthickness=0,
            bd=0,
            sliderrelief=tk.FLAT,
        )
        scale.pack(fill=tk.X)
        trace = variable.trace_add("write", update_value)
        scale.bind("<Destroy>", lambda e: variable.trace_remove("write", trace) if e.widget is scale else None, add="+")
        scale.value_label = value_label
        update_value()
        if variable is self.margin_mm or variable is self.middle_margin_mm:
            self.register_photo_edit_control(scale)
        return scale


    def setup_ui(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self.root, bg=THEME["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header.grid_columnconfigure(1, weight=1)

        brand = tk.Frame(header, bg=THEME["bg"])
        brand.grid(row=0, column=0, sticky="w")
        tk.Label(brand, text="Merchant", bg=THEME["bg"], fg=THEME["text"], font=("Segoe UI", 28)).pack(side=tk.LEFT)
        tk.Label(brand, text=" Pro", bg=THEME["bg"], fg=THEME["accent"], font=("Segoe UI", 28)).pack(side=tk.LEFT)
        tk.Label(brand, text="  商用照片排版工作台", bg=THEME["bg"], fg=THEME["muted"], font=("Microsoft YaHei UI", 11)).pack(side=tk.LEFT, padx=(10, 0), pady=(10, 0))

        toolbar = tk.Frame(header, bg=THEME["bg"])
        toolbar.grid(row=0, column=1, sticky="e")
        self.make_button(toolbar, "载入演示照片", self.load_demo_images, "secondary").pack(side=tk.LEFT, padx=(0, 8))
        from .collage import open_collage_editor
        self.make_button(toolbar, "多照片拼版", lambda: open_collage_editor(self), "primary").pack(side=tk.LEFT, padx=(0, 8))
        self.make_button(toolbar, "清空队列", self.clear_queue, "secondary").pack(side=tk.LEFT, padx=(0, 8))
        self.make_button(toolbar, "打印预览页", self.single_print_current, "secondary").pack(side=tk.LEFT, padx=(0, 8))
        self.make_button(toolbar, "高级校准", self.open_advanced_calibration, "secondary").pack(side=tk.LEFT, padx=(0, 8))

        body = tk.Frame(self.root, bg=THEME["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = self.make_panel(body, row=0, column=2, sticky="ns", padx=(12, 0))
        left.configure(width=310)
        left.pack_propagate(False)
        settings_footer = tk.Frame(left, bg=THEME["panel"])
        settings_footer.pack(side=tk.BOTTOM, fill=tk.X, padx=18, pady=(4, 18))
        self.make_button(settings_footer, "打印全部", self.batch_print_queue, "secondary", compact=True).pack(fill=tk.X, pady=(0, 4))
        self.print_checked_button = self.make_button(settings_footer, "打印勾选页", self.print_checked_sheets, "primary")
        self.print_checked_button.pack(fill=tk.X)
        self.update_checked_button()
        settings_area = tk.Frame(left, bg=THEME["panel"])
        settings_area.pack(fill=tk.BOTH, expand=True, padx=(18, 6), pady=(18, 0))
        settings_canvas = tk.Canvas(settings_area, bg=THEME["panel"], highlightthickness=0, bd=0)
        settings_scroll = ttk.Scrollbar(settings_area, orient=tk.VERTICAL, command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_inner = tk.Frame(settings_canvas, bg=THEME["panel"])
        settings_window = settings_canvas.create_window((0, 0), window=left_inner, anchor="nw")
        left_inner.bind("<Configure>", lambda e: settings_canvas.configure(scrollregion=settings_canvas.bbox("all")))
        settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfigure(settings_window, width=e.width))
        def scroll_settings(event):
            settings_canvas.yview_scroll(int(-event.delta / 120), "units")
        def bind_scroll(widget):
            widget.bind("<MouseWheel>", scroll_settings, add="+")
            for child in widget.winfo_children():
                bind_scroll(child)

        self.make_section_title(left_inner, "排版与打印设置", "选择规格、适配方式与打印机")
        tk.Label(left_inner, text="纸张与照片规格", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(18, 6))
        layout_combo = ttk.Combobox(left_inner, textvariable=self.layout_mode, values=list(LAYOUT_OPTIONS.keys()), state="readonly", style="Merchant.TCombobox")
        layout_combo.pack(fill=tk.X)
        layout_combo.bind("<<ComboboxSelected>>", lambda e: self.on_layout_changed())

        dpi_row = tk.Frame(left_inner, bg=THEME["panel"])
        dpi_row.pack(fill=tk.X, pady=(14, 2))
        tk.Label(dpi_row, text="输出 DPI", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        dpi_box = ttk.Combobox(dpi_row, textvariable=self.dpi, values=[300, 600], state="readonly", width=8, style="Merchant.TCombobox")
        dpi_box.pack(side=tk.RIGHT)
        dpi_box.bind("<<ComboboxSelected>>", lambda e: self.on_settings_changed(reprocess=True))
        self.register_photo_edit_control(dpi_box, enabled_state="readonly")

        printer_header = tk.Frame(left_inner, bg=THEME["panel"])
        printer_header.pack(fill=tk.X, pady=(14, 6))
        tk.Label(printer_header, text="打印机", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.make_button(printer_header, "刷新", self.refresh_printer_list, "secondary", compact=True).pack(side=tk.RIGHT)
        self.make_button(printer_header, "命名", self.rename_selected_printer, "secondary", compact=True).pack(side=tk.RIGHT, padx=4)
        self.printer_combo = ttk.Combobox(
            left_inner,
            postcommand=lambda: self.refresh_printer_list(show_status=False, save=False),
            state="readonly" if self.printer_names else "disabled",
            style="Merchant.TCombobox",
        )
        self.printer_combo.pack(fill=tk.X)
        self.sync_printer_selector()
        self.printer_combo.bind("<<ComboboxSelected>>", self.select_displayed_printer)
        self.make_check(left_inner, "跟随 Windows 默认打印机", self.follow_system_printer,
                        self.on_follow_system_printer_changed).pack(anchor=tk.W, pady=(4, 0))
        self.make_page_settings_entry(left_inner)
        self.make_button(left_inner, "检查本页打印定位", self.inspect_preview_printer_placement,
                         "secondary", compact=True).pack(fill=tk.X, pady=(4, 0))

        tk.Label(left_inner, text="打印方式", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(14, 6))
        print_method_combo = ttk.Combobox(
            left_inner,
            textvariable=self.print_method,
            values=PRINT_METHOD_OPTIONS,
            state="readonly",
            style="Merchant.TCombobox",
        )
        print_method_combo.pack(fill=tk.X)
        print_method_combo.bind("<<ComboboxSelected>>", self.on_print_method_changed)

        tk.Label(left_inner, text="相纸放置方向", bg=THEME["panel"], fg=THEME["muted"],
                 font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(14, 6))
        self.paper_orientation_combo = ttk.Combobox(left_inner, textvariable=self.paper_orientation,
            values=PAPER_ORIENTATION_OPTIONS, state="readonly", style="Merchant.TCombobox")
        self.paper_orientation_combo.pack(fill=tk.X)
        self.paper_orientation_combo.bind("<<ComboboxSelected>>", self.on_paper_orientation_changed)
        tk.Label(left_inner, text="纵向短边在上，横向长边在上；进纸方式按打印机纸盒要求。",
                 bg=THEME["panel"], fg=THEME["muted"], wraplength=260, justify=tk.LEFT,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, pady=(4, 0))

        tk.Label(left_inner, text="排版设置统一应用全部照片组\n多照片拼版单独设置；旋转 / 微调仅当前组",
                 bg=THEME["panel"], fg=THEME["muted"], justify=tk.LEFT, wraplength=260,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, pady=(12, 0))
        self.margin_slider = self.make_slider(left_inner, "边部留白", self.margin_mm, 0, 10, 0.5, lambda: self.on_settings_changed(reprocess=True))

        tk.Label(left_inner, text="照片适配", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(14, 6))
        fit_combo = ttk.Combobox(left_inner, textvariable=self.fit_mode, values=FIT_MODE_OPTIONS, state="readonly", style="Merchant.TCombobox")
        fit_combo.pack(fill=tk.X)
        fit_combo.bind("<<ComboboxSelected>>", lambda e: self.on_fit_mode_changed())
        self.register_photo_edit_control(fit_combo, enabled_state="readonly")

        self.photo_adjust_frame = tk.Frame(left_inner, bg=THEME["panel"])
        self.photo_adjust_frame.pack(fill=tk.X, pady=(14, 0))
        self.make_photo_adjust_controls(self.photo_adjust_frame)
        bind_scroll(left_inner)

        center = self.make_panel(body, row=0, column=1, sticky="nsew")
        center.grid_rowconfigure(2, weight=1)
        center.grid_columnconfigure(0, weight=1)

        flow = tk.Frame(center, bg=THEME["panel"])
        # Retain the flow indicators for status updates without taking preview space.
        flow.grid(row=0, column=0, sticky="ew")
        flow.grid_remove()
        flow.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.flow_labels = []
        for idx, (title, subtitle) in enumerate([
            ("01 导入照片", "JPG / PNG / WEBP"),
            ("02 设置规格", "纸张、DPI、边距"),
            ("03 预览校准", "安全线与位置"),
            ("04 打印输出", "校验后提交"),
        ]):
            card = tk.Frame(flow, bg=THEME["card"], highlightbackground=THEME["border"], highlightthickness=1)
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 8, 0))
            title_label = tk.Label(card, text=title, bg=THEME["card"], fg=THEME["accent"], font=("Microsoft YaHei UI", 10, "bold"))
            title_label.pack(anchor=tk.W, padx=10, pady=(7, 1))
            tk.Label(card, text=subtitle, bg=THEME["card"], fg=THEME["muted"], font=("Microsoft YaHei UI", 8)).pack(anchor=tk.W, padx=10, pady=(0, 7))
            self.flow_labels.append(title_label)

        preview_header = tk.Frame(center, bg=THEME["panel"])
        preview_header.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        preview_header.grid_columnconfigure(1, weight=1)
        tk.Label(preview_header, text="排版预览", bg=THEME["panel"], fg=THEME["text"], font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, sticky=tk.W)
        tk.Label(preview_header, textvariable=self.canvas_status_var, bg=THEME["card"], fg=THEME["accent"], font=("Microsoft YaHei UI", 9), padx=10, pady=5).grid(row=0, column=1, sticky="e")

        preview_wrap = tk.Frame(center, bg=THEME["panel"])
        preview_wrap.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 12))
        preview_wrap.grid_rowconfigure(0, weight=1)
        preview_wrap.grid_columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(preview_wrap, bg=THEME["bg"], highlightthickness=0, bd=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.schedule_preview_update)
        self.preview_canvas.bind("<Destroy>", self.cancel_preview_update)

        tk.Label(center, text="当前照片", bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=3, column=0, sticky="w", padx=18, pady=(0, 6))
        slots = tk.Frame(center, bg=THEME["panel"])
        slots.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 14))
        slots.grid_columnconfigure((0, 1), weight=1)
        self.drop1_frame = self.make_photo_slot(slots, 0)
        self.drop1_frame.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.drop2_frame = self.make_photo_slot(slots, 1)
        self.drop2_frame.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        right = self.make_panel(body, row=0, column=0, sticky="ns", padx=(0, 12))
        right.configure(width=330)
        right.pack_propagate(False)
        right_inner = tk.Frame(right, bg=THEME["panel"])
        right_inner.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        self.make_button(right_inner, "批量导入", self.select_files_batch, "primary").pack(fill=tk.X, pady=(0, 16))
        self.make_section_title(right_inner, "打印批次", "点击照片预览，勾选方框指定打印页")
        tk.Label(
            right_inner,
            textvariable=self.queue_summary_var,
            bg=THEME["card"],
            fg=THEME["text"],
            anchor=tk.W,
            padx=10,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(fill=tk.X, pady=(10, 0))
        marks = tk.Frame(right_inner, bg=THEME["panel"])
        marks.pack(fill=tk.X)
        for caption, value in (("全选", True), ("取消勾选", False)):
            self.make_button(marks, caption, lambda v=value: self.check_all_sheets(v),
                             compact=True).pack(side=tk.LEFT, padx=(0, 6))
        self.task_listbox = BatchList(right_inner, self.preview_selected_task, self.update_checked_button)
        self.task_listbox.pack(fill=tk.BOTH, expand=True, pady=(8, 8), side=tk.BOTTOM)
        queue_buttons = tk.Frame(right_inner, bg=THEME["panel"])
        queue_buttons.pack(fill=tk.X)
        self.make_button(queue_buttons, "加入打印队列", self.add_task, "secondary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.make_button(queue_buttons, "移除", self.remove_selected_task, "secondary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.make_button(right_inner, "打印前检查", self.validate_batch_queue, "secondary").pack(fill=tk.X, pady=(8, 8))

        # Status variables are still updated by the existing validation logic.
        for key in ("import", "size", "dpi", "margin", "fit", "print_status"):
            self.metric_vars[key] = tk.StringVar(value="-")

        tk.Label(right_inner, text="问题检查", bg=THEME["panel"], fg=THEME["text"], font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(2, 4))
        tk.Label(
            right_inner,
            textvariable=self.issue_var,
            bg=THEME["card"],
            fg=THEME["muted"],
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=280,
            padx=10,
            pady=8,
            font=("Microsoft YaHei UI", 9),
        ).pack(fill=tk.X, pady=(0, 10))

        status = tk.Label(
            right_inner,
            textvariable=self.status_var,
            bg=THEME["panel"],
            fg=THEME["muted"],
            justify=tk.LEFT,
            wraplength=280,
            font=("Microsoft YaHei UI", 9),
        )
        status.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))

        self.task_listbox.pack_forget()
        self.task_listbox.pack(before=queue_buttons, fill=tk.BOTH, expand=True, pady=(8, 8))
        self.update_info_text(None)


    def make_photo_slot(self, parent, index):
        outer = tk.Frame(parent, bg=THEME["card"], highlightbackground=THEME["border"], highlightthickness=1)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(1, minsize=48)
        header = tk.Frame(outer, bg=THEME["card"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 2))
        tk.Label(header, text=f"图片 {index + 1}", bg=THEME["card"], fg=THEME["text"], font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT)
        state_var = tk.StringVar(value="等待导入")
        tk.Label(header, textvariable=state_var, bg=THEME["card"], fg=THEME["subtle"], font=("Microsoft YaHei UI", 8)).pack(side=tk.RIGHT)
        label = tk.Label(
            outer,
            text=f"拖入或选择照片 {index + 1}",
            bg=THEME["card_soft"],
            fg=THEME["muted"],
            justify=tk.CENTER,
            font=("Microsoft YaHei UI", 8),
            padx=10,
            pady=18,
        )
        label.grid(row=1, column=0, sticky="nsew", padx=(10, 8), pady=(0, 6))
        meta_var = tk.StringVar(value="未导入\n-\n未放入版面")
        meta_label = tk.Label(
            outer,
            textvariable=meta_var,
            bg=THEME["card"],
            fg=THEME["muted"],
            justify=tk.LEFT,
            anchor=tk.NW,
            font=("Microsoft YaHei UI", 8),
        )
        meta_label.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=(0, 5))
        button_row = tk.Frame(outer, bg=THEME["card"])
        button_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        replace_photo = self.make_button(button_row, "替换", lambda i=index: self.select_file(i), "secondary", compact=True)
        rotate_photo = self.make_button(button_row, "旋转", lambda i=index: self.rotate_photo(i), "secondary", compact=True)
        self.register_photo_edit_control(replace_photo, index)
        self.register_photo_edit_control(rotate_photo, index)
        replace_photo.pack(side=tk.LEFT)
        rotate_photo.pack(side=tk.LEFT, padx=(8, 0))
        name_var = tk.StringVar(value="未导入")
        tk.Label(button_row, textvariable=name_var, bg=THEME["card"], fg=THEME["subtle"], font=("Microsoft YaHei UI", 8)).pack(side=tk.RIGHT)
        if index == 0:
            self.drop1_label = label
            self.photo1_name_var = name_var
        else:
            self.drop2_label = label
            self.photo2_name_var = name_var
        self.photo_meta_vars[index] = meta_var
        self.photo_state_vars[index] = state_var
        return outer


    def open_advanced_calibration(self):
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            self.advanced_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.advanced_window = window
        window.title("高级打印校准")
        window.configure(bg=THEME["bg"])
        window.minsize(800, 540)
        window.geometry(f"{min(1020, self.root.winfo_screenwidth() - 60)}x{min(740, self.root.winfo_screenheight() - 100)}")
        window.transient(self.root)
        window.grab_set()

        body = tk.Frame(window, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        controls = tk.Frame(body, bg=THEME["panel"])
        controls.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll_canvas = tk.Canvas(controls, width=370, highlightthickness=0, bg=THEME["panel"])
        scrollbar = ttk.Scrollbar(controls, orient=tk.VERTICAL, command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(scroll_canvas, bg=THEME["panel"])
        inner_window = scroll_canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        inner.bind("<Configure>", lambda _e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>", lambda e: scroll_canvas.itemconfigure(inner_window, width=e.width))

        preview = tk.Frame(body, bg=THEME["panel"])
        preview.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        tk.Label(preview, text="校准图预览", bg=THEME["panel"], fg=THEME["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 8))
        self.calibration_preview_canvas = tk.Canvas(preview, highlightthickness=0, bg=THEME["bg"])
        self.calibration_preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.calibration_preview_canvas.bind("<Configure>", self.draw_calibration_preview)
        tk.Label(preview, text="每小格 1 mm · 红十字为纸张中心\n灰色参考框设计距纸张四边各 10 mm\n测量时从实际纸边量起\n预览随窗口缩放，打印刻度保持实际毫米尺寸",
                 bg=THEME["panel"], fg=THEME["muted"], font=("Microsoft YaHei UI", 9),
                 justify=tk.LEFT).pack(anchor=tk.W, pady=(8, 0))
        self.make_advanced_calibration_controls(inner, self.calibration_target(PAPER_ORIENTATION_AUTO))

        def bind_scroll(widget):
            widget.bind("<MouseWheel>", lambda e: scroll_canvas.yview_scroll(int(-e.delta / 120), "units"), add="+")
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(inner)

        actions = tk.Frame(body, bg=THEME["panel"])
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        self.make_button(actions, "关闭", window.destroy, "secondary").pack(side=tk.RIGHT)

        window.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - window.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")


