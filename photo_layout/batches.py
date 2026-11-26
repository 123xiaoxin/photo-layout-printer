"""Photo batch creation and queue operations."""
import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog
import os
from datetime import datetime
from itertools import groupby
from PIL import Image
from .specifications import THEME
from .print_orientation import task_output_paper_size, paper_orientation_label

# Output orientation and printer calibration are global; these settings belong
# to an individual editable photo group.
PAGE_SETTINGS = (
    "layout_mode", "dpi", "fit_mode", "margin_mm", "enable_margin",
    "middle_margin_mm", "auto_rotate", "show_guides", "draw_cut_line",
)

class BatchesMixin:
    """Behavior used by the application controller."""
    def detach_task_editor(self):
        """Start a draft without changing any queued sheet."""
        self._editing_task = None
        self._displayed_editor_task = None
        self.preview_task_index = None
        if hasattr(self, "task_listbox"):
            self.task_listbox.selection_clear(0, tk.END)
        self.sync_photo_edit_controls()

    def capture_editor_state(self):
        count = self.get_layout_base()["slot_count"]
        return {
            "settings": {name: getattr(self, name).get() for name in PAGE_SETTINGS},
            # Source pixels are immutable; fitting/rotation create new images.
            # Keep them in memory so an edited group never depends on a file
            # still being present, and copy the mutable lists for every group.
            "original_images": [self.original_images[i] if i < count else None for i in range(2)],
            "original_paths": [self.original_paths[i] if i < count else "" for i in range(2)],
            "rotations": self.rotation_angles[:],
            "horizontal_offset": self.horizontal_offset[:],
            "vertical_offset": self.vertical_offset[:],
        }

    def apply_editor_state(self, state, refresh_thumbnails=True):
        for name, value in state["settings"].items():
            getattr(self, name).set(value)
        self.original_images = state["original_images"][:]
        self.original_paths = state["original_paths"][:]
        self.rotation_angles = state["rotations"][:]
        self.horizontal_offset = state["horizontal_offset"][:]
        self.vertical_offset = state["vertical_offset"][:]
        for i in range(2):
            self.reprocess_photo(i, refresh_thumbnail=refresh_thumbnails)

    def remember_page_settings(self):
        self._page_settings_snapshot = {name: getattr(self, name).get() for name in PAGE_SETTINGS}

    def apply_shared_page_settings(self):
        """Apply only changed settings to every ordinary photo group."""
        current = {name: getattr(self, name).get() for name in PAGE_SETTINGS}
        previous = getattr(self, "_page_settings_snapshot", current)
        changed = {name: value for name, value in current.items()
                   if name != "layout_mode" and previous.get(name) != value}
        if not changed:
            return
        draft = self.capture_editor_state()
        selected = getattr(self, "_editing_task", None)
        self._restoring_task_editor = True
        try:
            for task in self.batch_tasks:
                state = task.get("editor_state")
                if task.get("kind") == "collage" or state is None:
                    continue
                state = {**state, "settings": {**state["settings"], **changed}}
                self.apply_editor_state(state, refresh_thumbnails=False)
                self.combined_image = self.combine_images()
                updated, _errors = self.build_current_task(
                    allow_blank_slot=task.get("allow_blank_slot"), require_valid=False)
                if updated is not None:
                    updated["created"] = task["created"]
                    task.update(updated)
            # The user's visible group and printing selection do not change
            # while the other groups are regenerated.
            state = selected["editor_state"] if selected is not None else draft
            self.apply_editor_state(state)
            self.remember_page_settings()
        finally:
            self._restoring_task_editor = False
        self.update_task_list()
        self.update_preview()
        return True

    def restore_task_editor(self, task):
        if getattr(self, "_displayed_editor_task", None) is task:
            return
        self._restoring_task_editor = True
        try:
            self._editing_task = None
            self.clear_current_images(save=False, detach=False)
            state = task.get("editor_state") if task.get("kind") != "collage" else None
            if state is not None:
                self._editing_task = task
                self.apply_editor_state(state)
            self.combined_image = task["image"]
            self._current_preview_source = task["preview_image"]
            self._displayed_editor_task = task
            self.remember_page_settings()
            self.load_template_offsets()
            self.update_offset_label()
            self.sync_photo_edit_controls()
            self.update_status_dashboard()
        finally:
            self._restoring_task_editor = False

    def commit_selected_task(self):
        index = self.preview_task_index
        if index is None or not 0 <= index < len(self.batch_tasks):
            return False
        task = self.batch_tasks[index]
        if getattr(self, "_editing_task", None) is not task:
            return False
        blank = task.get("allow_blank_slot")
        if blank is not None and self.original_images[blank] is not None:
            blank = None
        # Keep invalid edits visible and unprintable instead of silently printing
        # the previously valid pixels after the user has changed this group.
        updated, _errors = self.build_current_task(allow_blank_slot=blank, require_valid=False)
        if updated is None:
            return False
        updated["created"] = task["created"]
        task.update(updated)  # Preserve identity, checked_for_print, and queue order.
        self.remember_page_settings()
        self.update_task_list()
        self.update_status_dashboard()
        self.preview_selected_task()
        return True

    def page_editor_available(self):
        index = self.preview_task_index
        return index is None or (
            0 <= index < len(self.batch_tasks)
            and getattr(self, "_editing_task", None) is self.batch_tasks[index]
        )

    def can_edit_photo(self, index):
        if not self.page_editor_available():
            self.status_var.set("此页请在多照片拼版窗口中编辑")
            return False
        return 0 <= index < self.get_layout_base()["slot_count"]

    def select_files_batch(self):
        filetypes = [("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp"), ("所有文件", "*.*")]
        slot_count = self.get_layout_base()["slot_count"]
        group_size = 1 if slot_count == 1 else 2
        title = "选择批量照片（每张生成一个打印批次）" if group_size == 1 else "选择批量照片（每两张生成一个打印批次）"
        filenames = list(filedialog.askopenfilenames(title=title, filetypes=filetypes))
        if not filenames:
            return

        added = 0
        errors = []
        start_index = len(self.batch_tasks)
        for group_index in range(0, len(filenames), group_size):
            pair = filenames[group_index:group_index + group_size]
            allow_blank = False
            if group_size == 2 and len(pair) < 2:
                resolution, extra_file = self.resolve_odd_batch_photo(pair[0], filenames)
                if resolution == "cancel":
                    errors.append(f"末尾剩余 1 张未入队: {os.path.basename(pair[0])}")
                    break
                if resolution == "blank":
                    allow_blank = True
                elif extra_file:
                    pair.append(extra_file)
            self.clear_current_images(save=False)
            for slot, filename in enumerate(pair):
                try:
                    self.set_image_from_file(filename, slot)
                except Exception as e:
                    errors.append(f"{os.path.basename(filename)} 加载失败: {e}")
            self.combined_image = self.combine_images()
            task, task_errors = self.build_current_task(allow_blank_slot=1 if allow_blank else None)
            if task is None:
                errors.extend([f"第 {group_index // group_size + 1} 组: {e}" for e in task_errors])
                continue
            self.batch_tasks.append(task)
            added += 1

        self.update_task_list()
        self.update_preview()
        if added:
            self.task_listbox.selection_clear(0, tk.END)
            self.task_listbox.selection_set(start_index)
            self.task_listbox.activate(start_index)
            self.preview_selected_task()
        self.status_var.set(f"批量导入完成：新增 {added} 个打印批次")
        if errors:
            messagebox.showwarning("批量导入提示", "\n".join(errors[:10]))


    def resolve_odd_batch_photo(self, leftover_file, filenames):
        result = {"mode": "cancel", "file": None}
        dialog = tk.Toplevel(self.root)
        dialog.title("单数照片处理")
        dialog.configure(bg=THEME["panel"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(
            dialog,
            text="最后一个批次只剩 1 张照片",
            bg=THEME["panel"],
            fg=THEME["text"],
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor=tk.W, padx=18, pady=(16, 4))
        tk.Label(
            dialog,
            text=f"照片 1: {os.path.basename(leftover_file)}",
            bg=THEME["panel"],
            fg=THEME["muted"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor=tk.W, padx=18, pady=(0, 12))

        choices = tk.Frame(dialog, bg=THEME["panel"])
        choices.pack(fill=tk.BOTH, padx=18)
        self.make_button(choices, "第二格留空", lambda: finish("blank"), "primary").pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            choices,
            text="或选择一张补到第二格",
            bg=THEME["panel"],
            fg=THEME["muted"],
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor=tk.W, pady=(4, 6))

        listbox = tk.Listbox(
            choices,
            height=9,
            bg=THEME["card"],
            fg=THEME["text"],
            selectbackground="#314426",
            selectforeground=THEME["accent"],
            highlightthickness=1,
            highlightbackground=THEME["border"],
            bd=0,
            font=("Microsoft YaHei UI", 9),
        )
        reusable_files = [path for path in filenames if path != leftover_file]
        for path in reusable_files:
            listbox.insert(tk.END, os.path.basename(path))
        listbox.pack(fill=tk.BOTH)
        if reusable_files:
            listbox.selection_set(0)

        buttons = tk.Frame(dialog, bg=THEME["panel"])
        buttons.pack(fill=tk.X, padx=18, pady=16)

        def choose_from_list():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("提示", "请先在列表中选择一张照片", parent=dialog)
                return
            finish("file", reusable_files[selection[0]])

        def choose_new_file():
            filetypes = [("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp"), ("所有文件", "*.*")]
            filename = filedialog.askopenfilename(title="选择补充照片", filetypes=filetypes, parent=dialog)
            if filename:
                finish("file", filename)

        def finish(mode, file_path=None):
            result["mode"] = mode
            result["file"] = file_path
            dialog.destroy()

        self.make_button(buttons, "从列表选中", choose_from_list, "secondary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.make_button(buttons, "重新上传", choose_new_file, "secondary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.make_button(buttons, "取消", lambda: finish("cancel"), "danger").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        self.root.wait_window(dialog)
        return result["mode"], result["file"]


    def describe_current_page(self, allow_blank_slot=None, require_valid=True):
        if self.combined_image is None:
            return None, ["还没有生成排版图"]
        processed_sizes = [photo.size if photo is not None else None for photo in self.processed_photos]
        geometry = self.build_layout_geometry(
            processed_sizes=processed_sizes,
            offsets=list(zip(self.horizontal_offset, self.vertical_offset)),
        )
        slot_count = geometry.get("slot_count", len(geometry["slots"]))
        source_count = sum(1 for img in self.original_images[:slot_count] if img is not None)
        task = {
            "image": self.combined_image,
            "layout": self.layout_mode.get(),
            "dpi": self.dpi.get(),
            "fit_mode": self.fit_mode.get(),
            "margin_mm": self.margin_mm.get(),
            "enable_margin": self.enable_margin.get(),
            "middle_margin_mm": self.middle_margin_mm.get(),
            "auto_rotate": self.auto_rotate.get(),
            "show_guides": self.show_guides.get(),
            "draw_cut_line": self.draw_cut_line.get(),
            "paper_mm": geometry["paper_mm"],
            "photo_mm": geometry["photo_mm"],
            "size": self.combined_image.size,
            "source_count": source_count,
            "allow_blank_slot": allow_blank_slot,
            "source_paths": self.original_paths[:],
            "processed_sizes": processed_sizes,
            "offsets": list(zip(self.horizontal_offset, self.vertical_offset)),
            "rotations": self.rotation_angles[:],
            "geometry": geometry,
            "created": datetime.now().strftime("%H:%M:%S"),
        }
        task["validation"] = self.validate_position(task)
        if require_valid and not task["validation"]["ok"]:
            return None, task["validation"]["errors"]
        return task, []

    def build_current_task(self, allow_blank_slot=None, require_valid=True):
        task, errors = self.describe_current_page(allow_blank_slot, require_valid=require_valid)
        if task is None:
            return None, errors
        task["image"] = task["image"].copy()
        preview = self.combine_images(for_preview=True)
        preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        task["preview_image"] = preview
        task["editor_state"] = self.capture_editor_state()
        return task, []

    def add_task(self):
        task, errors = self.build_current_task()
        if task is None:
            if not errors:
                errors = ["请先导入照片或载入演示素材"]
            messagebox.showerror("位置校验失败", "\n".join(errors))
            self.status_var.set("位置校验失败，未加入批次")
            return
        self.batch_tasks.append(task)
        self.update_task_list()
        self.update_status_dashboard()
        self.task_listbox.selection_clear(0, tk.END)
        self.task_listbox.selection_set(tk.END)
        self.task_listbox.activate(tk.END)
        self.preview_selected_task()
        self.status_var.set(f"已加入批次：{task['layout']} / {task['size'][0]}x{task['size'][1]}，位置校验通过")


    def update_task_list(self):
        if not hasattr(self, "task_listbox"):
            return
        previous_selection = self.task_listbox.curselection()
        previous_index = previous_selection[0] if previous_selection else self.preview_task_index
        self.task_listbox.delete(0, tk.END)
        for idx, task in enumerate(self.batch_tasks):
            self.task_listbox.add_task(task, idx, self.format_task_sources(task, max_name_len=16))
        if previous_index is not None and 0 <= previous_index < len(self.batch_tasks):
            self.task_listbox.selection_set(previous_index)
            self.task_listbox.activate(previous_index)
        self.update_checked_button()

    def update_checked_button(self):
        count = sum(bool(task.get("checked_for_print")) for task in self.batch_tasks)
        self.print_checked_button.configure(text=f"打印勾选页（{count}）",
                                            state=tk.NORMAL if count else tk.DISABLED)

    def check_all_sheets(self, checked):
        for task in self.batch_tasks:
            task["checked_for_print"] = checked
        self.update_task_list()

    def print_checked_sheets(self):
        sheets = [task for task in self.batch_tasks if task.get("checked_for_print")]
        if sheets:
            self.dispatch_queue_tasks(sheets)

    def dispatch_queue_tasks(self, sheets):
        """Print only the requested pages, retaining queue order across paper changes."""
        sheet_numbers = {id(task): i for i, task in enumerate(self.batch_tasks, 1)}
        orientation = self.current_paper_orientation()
        if not self.validate_batch_queue(show_message=False, tasks=sheets):
            self.validate_batch_queue(tasks=sheets)
            return
        submitted = 0
        last_printer = None
        for paper, group in groupby(sheets, key=lambda task: task_output_paper_size(task, orientation)):
            jobs = list(group)
            if submitted:
                prompt = (f"已提交 {submitted} 页。请等上一组打印结束，将纸张换为 "
                          f"{paper[0]:g} × {paper[1]:g} mm，{paper_orientation_label(paper)}，"
                          f"再继续打印接下来的 {len(jobs)} 页。")
                if not messagebox.askokcancel("确认下一组相纸", prompt):
                    self.status_var.set(f"已提交 {submitted} 页，其余页未提交")
                    return
            info, dc, cleanup = self.prepare_print_context(jobs, "队列打印", paper_orientation=orientation)
            if info is None:
                if submitted:
                    self.status_var.set(f"已提交 {submitted} 页，其余页未提交")
                return
            try:
                printer = info["name"]
                if last_printer is not None and printer != last_printer:
                    prompt = (f"前 {submitted} 页已提交到 {self.printer_display_name(last_printer)}。"
                              f"本组目标已变为 {self.printer_display_name(printer)}，是否在这台打印机上继续？")
                    if not messagebox.askokcancel("本次作业的打印机已改变", prompt):
                        self.status_var.set(f"已提交 {submitted} 页，其余页未提交")
                        return
                self.print_tasks_with_win32(jobs, info, printer_dc=dc)
                last_printer = printer
            except Exception as error:
                first_page = sheet_numbers[id(jobs[0])]
                messagebox.showerror("打印提交失败",
                                     f"本组从队列第 {first_page} 页开始。请检查打印机队列后再重试。\n{error}")
                self.status_var.set(f"打印中断，此前已完成提交 {submitted} 页")
                return
            finally:
                self.close_system_print_context(dc, cleanup)
            submitted += len(jobs)
        self.status_var.set(f"已向打印机提交 {submitted} 页")
        messagebox.showinfo("已提交打印", f"已向打印机提交 {submitted} 页")


    def format_task_sources(self, task, max_name_len=18):
        names = []
        for index, path in enumerate(task.get("source_paths", [])):
            if index >= task.get("geometry", {}).get("slot_count", 2):
                break
            if path:
                name = os.path.basename(path)
                stem, ext = os.path.splitext(name)
                if len(name) > max_name_len:
                    name = f"{stem[:max(4, max_name_len - len(ext) - 1)]}…{ext}"
                names.append(name)
            elif task.get("allow_blank_slot") == index:
                names.append("留空")
        return " + ".join(names) if names else "-"


    def preview_selected_task(self, _event=None):
        if not hasattr(self, "task_listbox"):
            return
        selection = self.task_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.batch_tasks):
            return
        self.preview_task_index = index
        task = self.batch_tasks[index]
        self.restore_task_editor(task)
        validation = task.get("validation") or self.validate_position(task)
        task["validation"] = validation
        status = "校验通过" if validation["ok"] else "校验失败"
        margin_mm = task.get("margin_mm", self.margin_mm.get()) if task.get("enable_margin", True) else 0
        self.canvas_status_var.set(
            f"纸张：{task['layout']} | DPI：{task['dpi']} | 边距：{margin_mm:.1f} mm | 状态：{status}"
        )
        self.render_preview_image(
            task["preview_image"],
            title=f"批次 {index + 1:02d} / {task['layout']} / {task['dpi']} DPI",
            footer=f"{status} - {self.format_task_sources(task, max_name_len=24)}",
            summary=self.format_spec_summary(task),
        )
        warnings = task.get("validation", {}).get("warnings", [])
        self.issue_var.set("；".join(validation["errors"] + warnings) or "所选批次校验通过")
        details = f"正在预览批次 {index + 1}: {status} / {self.format_task_sources(task, max_name_len=36)}"
        if warnings:
            details += " / " + "；".join(warnings[:2])
        self.status_var.set(details)


    def remove_selected_task(self):
        if not hasattr(self, "task_listbox"):
            return
        selection = self.task_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.batch_tasks.pop(index)
        self.detach_task_editor()
        self.update_task_list()
        self.update_status_dashboard()
        if self.batch_tasks:
            self.task_listbox.selection_set(min(index, len(self.batch_tasks) - 1))
            self.preview_selected_task()
        else:
            self.update_preview()
        self.status_var.set("已移除选中的队列任务")


    def clear_queue(self):
        if not self.batch_tasks:
            self.status_var.set("打印队列已为空")
            return
        if not messagebox.askyesno("清空队列", "确定清空当前打印队列吗？"):
            return
        self.batch_tasks.clear()
        self.detach_task_editor()
        self.update_task_list()
        self.update_status_dashboard()
        self.update_preview()
        self.status_var.set("已清空打印队列")


    def validate_batch_queue(self, show_message=True, tasks=None):
        tasks = self.batch_tasks if tasks is None else tasks
        if not tasks:
            if show_message:
                messagebox.showwarning("提示", "批次为空，请先加入至少一个打印任务")
            return False
        all_errors = []
        all_warnings = []
        numbers = {id(task): n for n, task in enumerate(self.batch_tasks, 1)}
        for task in tasks:
            idx = numbers[id(task)]
            validation = self.validate_position(task)
            task["validation"] = validation
            for error in validation["errors"]:
                all_errors.append(f"批次 {idx:02d}: {error}")
            for warning in validation["warnings"]:
                all_warnings.append(f"批次 {idx:02d}: {warning}")
        self.update_task_list()
        self.update_status_dashboard()
        if self.preview_task_index is not None:
            self.preview_selected_task()
        if all_errors:
            if show_message:
                messagebox.showerror("打印位置校验失败", "\n".join(all_errors[:12]))
            self.status_var.set(f"打印位置校验失败：{len(all_errors)} 个问题")
            return False
        message = f"校验通过，共 {len(tasks)} 页。"
        if all_warnings:
            message += "\n\n提示:\n" + "\n".join(all_warnings[:8])
        if show_message:
            messagebox.showinfo("校验通过", message)
        self.status_var.set(f"打印位置校验通过：{len(tasks)} 页")
        return True


