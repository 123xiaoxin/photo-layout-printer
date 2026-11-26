"""Photo layout application entry point and controller."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageFont
import sys
import os
import json
from datetime import datetime

from photo_layout.specifications import *  # Existing import surface for callers.
from photo_layout.configuration import ConfigurationMixin
from photo_layout.layout import LayoutMixin
from photo_layout.interface import InterfaceMixin
from photo_layout.batches import BatchesMixin
from photo_layout.photos import PhotosMixin
from photo_layout.printing import PrintingMixin
from photo_layout.preview import PreviewMixin
from photo_layout.page_settings_ui import PageSettingsMixin
from photo_layout.print_orientation import PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_OPTIONS


class PhotoLayoutPrinter(ConfigurationMixin, LayoutMixin, InterfaceMixin, BatchesMixin, PhotosMixin, PrintingMixin, PreviewMixin, PageSettingsMixin):
    def __init__(self, root):
        self.root = root
        self.root.title("Merchant Pro - 商用照片排版工具")
        self.root.geometry("1320x820")
        self.root.resizable(True, True)
        self.root.minsize(1120, 720)
        self.root.configure(bg=THEME["bg"])

        # 存储图片
        self.original_images = [None, None]
        self.original_paths = ["", ""]
        self.processed_photos = [None, None]
        self.preview_photos = [None, None]
        self.combined_image = None
        self.preview_tk = None
        self.batch_tasks = []
        self.preview_task_index = None

        # 选项设置
        self.enable_margin = tk.BooleanVar(value=True)
        self.margin_mm = tk.DoubleVar(value=2.0)
        self.fit_mode = tk.StringVar(value=FIT_MODE_CROP)
        self.layout_mode = tk.StringVar(value="5寸+3寸")
        self.middle_margin_mm = tk.DoubleVar(value=0.0)
        self.show_guides = tk.BooleanVar(value=True)
        self.draw_cut_line = tk.BooleanVar(value=True)
        self.auto_rotate = tk.BooleanVar(value=True)
        self.dpi = tk.IntVar(value=DPI)
        self.print_method = tk.StringVar(value=PRINT_METHOD_DIRECT)
        self.paper_orientation = tk.StringVar(value=PAPER_ORIENTATION_AUTO)
        self.print_offset_x_mm = tk.DoubleVar(value=0.0)
        self.print_offset_y_mm = tk.DoubleVar(value=0.0)
        self.printer_calibration = {}
        self.selected_printer_name = tk.StringVar(value="")
        self.follow_system_printer = tk.BooleanVar(value=True)
        self.printer_names = []
        self.printer_combo = None

        # 照片状态
        self.rotation_angles = [0, 0]
        self.horizontal_offset = [0, 0]
        self.vertical_offset = [0, 0]

        # 当前选中的照片
        self.selected_photo = tk.IntVar(value=0)  # 0或1
        self.status_var = tk.StringVar(value="就绪，请导入照片或载入演示素材")
        self.canvas_status_var = tk.StringVar(value="纸张：- | DPI：- | 边距：- | 状态：等待导入")
        self.queue_summary_var = tk.StringVar(value="当前队列：0 个任务 | 预计：0 秒")
        self.issue_var = tk.StringVar(value="暂无问题")
        self.metric_vars = {}
        self.photo_meta_vars = [None, None]
        self.photo_state_vars = [None, None]
        self._preview_resize_job = None
        self.advanced_window = None

        # 加载保存的配置
        self.load_config()
        self._last_saved_paper_orientation = self.paper_orientation.get()
        self.refresh_printer_list(show_status=False, save=False)

        self.configure_theme()
        self.setup_ui()
        self.setup_drag_drop()
        self.update_preview()


    def on_paper_orientation_changed(self, _event=None):
        previous = getattr(self, "_last_saved_paper_orientation", PAPER_ORIENTATION_AUTO)
        if self.paper_orientation.get() not in PAPER_ORIENTATION_OPTIONS:
            self.paper_orientation.set(PAPER_ORIENTATION_AUTO)
        if not self.save_config():
            self.paper_orientation.set(previous)
            messagebox.showerror("无法保存相纸方向", getattr(self, "last_config_error", "请检查设置文件是否可写"), parent=self.root)
        else:
            self._last_saved_paper_orientation = self.paper_orientation.get()
        self.load_template_offsets()
        self.refresh_visible_preview()
        self.status_var.set(f"相纸放置方向：{self.paper_orientation.get()}")


    def reset_print_offsets(self):
        self.print_offset_x_mm.set(0.0)
        self.print_offset_y_mm.set(0.0)
        try:
            self.save_template_offsets()
        except OSError as error:
            self.status_var.set("校准未保存，已恢复原来的补偿值")
            messagebox.showerror("无法保存打印校准", f"已恢复原来的补偿值。\n\n{error}", parent=self.root)
            return
        self.update_preview()
        self.status_var.set("打印画面微调已重置")


    def apply_layout_preset(self, preset):
        self.layout_mode.set(preset)
        self.on_layout_changed()


    def on_settings_changed(self, reprocess=False):
        if getattr(self, "_restoring_task_editor", False) or not self.page_editor_available():
            return
        if not self.apply_shared_page_settings():
            if reprocess:
                self.reprocess_all_and_update()
            else:
                self.update_preview()
        self.save_config()


    def on_fit_mode_changed(self):
        self.fit_mode.set(normalize_fit_mode(self.fit_mode.get()))
        self.on_settings_changed(reprocess=True)
        self.status_var.set(f"照片适配模式：{self.fit_mode.get()}")


    def on_photo_selected(self):
        """照片选择改变"""
        idx = self.selected_photo.get()
        if self.original_images[idx] is not None:
            self.status_var.set(f"当前选中: 照片{idx+1}")
        else:
            self.status_var.set(f"当前选中: 照片{idx+1} (未添加)")


    def update_offset_label(self):
        """更新偏移显示"""
        if not hasattr(self, "offset_label"):
            return
        idx = self.selected_photo.get()
        x = self.horizontal_offset[idx]
        y = self.vertical_offset[idx]
        self.offset_label.config(text=f"偏移: X={x} Y={y} (照片{idx+1})")


    def move_selected(self, dx, dy):
        """移动选中的照片"""
        idx = self.selected_photo.get()
        if not self.can_edit_photo(idx):
            return

        if self.processed_photos[idx] is None:
            messagebox.showwarning("提示", "请先添加照片")
            return

        # 获取照片框尺寸
        _paper_mm, _photo_mm, _paper_px, photo_px = self.get_current_layout()
        photo_px_w, photo_px_h = photo_px

        # 计算最大偏移
        actual_w = self.processed_photos[idx].size[0]
        actual_h = self.processed_photos[idx].size[1]
        max_offset_x = max(0, (photo_px_w - actual_w) // 2)
        max_offset_y = max(0, (photo_px_h - actual_h) // 2)

        # 应用移动
        new_x = self.horizontal_offset[idx] + dx
        new_y = self.vertical_offset[idx] + dy

        # 限制范围
        if new_x > max_offset_x: new_x = max_offset_x
        if new_x < -max_offset_x: new_x = -max_offset_x
        if new_y > max_offset_y: new_y = max_offset_y
        if new_y < -max_offset_y: new_y = -max_offset_y

        self.horizontal_offset[idx] = new_x
        self.vertical_offset[idx] = new_y

        self.update_preview()
        self.save_config()  # 保存设置

        direction = ""
        if dx < 0: direction = "左移"
        elif dx > 0: direction = "右移"
        elif dy < 0: direction = "上移"
        elif dy > 0: direction = "下移"
        self.status_var.set(f"照片{idx+1} {direction} {max(abs(dx), abs(dy))}px")


    def reset_selected(self):
        """复位选中的照片"""
        idx = self.selected_photo.get()
        if not self.can_edit_photo(idx):
            return
        self.rotation_angles[idx] = 0
        self.horizontal_offset[idx] = 0
        self.vertical_offset[idx] = 0

        # 重新处理图片
        if self.original_images[idx] is not None:
            self.reprocess_photo(idx)

        self.update_preview()
        if hasattr(self, "offset_label"):
            self.update_offset_label()
        self.save_config()
        self.status_var.set(f"照片{idx+1} 已复位")


    def rotate_photo(self, index):
        """旋转指定编号的照片"""
        if not self.can_edit_photo(index):
            return
        if self.original_images[index] is None:
            messagebox.showwarning("提示", "请先添加照片")
            return

        self.rotation_angles[index] = (self.rotation_angles[index] + 90) % 360
        self.reprocess_photo(index)

        self.update_preview()
        self.save_config()

        angle = self.rotation_angles[index]
        self.status_var.set(f"照片{index+1} 已旋转 {angle}°")


    def move_photo(self, index, dx, dy):
        """移动指定编号的照片"""
        if not self.can_edit_photo(index):
            return
        if self.processed_photos[index] is None:
            messagebox.showwarning("提示", "请先添加照片")
            return

        _paper_mm, _photo_mm, _paper_px, photo_px = self.get_current_layout()
        photo_px_w, photo_px_h = photo_px

        actual_w = self.processed_photos[index].size[0]
        actual_h = self.processed_photos[index].size[1]
        max_offset_x = max(0, (photo_px_w - actual_w) // 2)
        max_offset_y = max(0, (photo_px_h - actual_h) // 2)

        new_x = self.horizontal_offset[index] + dx
        new_y = self.vertical_offset[index] + dy

        if new_x > max_offset_x: new_x = max_offset_x
        if new_x < -max_offset_x: new_x = -max_offset_x
        if new_y > max_offset_y: new_y = max_offset_y
        if new_y < -max_offset_y: new_y = -max_offset_y

        self.horizontal_offset[index] = new_x
        self.vertical_offset[index] = new_y

        self.update_preview()
        self.save_config()

        direction = ""
        if dx < 0: direction = "左移"
        elif dx > 0: direction = "右移"
        elif dy < 0: direction = "上移"
        elif dy > 0: direction = "下移"
        self.status_var.set(f"照片{index+1} {direction} {max(abs(dx), abs(dy))}px")


    def reset_all(self):
        """复位所有照片"""
        if not self.page_editor_available():
            return
        for i in range(2):
            self.rotation_angles[i] = 0
            self.horizontal_offset[i] = 0
            self.vertical_offset[i] = 0

            if self.original_images[i] is not None:
                self.reprocess_photo(i)

        self.update_preview()
        self.save_config()
        self.status_var.set("已复位全部照片")


    def rotate_selected(self):
        """旋转选中的照片"""
        idx = self.selected_photo.get()
        if not self.can_edit_photo(idx):
            return

        if self.original_images[idx] is None:
            messagebox.showwarning("提示", "请先添加照片")
            return

        self.rotation_angles[idx] = (self.rotation_angles[idx] + 90) % 360
        self.reprocess_photo(idx)

        self.update_preview()
        self.save_config()

        angle = self.rotation_angles[idx]
        self.status_var.set(f"照片{idx+1} 已旋转 {angle}°")


    def update_info_text(self, parent):
        layout_name = self.layout_mode.get()
        paper_mm, photo_mm, _paper_px, _photo_px = self.get_current_layout()

        info_text = f"排版: {layout_name}相纸 ({paper_mm[0]:.1f}×{paper_mm[1]:.1f}mm) - 2张{photo_mm[0]:.1f}×{photo_mm[1]:.1f}mm照片"

        if hasattr(self, "metric_vars"):
            self.update_status_dashboard()
            return

        if hasattr(self, 'info_label') and self.info_label is not None:
            self.info_label.config(text=info_text)
        elif parent is not None:
            self.info_label = ttk.Label(parent, text=info_text, justify=tk.CENTER)
            self.info_label.pack(pady=(0, 5))


    def on_layout_changed(self):
        self.detach_task_editor()
        if self.get_layout_base()["slot_count"] == 1:
            self.original_images[1] = None
            self.original_paths[1] = ""
            self.rotation_angles[1] = 0
            self.horizontal_offset[1] = self.vertical_offset[1] = 0
            self.reprocess_photo(1)
        layout_name = self.layout_mode.get()
        self.root.title(f"Merchant Pro - {layout_name}")
        self.load_template_offsets()  # Load calibration for this template
        self.update_info_text(None)
        self.reprocess_all_and_update()
        self.save_config()


    def setup_drag_drop(self):
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            for widget in [self.root, self.drop1_frame, self.drop2_frame, self.drop1_label, self.drop2_label]:
                try:
                    widget.drop_target_register(DND_FILES)
                except:
                    pass

            if not hasattr(self.root, "dnd_bind"):
                print("提示：当前窗口未启用 TkinterDnD，拖放功能跳过")
                return

            self.root.dnd_bind('<<Drop>>', self.on_drop)
            for widget, handler in [
                (self.drop1_label, lambda e: self.on_drop_to_index(e, 0)),
                (self.drop2_label, lambda e: self.on_drop_to_index(e, 1)),
                (self.drop1_frame, lambda e: self.on_drop_to_index(e, 0)),
                (self.drop2_frame, lambda e: self.on_drop_to_index(e, 1)),
            ]:
                if hasattr(widget, "dnd_bind"):
                    widget.dnd_bind('<<Drop>>', handler)
            print("拖放功能已启用")
        except ImportError:
            print("提示：未安装 tkinterdnd2")


    def on_drop(self, event):
        files = self.parse_drop_files(event.data)
        if not files:
            return
        slots = range(self.get_layout_base()["slot_count"])
        targets = sorted(slots, key=lambda index: self.original_images[index] is not None)
        for filepath, index in zip(files, targets):
            self.load_image(filepath, index)


    def on_drop_to_index(self, event, index):
        files = self.parse_drop_files(event.data)
        if not files:
            return
        self.load_image(files[0], index)


    def parse_drop_files(self, data):
        return list(self.root.tk.splitlist(data))


    def clear_all(self):
        self.clear_current_images(save=True)
        self.update_preview()
        self.status_var.set("已清空")


    def save_image(self):
        if self.combined_image is None:
            messagebox.showwarning("提示", "还没有添加照片")
            return

        filename = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("JPEG图片", "*.jpg"), ("PNG图片", "*.png"), ("所有文件", "*.*")], title="保存排版好的图片")

        if filename:
            try:
                img_to_save = self.combined_image
                if filename.lower().endswith('.png'):
                    if img_to_save.mode == 'RGBA':
                        img_to_save.save(filename, dpi=(self.dpi.get(), self.dpi.get()))
                    else:
                        img_to_save = img_to_save.convert('RGB')
                        img_to_save.save(filename, dpi=(self.dpi.get(), self.dpi.get()))
                else:
                    if img_to_save.mode in ('RGBA', 'LA', 'P'):
                        img_to_save = img_to_save.convert('RGB')
                    img_to_save.save(filename, quality=95, optimize=True, dpi=(self.dpi.get(), self.dpi.get()))

                messagebox.showinfo("成功", f"已保存到:\n{filename}")
                self.status_var.set(f"已保存: {os.path.basename(filename)}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {str(e)}")


def main():
    from photo_layout.startup import reveal_with_startup

    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()

    root.withdraw()
    app = PhotoLayoutPrinter(root)
    reveal_with_startup(root)
    root.mainloop()


if __name__ == "__main__":
    main()
