"""Paper geometry and position validation."""
from .specifications import DPI, LAYOUT_OPTIONS, MM_TO_INCH
from .collage_layout import validate_collage

class LayoutMixin:
    """Behavior used by the application controller."""
    def get_current_layout(self):
        base = self.get_layout_base()
        return base["paper_mm"], base["photo_mm"], base["paper_px"], base["photo_px"]


    def get_layout_base(self, layout_name=None, dpi=None, middle_margin_mm=None):
        layout_name = layout_name or self.layout_mode.get()
        if layout_name not in LAYOUT_OPTIONS:
            layout_name = next(iter(LAYOUT_OPTIONS))
        layout = LAYOUT_OPTIONS[layout_name]
        paper_mm = layout["paper_mm"]
        dpi = dpi or (self.dpi.get() if hasattr(self, "dpi") else DPI)
        dpi = dpi or DPI
        middle_margin_mm = self.middle_margin_mm.get() if middle_margin_mm is None else middle_margin_mm
        direction = layout.get("direction", "vertical")
        slot_count = int(layout.get("slot_count", 1 if direction == "single" else 2))

        paper_px = (round(paper_mm[0] * dpi * MM_TO_INCH), round(paper_mm[1] * dpi * MM_TO_INCH))
        requested_middle_px = round(max(0, middle_margin_mm) * dpi * MM_TO_INCH)
        if slot_count == 1 or direction == "single":
            middle_margin_px = 0
            max_middle_px = 0
            photo_px = paper_px
        elif direction == "horizontal":
            max_middle_px = max(0, paper_px[0] - 2)
            middle_margin_px = min(requested_middle_px, max_middle_px)
            photo_px = (max(1, (paper_px[0] - middle_margin_px) // 2), paper_px[1])
        else:
            max_middle_px = max(0, paper_px[1] - 2)
            middle_margin_px = min(requested_middle_px, max_middle_px)
            photo_px = (paper_px[0], max(1, (paper_px[1] - middle_margin_px) // 2))

        photo_mm = (photo_px[0] * 25.4 / dpi, photo_px[1] * 25.4 / dpi)
        return {
            "layout": layout_name,
            "direction": direction,
            "slot_count": slot_count,
            "paper_mm": paper_mm,
            "photo_mm": photo_mm,
            "paper_px": paper_px,
            "photo_px": photo_px,
            "requested_middle_px": requested_middle_px,
            "middle_margin_px": middle_margin_px,
            "max_middle_px": max_middle_px,
        }


    def build_layout_geometry(self, processed_sizes=None, offsets=None, layout_name=None, dpi=None, middle_margin_mm=None):
        layout_name = layout_name or self.layout_mode.get()
        dpi = dpi or self.dpi.get()
        processed_sizes = processed_sizes if processed_sizes is not None else [
            photo.size if photo is not None else None for photo in self.processed_photos
        ]
        offsets = offsets if offsets is not None else list(zip(self.horizontal_offset, self.vertical_offset))

        base = self.get_layout_base(layout_name=layout_name, dpi=dpi, middle_margin_mm=middle_margin_mm)
        paper_mm = base["paper_mm"]
        photo_mm = base["photo_mm"]
        paper_px = base["paper_px"]
        photo_px = base["photo_px"]
        direction = base["direction"]
        slot_count = base["slot_count"]
        middle_margin_px = base["middle_margin_px"]
        requested_middle_px = base["requested_middle_px"]
        max_middle_px = base["max_middle_px"]

        if slot_count == 1 or direction == "single":
            slot_origins = [(0, 0)]
        elif direction == "horizontal":
            total_content_width = photo_px[0] * 2 + middle_margin_px
            available_margin = paper_px[0] - total_content_width
            start_x = max(0, available_margin // 2)
            if available_margin % 2 != 0:
                start_x += 1
            start_y = 0
            slot_origins = [(start_x, start_y), (start_x + photo_px[0] + middle_margin_px, start_y)]
        else:
            total_content_height = photo_px[1] * 2 + middle_margin_px
            available_margin = paper_px[1] - total_content_height
            start_y = max(0, available_margin // 2)
            if available_margin % 2 != 0:
                start_y += 1
            start_x = 0
            slot_origins = [(start_x, start_y), (start_x, start_y + photo_px[1] + middle_margin_px)]

        slots = []
        for index, size in enumerate(processed_sizes[:slot_count]):
            origin_x, origin_y = slot_origins[index]
            frame_box = (origin_x, origin_y, origin_x + photo_px[0], origin_y + photo_px[1])
            photo_box = None
            if size is not None:
                actual_w, actual_h = size
                diff_w = photo_px[0] - actual_w
                diff_h = photo_px[1] - actual_h
                offset_x, offset_y = offsets[index] if index < len(offsets) else (0, 0)
                paste_x = origin_x + (diff_w // 2) + offset_x
                if diff_w % 2 != 0:
                    paste_x += 1
                paste_y = origin_y + (diff_h // 2) + offset_y
                if diff_h % 2 != 0:
                    paste_y += 1
                photo_box = (paste_x, paste_y, paste_x + actual_w, paste_y + actual_h)
            slots.append({"frame": frame_box, "photo": photo_box})

        return {
            "layout": layout_name,
            "dpi": dpi,
            "paper_mm": paper_mm,
            "photo_mm": photo_mm,
            "paper_px": paper_px,
            "photo_px": photo_px,
            "direction": direction,
            "slot_count": slot_count,
            "middle_margin_px": middle_margin_px,
            "requested_middle_px": requested_middle_px,
            "max_middle_px": max_middle_px,
            "slots": slots,
        }


    def validate_position(self, task):
        if task.get("kind") == "collage":
            return validate_collage(task)
        errors = []
        warnings = []
        geometry = task["geometry"]
        paper_w, paper_h = geometry["paper_px"]
        photo_w, photo_h = geometry["photo_px"]
        image_w, image_h = task["image"].size
        mm_per_px = 25.4 / max(task["dpi"], 1)

        if (image_w, image_h) != (paper_w, paper_h):
            errors.append(f"成片尺寸 {image_w}x{image_h} 与模板 {paper_w}x{paper_h} 不一致")
        allow_blank_slot = task.get("allow_blank_slot")
        source_count = task.get("source_count", 0)
        slots = geometry["slots"]
        expected_slots = geometry.get("slot_count", len(slots))
        if source_count != expected_slots:
            if expected_slots == 2 and allow_blank_slot is not None and source_count == 1:
                warnings.append(f"照片{allow_blank_slot + 1}已按用户选择留空")
            else:
                errors.append(f"当前模板需要 {expected_slots} 张照片")
        if expected_slots > 1 and geometry["requested_middle_px"] > geometry["middle_margin_px"]:
            warnings.append("中缝留白超过相纸可用空间，系统已自动限幅")

        direction = geometry.get("direction", "vertical")
        if expected_slots == 1:
            frame = slots[0]["frame"]
            horizontal_error_mm = abs(frame[0] - (paper_w - frame[2])) * mm_per_px
            vertical_error_mm = abs(frame[1] - (paper_h - frame[3])) * mm_per_px
            if horizontal_error_mm > 0.1:
                errors.append(f"照片框水平居中误差 {horizontal_error_mm:.2f}mm，超过 0.1mm")
            if vertical_error_mm > 0.1:
                errors.append(f"照片框垂直居中误差 {vertical_error_mm:.2f}mm，超过 0.1mm")
        elif direction == "horizontal":
            left_margin = slots[0]["frame"][0]
            right_margin = paper_w - slots[1]["frame"][2]
            horizontal_error_mm = abs(left_margin - right_margin) * mm_per_px
            if horizontal_error_mm > 0.1:
                errors.append(f"左右留白误差 {horizontal_error_mm:.2f}mm，超过 0.1mm")

            for index, slot in enumerate(slots, 1):
                frame = slot["frame"]
                top_margin = frame[1]
                bottom_margin = paper_h - frame[3]
                vertical_error_mm = abs(top_margin - bottom_margin) * mm_per_px
                if vertical_error_mm > 0.1:
                    errors.append(f"照片{index}上下居中误差 {vertical_error_mm:.2f}mm，超过 0.1mm")
        else:
            for index, slot in enumerate(slots, 1):
                frame = slot["frame"]
                left_margin = frame[0]
                right_margin = paper_w - frame[2]
                horizontal_error_mm = abs(left_margin - right_margin) * mm_per_px
                if horizontal_error_mm > 0.1:
                    errors.append(f"照片{index}水平居中误差 {horizontal_error_mm:.2f}mm，超过 0.1mm")

            top_margin = slots[0]["frame"][1]
            bottom_margin = paper_h - slots[1]["frame"][3]
            vertical_error_mm = abs(top_margin - bottom_margin) * mm_per_px
            if vertical_error_mm > 0.1:
                errors.append(f"上下留白误差 {vertical_error_mm:.2f}mm，超过 0.1mm")

        for index, slot in enumerate(slots, 1):
            frame = slot["frame"]
            photo = slot["photo"]
            if frame[0] < 0 or frame[1] < 0 or frame[2] > paper_w or frame[3] > paper_h:
                errors.append(f"照片{index}框超出相纸边界")
            if frame[2] - frame[0] != photo_w or frame[3] - frame[1] != photo_h:
                errors.append(f"照片{index}框尺寸与模板不一致")
            if photo is None:
                if allow_blank_slot == index - 1:
                    continue
                errors.append(f"照片{index}未导入")
                continue
            if photo[0] < frame[0] or photo[1] < frame[1] or photo[2] > frame[2] or photo[3] > frame[3]:
                errors.append(f"照片{index}内容超出照片框，请复位或调整偏移")

        return {"ok": not errors, "errors": errors, "warnings": warnings}


