"""Preview rendering and status updates."""
import tkinter as tk
from PIL import Image
from PIL import ImageTk
import os
from .specifications import THEME
from .print_orientation import PAPER_ORIENTATION_AUTO, orient_paper_size

class PreviewMixin:
    """Behavior used by the application controller."""
    def cancel_preview_update(self, _event=None):
        if self._preview_resize_job is not None:
            self.root.after_cancel(self._preview_resize_job)
            self._preview_resize_job = None

    def schedule_preview_update(self, _event=None):
        self.cancel_preview_update()
        self._preview_resize_job = self.root.after(80, self.refresh_visible_preview)


    def refresh_visible_preview(self):
        self.cancel_preview_update()
        if self.preview_task_index is not None:
            self.preview_selected_task()
        else:
            self.draw_current_preview()


    def update_photo_thumbnail(self, index):
        img_processed = self.processed_photos[index]
        label = self.drop1_label if index == 0 else self.drop2_label
        name_var = self.photo1_name_var if index == 0 else self.photo2_name_var
        meta_var = self.photo_meta_vars[index] if index < len(self.photo_meta_vars) else None
        state_var = self.photo_state_vars[index] if index < len(self.photo_state_vars) else None

        if img_processed is None:
            unavailable = not self.page_editor_available()
            inactive = index >= self.get_layout_base()["slot_count"]
            placeholder = ("多照片拼版单独设置" if unavailable else
                           "本规格只使用照片 1" if inactive else f"拖入或选择照片 {index + 1}")
            label.config(
                image="",
                text=placeholder,
                bg=THEME["card_soft"],
                fg=THEME["muted"],
                padx=10,
                pady=18,
            )
            name_var.set("未导入")
            if meta_var is not None:
                meta_var.set("未导入\n-\n未放入版面")
            if state_var is not None:
                state_var.set("单独设置" if unavailable else "不使用" if inactive else "等待导入")
            return

        w, h = img_processed.size
        scale = min(104 / max(w, 1), 68 / max(h, 1))
        preview_w = max(1, int(w * scale))
        preview_h = max(1, int(h * scale))
        preview_img = img_processed.resize((preview_w, preview_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(preview_img)
        self.preview_photos[index] = photo
        label.config(image=photo, text="", bg=THEME["card_soft"], padx=0, pady=0)

        name = self.original_paths[index] or f"照片 {index + 1}"
        display_name = os.path.basename(name)
        name_var.set(display_name[:18])
        if meta_var is not None:
            original = self.original_images[index]
            original_size = f"{original.size[0]} x {original.size[1]} px" if original is not None else "-"
            meta_var.set(f"{display_name[:26]}\n原图 {original_size}\n版面 {w} x {h} px")
        if state_var is not None:
            state_var.set("已放入版面")


    def format_spec_summary(self, task=None):
        orientation = self.paper_orientation.get() if hasattr(self, "paper_orientation") else PAPER_ORIENTATION_AUTO
        if task and task.get("kind") == "collage":
            w, h = task["paper_mm"]
            rows, columns = task["geometry"]["grid"]
            if tuple(orient_paper_size((w, h), orientation)) != (w, h):
                w, h = h, w
                rows, columns = columns, rows
            return (f"{w:g} × {h:g} mm   ·   {rows} 行 × {columns} 列\n"
                    f"裁剪留白 {task['margin_mm']:g} mm   ·   {task['dpi']} DPI")
        if task is not None:
            geometry = task["geometry"]
            paper_mm = task["paper_mm"]
            photo_mm = task["photo_mm"]
            paper_px = geometry["paper_px"]
            direction = geometry.get("direction", "vertical")
            dpi = task["dpi"]
            fit_mode = task.get("fit_mode", self.fit_mode.get())
            middle_mm = geometry["middle_margin_px"] * 25.4 / max(dpi, 1)
        else:
            base = self.get_layout_base()
            paper_mm = base["paper_mm"]
            photo_mm = base["photo_mm"]
            paper_px = base["paper_px"]
            direction = base["direction"]
            dpi = self.dpi.get()
            fit_mode = self.fit_mode.get()
            middle_mm = base["middle_margin_px"] * 25.4 / max(dpi, 1)

        output_paper = tuple(orient_paper_size(paper_mm, orientation))
        if output_paper != tuple(paper_mm):
            paper_mm = output_paper
            photo_mm = photo_mm[::-1]
            paper_px = paper_px[::-1]
            if direction != "single":
                direction = "horizontal" if direction == "vertical" else "vertical"
        if direction == "single":
            direction_label = "整张单图"
        elif direction == "horizontal":
            direction_label = "左右双栏"
        else:
            direction_label = "上下双张"
        return (
            f"相纸 {paper_mm[0]:.1f} x {paper_mm[1]:.1f} mm | 单张 {photo_mm[0]:.1f} x {photo_mm[1]:.1f} mm\n"
            f"{direction_label} | 中缝 {middle_mm:.1f} mm | 输出 {paper_px[0]} x {paper_px[1]} @ {dpi} DPI | {fit_mode}"
        )


    def draw_preview_summary(self, canvas_w, summary, top=12):
        if not summary:
            return
        text_width = max(1, canvas_w - 44)
        text_id = self.preview_canvas.create_text(
            canvas_w - 22,
            top,
            text=summary,
            anchor=tk.NE,
            width=text_width,
            justify=tk.RIGHT,
            fill=THEME["text"],
            font=("Microsoft YaHei UI", 9),
        )
        bbox = self.preview_canvas.bbox(text_id)
        if bbox:
            bg_id = self.preview_canvas.create_rectangle(
                bbox[0] - 10,
                bbox[1] - 7,
                bbox[2] + 10,
                bbox[3] + 7,
                fill=THEME["card"],
                outline=THEME["border"],
            )
            self.preview_canvas.tag_lower(bg_id, text_id)
            return bbox[3] + 14
        return top


    def render_preview_image(self, image, title=None, footer=None, summary=None):
        if not hasattr(self, "preview_canvas"):
            return

        orientation = self.paper_orientation.get() if hasattr(self, "paper_orientation") else PAPER_ORIENTATION_AUTO
        if tuple(orient_paper_size(image.size, orientation)) != image.size:
            image = image.transpose(Image.Transpose.ROTATE_270)
        if orientation != PAPER_ORIENTATION_AUTO:
            summary = (summary or self.format_spec_summary()) + f"\n相纸放置：{orientation}"

        self.preview_canvas.delete("all")
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if min(canvas_w, canvas_h) <= 1:
            return
        top = 10
        if title:
            item = self.preview_canvas.create_text(16, top, text=title, anchor=tk.NW,
                width=max(1, canvas_w - 32), fill=THEME["accent"], font=("Microsoft YaHei UI", 11, "bold"))
            top = self.preview_canvas.bbox(item)[3] + 10
        top = self.draw_preview_summary(canvas_w, summary or self.format_spec_summary(), top)
        bottom = canvas_h - 12
        if footer:
            item = self.preview_canvas.create_text(16, bottom, text=footer, anchor=tk.SW,
                width=max(1, canvas_w - 32), fill=THEME["muted"], font=("Microsoft YaHei UI", 10))
            bottom = self.preview_canvas.bbox(item)[1] - 10
        if bottom <= top:
            return
        paper_w, paper_h = image.size
        scale = min(max(1, canvas_w - 40) / paper_w, (bottom - top) / paper_h)
        preview_size = (max(1, int(paper_w * scale)), max(1, int(paper_h * scale)))

        preview_img = image.resize(preview_size, Image.Resampling.LANCZOS)
        self.preview_tk = ImageTk.PhotoImage(preview_img)
        x = canvas_w // 2
        y = (top + bottom) // 2
        self.preview_canvas.create_rectangle(
            x - preview_size[0] // 2 + 12,
            y - preview_size[1] // 2 + 12,
            x + preview_size[0] // 2 + 12,
            y + preview_size[1] // 2 + 12,
            fill="#000000",
            outline="",
        )
        self.preview_canvas.create_image(x, y, image=self.preview_tk)
        self.preview_canvas.create_rectangle(
            x - preview_size[0] // 2,
            y - preview_size[1] // 2,
            x + preview_size[0] // 2,
            y + preview_size[1] // 2,
            outline=THEME["accent"],
            width=1,
        )


    def update_preview(self):
        if getattr(self, "_restoring_task_editor", False):
            return
        if not self.page_editor_available():
            self.preview_selected_task()
            return
        self.combined_image = self.combine_images()
        self._current_preview_source = self.combined_image
        if self.combined_image is not None and (self.show_guides.get() or self.draw_cut_line.get()):
            self._current_preview_source = self.combine_images(for_preview=True)
        if self.commit_selected_task():
            return
        self.detach_task_editor()
        self.remember_page_settings()
        self.draw_current_preview()
        self.update_status_dashboard()

    def draw_current_preview(self):
        if not hasattr(self, "preview_canvas"):
            return

        self.preview_canvas.delete("all")
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if min(canvas_w, canvas_h) <= 1:
            return

        if self.combined_image is None:
            self.preview_canvas.create_rectangle(28, 28, canvas_w - 28, canvas_h - 28, outline=THEME["border"], fill=THEME["card"])
            self.draw_preview_summary(canvas_w, self.format_spec_summary())
            self.preview_canvas.create_text(canvas_w // 2, canvas_h // 2 - 18, text="拖入照片开始排版", fill=THEME["accent"], font=("Microsoft YaHei UI", 24, "bold"))
            self.preview_canvas.create_text(canvas_w // 2, canvas_h // 2 + 24, text="支持 JPG / PNG / WEBP，可批量导入", fill=THEME["muted"], font=("Microsoft YaHei UI", 11))
            return

        self.render_preview_image(self._current_preview_source, title="当前版面预览", footer="调整后请加入批次；排版设置统一应用全部照片组")


    def update_status_dashboard(self):
        if hasattr(self, "refresh_page_settings_summary"):
            self.refresh_page_settings_summary()
        if not hasattr(self, "metric_vars"):
            return

        base = self.get_layout_base()
        slot_count = base["slot_count"]
        loaded = sum(1 for img in self.original_images[:slot_count] if img is not None)
        paper_px = base["paper_px"]
        issues = []

        selected = None
        if self.preview_task_index is not None and 0 <= self.preview_task_index < len(self.batch_tasks):
            selected = self.batch_tasks[self.preview_task_index]
        if selected is not None:
            loaded = selected["source_count"]
            slot_count = selected["geometry"].get("slot_count", len(selected["geometry"]["slots"]))
            paper_px = selected["size"]
            valid = selected.get("validation") or self.validate_position(selected)
            print_status = "可打印：校验通过" if valid["ok"] else "不可打印：需检查"
            issues.extend(valid["errors"])
        elif loaded == 0:
            print_status = "不可打印：缺少照片"
            issues.append("请先导入照片")
        elif loaded < slot_count:
            print_status = "不可打印：缺少照片"
            issues.append(f"还需要 {slot_count - loaded} 张照片")
        else:
            task, task_errors = self.describe_current_page()
            if task is not None:
                print_status = "可打印：校验通过"
            else:
                print_status = "不可打印：需检查"
                issues.extend(task_errors[:3])

        values = {
            "import": f"{loaded}/{slot_count} 张",
            "size": f"{paper_px[0]}x{paper_px[1]} px",
            "dpi": f"{selected['dpi'] if selected else self.dpi.get()}",
            "margin": f"{(selected['margin_mm'] if selected else self.margin_mm.get()) if (selected.get('enable_margin', True) if selected else self.enable_margin.get()) else 0:.1f} mm",
            "fit": selected.get("fit_mode", self.fit_mode.get()) if selected else self.fit_mode.get(),
            "print_status": print_status,
        }
        if hasattr(self, "queue_summary_var"):
            seconds = len(self.batch_tasks) * 10
            if seconds >= 60:
                estimate = f"约 {seconds // 60} 分 {seconds % 60} 秒"
            elif seconds > 0:
                estimate = f"约 {seconds} 秒"
            else:
                estimate = "0 秒"
            self.queue_summary_var.set(f"当前队列：{len(self.batch_tasks)} 个任务 | 预计：{estimate}")
        for key, value in values.items():
            if key in self.metric_vars:
                self.metric_vars[key].set(value)

        if hasattr(self, "canvas_status_var"):
            self.canvas_status_var.set(
                f"纸张：{self.layout_mode.get()} | DPI：{self.dpi.get()} | 边距：{self.margin_mm.get():.1f} mm | 状态：{print_status}"
            )
        if hasattr(self, "issue_var"):
            self.issue_var.set("暂无问题" if not issues else "\n".join(issues[:4]))


