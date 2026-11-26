"""Multi-photo print sheet editor."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .collage_layout import CollageOptions, GRIDS, ORIENTATIONS, PAPERS, build_collage_task, choose_paper
from .specifications import FIT_MODE_EQUAL_BORDER, FIT_MODE_OPTIONS, THEME


def open_collage_editor(app):
    existing = getattr(app, "collage_editor", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    app.collage_editor = CollageEditor(app)
    return app.collage_editor


class CollageEditor(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("多照片拼版")
        self.configure(bg=THEME["panel"])
        self.geometry("840x560")
        self.minsize(680, 500)
        self.transient(app.root)
        self.grab_set()
        self.photos = []
        self.page = 0
        self.draft = None
        self.rendered = None
        self.paper = tk.StringVar(self, "5寸" if app.layout_mode.get().startswith("5") else "6寸")
        self.pattern = tk.StringVar(self, "四宫格")
        self.direction = tk.StringVar(self, "自动")
        self.border = tk.StringVar(self, str(app.margin_mm.get() if app.enable_margin.get() else 0))
        self.fit = tk.StringVar(self, FIT_MODE_EQUAL_BORDER)
        self.cut_marks = tk.BooleanVar(self, app.draw_cut_line.get())
        self.auto_rotate = tk.BooleanVar(self, app.auto_rotate.get())
        self.summary = tk.StringVar(self)
        self.pending = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = tk.Frame(self, bg=THEME["panel"])
        side.grid(row=0, column=0, sticky="nsew", padx=14, pady=12)
        side.grid_columnconfigure(1, weight=1)
        side.grid_rowconfigure(7, weight=1)
        for i, (title, var, choices) in enumerate([
                ("相纸", self.paper, PAPERS), ("排列", self.pattern, GRIDS),
                ("纸张方向", self.direction, ORIENTATIONS), ("照片适配", self.fit, FIT_MODE_OPTIONS)]):
            self.label(side, title).grid(row=i, column=0, sticky="w", pady=3)
            box = ttk.Combobox(side, textvariable=var, values=tuple(choices), width=16, state="readonly",
                               style="Merchant.TCombobox")
            box.grid(row=i, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=3)
        self.label(side, "四边留白 (mm)").grid(row=4, column=0, sticky="w")
        ttk.Spinbox(side, from_=0, to=10, increment=0.5, textvariable=self.border,
                    width=8).grid(row=4, column=1, sticky="w", padx=6)
        flags = tk.Frame(side, bg=THEME["panel"])
        flags.grid(row=5, column=0, columnspan=3, sticky="ew")
        for label, var in (("自动转正", self.auto_rotate), ("裁切标记", self.cut_marks)):
            tk.Checkbutton(flags, text=label, variable=var, bg=THEME["panel"], fg=THEME["text"],
                           selectcolor=THEME["card"], activebackground=THEME["panel"],
                           activeforeground=THEME["accent"]).pack(side=tk.LEFT, pady=4)
        app.make_button(side, "添加照片", self.add_files, "primary", compact=True).grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=5)
        listing = tk.Frame(side)
        listing.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=5)
        self.listbox = tk.Listbox(listing, width=26, height=5, exportselection=False,
                                  bg=THEME["card"], fg=THEME["text"], bd=0,
                                  selectbackground="#314426", selectforeground=THEME["accent"])
        bar = ttk.Scrollbar(listing, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.reveal_selected)
        for i, (label, action) in enumerate((("上移", lambda: self.move(-1)),
                                             ("下移", lambda: self.move(1)), ("移除", self.remove))):
            app.make_button(side, label, action, compact=True).grid(row=8, column=i, sticky="ew", padx=2)

        preview = tk.Frame(self, bg=THEME["bg"])
        preview.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        self.canvas = tk.Canvas(preview, bg=THEME["bg"], highlightthickness=0, width=260, height=250)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self.paint())
        nav = tk.Frame(preview, bg=THEME["bg"])
        nav.pack(fill=tk.X)
        app.make_button(nav, "上一页", lambda: self.turn(-1), compact=True).pack(side=tk.LEFT)
        app.make_button(nav, "下一页", lambda: self.turn(1), compact=True).pack(side=tk.RIGHT)
        tk.Label(nav, textvariable=self.summary, fg=THEME["text"], bg=THEME["bg"], wraplength=290).pack(
            fill=tk.X, expand=True, pady=5)
        self.enqueue = app.make_button(self, "将拼版加入打印队列", self.commit, "primary")
        self.enqueue.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 12))
        for var in (self.paper, self.pattern, self.direction, self.border, self.fit, self.auto_rotate, self.cut_marks):
            var.trace_add("write", self.schedule)
        self.refresh()

    def label(self, parent, text):
        return tk.Label(parent, text=text, bg=THEME["panel"], fg=THEME["text"])

    def options(self):
        try:
            border = float(self.border.get())
        except ValueError:
            raise ValueError("请输入 0 至 10 之间的留白毫米数") from None
        return CollageOptions(self.paper.get(), self.pattern.get(), self.direction.get(), border,
                              self.fit.get(), self.auto_rotate.get(), self.cut_marks.get())

    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="选择不同的照片",
                    filetypes=[("照片", "*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"), ("全部文件", "*.*")])
        if not paths:
            return
        new = []
        try:
            for path in paths:
                with Image.open(path) as img:
                    size = img.size[::-1] if img.getexif().get(274, 1) in (5, 6, 7, 8) else img.size
                new.append((path, size))
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            messagebox.showerror("照片无法读取", f"{os.path.basename(path)}\n{exc}", parent=self)
            return
        self.photos.extend(new)
        self.update_list()

    def update_list(self, selected=None):
        self.listbox.delete(0, tk.END)
        for i, (path, _) in enumerate(self.photos, 1):
            self.listbox.insert(tk.END, f"{i:02d}   {os.path.basename(path)}")
        if selected is not None and self.photos:
            selected = min(selected, len(self.photos) - 1)
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
            self.reveal_selected()
        self.schedule()

    def reveal_selected(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            rows, columns = GRIDS[self.pattern.get()]
            self.page = selection[0] // (rows * columns)
            self.schedule()

    def move(self, delta):
        selection = self.listbox.curselection()
        if selection:
            i = selection[0]
            j = i + delta
            if 0 <= j < len(self.photos):
                self.photos[i], self.photos[j] = self.photos[j], self.photos[i]
                self.update_list(j)

    def remove(self):
        selection = self.listbox.curselection()
        if selection:
            self.photos.pop(selection[0])
            self.update_list(selection[0])

    def turn(self, delta):
        self.page += delta
        self.schedule()

    def schedule(self, *_):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(100, self.refresh)

    def refresh(self):
        self.pending = None
        self.draft = None
        self.enqueue.configure(state=tk.DISABLED)
        try:
            options = self.options()
            if self.photos:
                pages = (len(self.photos) + options.capacity - 1) // options.capacity
                self.page = max(0, min(self.page, pages - 1))
                begin = self.page * options.capacity
                paths = [p for p, _ in self.photos[begin:begin + options.capacity]]
                paper = choose_paper(options, [size for _, size in self.photos])
                # Native-pixel mode depends on output DPI. Display a reduction of the actual sheet.
                task = build_collage_task(paths, options, paper, self.app.dpi.get())
                self.draft = task["preview_image"]
                blank = options.capacity - len(paths)
                self.summary.set(f"第 {self.page + 1} / {pages} 页 · {paper[0]:g} × {paper[1]:g} mm"
                                 + (f" · 末尾留空 {blank} 格" if blank else ""))
                self.enqueue.configure(state=tk.NORMAL, text=f"将 {pages} 页拼版加入打印队列")
            else:
                self.summary.set("添加照片后预览")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.summary.set(str(exc))
        self.paint()

    def paint(self):
        self.canvas.delete("all")
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.draft is None:
            self.canvas.create_text(w // 2, h // 2, text="添加照片，预览相纸上的排列", fill=THEME["muted"])
            return
        image = self.draft.copy()
        image.thumbnail((max(1, w - 24), max(1, h - 24)), Image.Resampling.LANCZOS)
        self.rendered = ImageTk.PhotoImage(image, master=self)
        self.canvas.create_image(w // 2, h // 2, image=self.rendered)

    def commit(self):
        if not self.photos:
            return
        try:
            options = self.options()
            paper = choose_paper(options, [size for _, size in self.photos])
            paths = [p for p, _ in self.photos]
            tasks = []
            for i in range(0, len(paths), options.capacity):
                task = build_collage_task(paths[i:i + options.capacity], options, paper, self.app.dpi.get())
                validation = self.app.validate_position(task)
                if not validation["ok"]:
                    raise ValueError("\n".join(validation["errors"]))
                tasks.append(task)
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            messagebox.showerror("拼版未加入队列", str(exc), parent=self)
            return
        first = len(self.app.batch_tasks)
        self.app.batch_tasks.extend(tasks)
        self.app.update_task_list()
        self.app.update_status_dashboard()
        self.app.task_listbox.selection_clear(0, tk.END)
        self.app.task_listbox.selection_set(first)
        self.app.task_listbox.activate(first)
        self.app.preview_selected_task()
        self.app.status_var.set(f"已加入 {len(tasks)} 页多照片拼版")
        self.close()

    def close(self):
        if self.pending:
            self.after_cancel(self.pending)
        self.destroy()
