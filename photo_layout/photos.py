"""Image loading, fitting, and composition."""
from tkinter import messagebox
from tkinter import filedialog
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import os
from .specifications import DPI
from .photo_fit import fit_photo, inset_size, read_photo
from .cut_marks import draw_cut_ticks

class PhotosMixin:
    """Behavior used by the application controller."""
    def make_demo_image(self, index):
        size = (1800, 1200) if index == 0 else (1200, 1800)
        base = Image.new("RGB", size, "#121812" if index == 0 else "#101421")
        draw = ImageDraw.Draw(base)
        w, h = size
        accent = (217, 255, 138) if index == 0 else (47, 125, 246)
        muted = (90, 112, 91) if index == 0 else (88, 106, 150)
        for y in range(0, h, 18):
            ratio = y / max(h, 1)
            color = (
                int(18 + ratio * 20),
                int(24 + ratio * 45),
                int(18 + ratio * 35),
            )
            draw.rectangle((0, y, w, y + 18), fill=color)
        for i in range(14):
            x = int((i + 1) * w / 15)
            draw.line((x, 0, x - w // 5, h), fill=muted, width=3)
        draw.rounded_rectangle((w * 0.08, h * 0.12, w * 0.92, h * 0.88), radius=36, outline=accent, width=8)
        draw.ellipse((w * 0.14, h * 0.2, w * 0.38, h * 0.56), fill=accent)
        draw.rectangle((w * 0.16, h * 0.58, w * 0.84, h * 0.76), fill=(250, 250, 244))
        draw.rectangle((w * 0.16, h * 0.79, w * 0.65, h * 0.84), fill=accent)
        try:
            font_big = ImageFont.truetype("arial.ttf", 88)
            font_small = ImageFont.truetype("arial.ttf", 42)
        except Exception:
            font_big = ImageFont.load_default()
            font_small = ImageFont.load_default()
        draw.text((w * 0.44, h * 0.25), f"PHOTO {index + 1}", fill=(244, 247, 239), font=font_big)
        draw.text((w * 0.44, h * 0.38), "Merchant Pro Demo", fill=accent, font=font_small)
        return base


    def load_demo_images(self):
        self.detach_task_editor()
        for index in range(2):
            if index >= self.get_layout_base()["slot_count"]:
                self.original_images[index] = None
                self.original_paths[index] = ""
                self.reprocess_photo(index)
                continue
            self.original_images[index] = self.make_demo_image(index)
            self.original_paths[index] = f"demo_photo_{index + 1}.jpg"
            self.rotation_angles[index] = 0
            self.horizontal_offset[index] = 0
            self.vertical_offset[index] = 0
            self.reprocess_photo(index)
        self.update_preview()
        self.status_var.set("已载入演示照片，请先加入批次，再校验并批量打印")


    def clear_current_images(self, save=True, detach=True):
        if detach:
            self.detach_task_editor()
        self.original_images = [None, None]
        self.original_paths = ["", ""]
        self.processed_photos = [None, None]
        self.preview_photos = [None, None]
        self.rotation_angles = [0, 0]
        self.horizontal_offset = [0, 0]
        self.vertical_offset = [0, 0]
        if hasattr(self, "drop1_label"):
            self.update_photo_thumbnail(0)
            self.update_photo_thumbnail(1)
        if save:
            self.save_config()


    def set_image_from_file(self, filepath, index):
        self.original_images[index] = read_photo(filepath)
        self.original_paths[index] = filepath
        self.rotation_angles[index] = 0
        self.horizontal_offset[index] = 0
        self.vertical_offset[index] = 0
        self.reprocess_photo(index)


    def select_file(self, index):
        if not self.can_edit_photo(index):
            return
        filetypes = [("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp"), ("所有文件", "*.*")]
        filename = filedialog.askopenfilename(title=f"选择第{index+1}张照片", filetypes=filetypes)
        if filename:
            self.load_image(filename, index)


    def load_image(self, filepath, index):
        if not self.can_edit_photo(index):
            return
        try:
            self.set_image_from_file(filepath, index)

            self.update_preview()
            self.save_config()

            self.status_var.set(f"照片{index+1}加载: {os.path.basename(filepath)}")

            if self.preview_task_index is not None:
                self.status_var.set(f"已更新第 {self.preview_task_index + 1} 组的照片 {index + 1}，打印版面已同步")
            elif self.processed_photos[0] is not None and self.processed_photos[1] is not None:
                self.status_var.set("两张照片已就绪，请加入批次后统一打印")

        except Exception as e:
            messagebox.showerror("错误", f"加载图片失败: {str(e)}")


    def reprocess_photo(self, index, refresh_thumbnail=True):
        image = self.original_images[index]
        if image is None:
            self.processed_photos[index] = None
        else:
            slot_size = self.get_layout_base()["photo_px"]
            margin_mm = self.margin_mm.get() if self.enable_margin.get() else 0
            target_size = inset_size(slot_size, margin_mm, self.dpi.get())
            self.processed_photos[index] = fit_photo(
                image, target_size, self.fit_mode.get(), self.auto_rotate.get(), self.rotation_angles[index]
            )
            # Reducing a border or changing DPI also reduces the allowed nudge.
            for offsets, slot_length, target_length in zip(
                (self.horizontal_offset, self.vertical_offset), slot_size, target_size
            ):
                limit = (slot_length - target_length) // 2
                offsets[index] = min(limit, max(-limit, offsets[index]))
        if refresh_thumbnail and hasattr(self, "drop1_label"):
            self.update_photo_thumbnail(index)


    def draw_dashed_line(self, draw, start, end, fill, width=1, dash=12, gap=8):
        x1, y1 = start
        x2, y2 = end
        if y1 == y2:
            step = dash + gap
            direction = 1 if x2 >= x1 else -1
            for x in range(x1, x2 + direction, step * direction):
                dash_end = x + dash * direction
                if direction > 0:
                    dash_end = min(dash_end, x2)
                else:
                    dash_end = max(dash_end, x2)
                draw.line((x, y1, dash_end, y2), fill=fill, width=width)
        elif x1 == x2:
            step = dash + gap
            direction = 1 if y2 >= y1 else -1
            for y in range(y1, y2 + direction, step * direction):
                dash_end = y + dash * direction
                if direction > 0:
                    dash_end = min(dash_end, y2)
                else:
                    dash_end = max(dash_end, y2)
                draw.line((x1, y, x2, dash_end), fill=fill, width=width)


    def draw_dashed_rectangle(self, draw, box, fill, width=1, dash=12, gap=8):
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            return
        self.draw_dashed_line(draw, (x1, y1), (x2, y1), fill, width, dash, gap)
        self.draw_dashed_line(draw, (x1, y2), (x2, y2), fill, width, dash, gap)
        self.draw_dashed_line(draw, (x1, y1), (x1, y2), fill, width, dash, gap)
        self.draw_dashed_line(draw, (x2, y1), (x2, y2), fill, width, dash, gap)


    def combine_images(self, for_preview=False):
        if all(p is None for p in self.processed_photos):
            return None

        processed_sizes = [photo.size if photo is not None else None for photo in self.processed_photos]
        geometry = self.build_layout_geometry(
            processed_sizes=processed_sizes,
            offsets=list(zip(self.horizontal_offset, self.vertical_offset)),
        )
        paper_px = geometry["paper_px"]
        photo_px = geometry["photo_px"]
        combined = Image.new('RGB', paper_px, 'white')
        draw = ImageDraw.Draw(combined)
        dpi = self.dpi.get() if hasattr(self, "dpi") else DPI

        if for_preview and self.show_guides.get():
            guide = (217, 255, 138)
            soft = (215, 220, 210)
            for slot in geometry["slots"]:
                sx, sy, ex, ey = slot["frame"]
                draw.rectangle((sx, sy, sx + photo_px[0] - 1, sy + photo_px[1] - 1), outline=guide, width=max(1, dpi // 150))
                for div in (0.25, 0.5, 0.75):
                    gx = int(sx + photo_px[0] * div)
                    gy = int(sy + photo_px[1] * div)
                    draw.line([(gx, sy), (gx, ey)], fill=soft, width=1)
                    draw.line([(sx, gy), (ex, gy)], fill=soft, width=1)

        # Draw cut lines on the waste side of each edge. With a nonzero
        # gutter, trimming both lines leaves the same border on every photo.
        mark_cuts = self.draw_cut_line.get() or (for_preview and self.show_guides.get())
        if mark_cuts and geometry["slot_count"] > 1:
            ink = (217, 255, 138) if for_preview else (120, 120, 120)
            first, second = (slot["frame"] for slot in geometry["slots"])
            horizontal = geometry["direction"] == "horizontal"
            start, end = (first[2], second[0]) if horizontal else (first[3], second[1])
            edges = sorted({start, max(start, end - 1)})
            margin_mm = self.margin_mm.get() if self.enable_margin.get() else 0
            fitted_size = inset_size(photo_px, margin_mm, dpi)
            inset = (photo_px[0] - fitted_size[0]) // 2
            draw_cut_ticks(combined, edges if horizontal else (), () if horizontal else edges,
                           inset, dpi, ink)

        # 粘贴照片（应用偏移）
        for index, slot in enumerate(geometry["slots"]):
            photo = self.processed_photos[index]
            if photo is None:
                continue
            photo_box = slot["photo"]
            if photo_box is None:
                continue
            paste_x, paste_y = photo_box[0], photo_box[1]
            if photo.mode == 'RGBA':
                combined.paste(photo, (paste_x, paste_y), photo.split()[3])
            else:
                combined.paste(photo, (paste_x, paste_y))
            if for_preview and self.show_guides.get():
                boundary_color = (0, 178, 214)
                boundary_width = max(1, dpi // 180)
                dash = max(8, dpi // 28)
                gap = max(5, dpi // 55)
                self.draw_dashed_rectangle(
                    draw,
                    (photo_box[0], photo_box[1], photo_box[2] - 1, photo_box[3] - 1),
                    boundary_color,
                    width=boundary_width,
                    dash=dash,
                    gap=gap,
                )

        return combined


    def reprocess_all_and_update(self):
        for i in range(2):
            if self.original_images[i] is not None:
                self.reprocess_photo(i)

        self.update_preview()


