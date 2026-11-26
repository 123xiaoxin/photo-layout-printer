"""Saved settings and calibration offsets."""
import os
import json
import platform
import tempfile
import base64
import binascii
import copy
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from .specifications import CONFIG_FILE, FIT_MODE_CROP, LAYOUT_OPTIONS, PRINT_METHOD_OPTIONS, normalize_fit_mode
from .print_orientation import PAPER_ORIENTATION_AUTO, PAPER_ORIENTATION_OPTIONS, orient_paper_size


@dataclass(frozen=True)
class CalibrationTarget:
    printer: str
    layout: str
    paper_mm: tuple
    dpi: int


def paper_profile_key(paper_mm):
    width, height = paper_mm
    return f"paper:{round(width * 10)}x{round(height * 10)}"


MAX_DRIVER_DEVMODE_BYTES = 2 * 1024 * 1024
_MAX_DRIVER_IDENTITY_BYTES = 64 * 1024
_PAPER_PROFILE_PATTERN = re.compile(r"paper:[1-9][0-9]*x[1-9][0-9]*\Z")


def _profile_mapping(value, description, paper_keys=False):
    if not isinstance(value, dict):
        raise ValueError(f"已保存的打印机页面设置损坏：{description}应为对象，请重设此页面设置")
    for key in value:
        if (not isinstance(key, str) or not key or len(key) > 1024
                or not key.isprintable() or key != key.strip().casefold()
                or (paper_keys and not _PAPER_PROFILE_PATTERN.fullmatch(key))):
            raise ValueError(f"已保存的打印机页面设置损坏：{description}包含无效名称，请重设此页面设置")
    return value


def _validate_driver_identity(identity):
    """Check JSON shape only; native code owns driver compatibility checks."""
    def visit(value, depth=0):
        if depth > 8:
            raise ValueError("打印驱动标识层级过多")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key or len(key) > 256 or not key.isprintable():
                    raise ValueError("打印驱动标识包含无效字段")
                visit(child, depth + 1)
        elif isinstance(value, str):
            if len(value) > 16384:
                raise ValueError("打印驱动标识字段过长")
        elif type(value) in (int, float, bool):
            if type(value) is float and not math.isfinite(value):
                raise ValueError("打印驱动标识包含无效数值")
        else:
            raise ValueError("打印驱动标识只接受 JSON 对象、字符串和数值")

    if not isinstance(identity, dict) or not identity:
        raise ValueError("打印驱动标识不能为空")
    visit(identity)
    if len(json.dumps(identity, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX_DRIVER_IDENTITY_BYTES:
        raise ValueError("打印驱动标识过大")


def _decode_driver_profile(record):
    if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
        raise ValueError("已保存的打印机页面设置版本无效，请重新设置")
    encoded = record.get("devmode_base64")
    if not isinstance(encoded, str) or not encoded or len(encoded) > ((MAX_DRIVER_DEVMODE_BYTES + 2) // 3) * 4:
        raise ValueError("已保存的打印机页面设置数据无效或过大，请重新设置")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("已保存的打印机页面设置编码损坏，请重新设置") from error
    if (not payload or len(payload) > MAX_DRIVER_DEVMODE_BYTES
            or base64.b64encode(payload).decode("ascii") != encoded):
        raise ValueError("已保存的打印机页面设置数据无效，请重新设置")
    identity = record.get("driver_identity")
    _validate_driver_identity(identity)
    saved_at = record.get("saved_at")
    try:
        stamp = datetime.fromisoformat(saved_at)
        if stamp.tzinfo is None:
            raise ValueError("保存时间缺少时区")
    except (TypeError, ValueError) as error:
        raise ValueError("已保存的打印机页面设置时间无效，请重新设置") from error
    return {"devmode_bytes": payload, "driver_identity": copy.deepcopy(identity), "saved_at": saved_at}


def _driver_profile_load_errors(profiles):
    """Diagnose malformed records without erasing them during unrelated saves."""
    errors = {}
    try:
        _profile_mapping(profiles, "电脑列表")
    except ValueError as error:
        return {"": str(error)}
    for host, printers in profiles.items():
        try:
            _profile_mapping(printers, "打印机列表")
        except ValueError as error:
            errors[host] = str(error)
            continue
        for queue, papers in printers.items():
            scope = f"{host}/{queue}"
            try:
                _profile_mapping(papers, "纸张列表", paper_keys=True)
            except ValueError as error:
                errors[scope] = str(error)
                continue
            for paper, record in papers.items():
                try:
                    _decode_driver_profile(record)
                except ValueError as error:
                    errors[f"{scope}/{paper}"] = str(error)
    return errors


def write_config_file(config):
    # Replace the previous JSON only after the complete replacement has been written.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=os.path.dirname(os.path.abspath(CONFIG_FILE)),
                                         prefix=".photo-layout-", suffix=".tmp") as output:
            temporary_path = output.name
            json.dump(config, output, ensure_ascii=False, indent=2)
        os.replace(temporary_path, CONFIG_FILE)
        temporary_path = None
    finally:
        if temporary_path is not None:
            os.remove(temporary_path)


class ConfigurationMixin:
    """Behavior used by the application controller."""
    def load_config(self):
        """加载保存的配置"""
        self.printer_preferences = {}
        self.printer_aliases = {}
        self.manual_printer_name = ""
        self.legacy_selected_printer = ""
        self.driver_page_profiles = {}
        self.driver_page_profile_errors = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.driver_page_profiles = copy.deepcopy(config.get("driver_page_profiles", {}))
                self.driver_page_profile_errors = _driver_profile_load_errors(self.driver_page_profiles)

                # 恢复设置
                if 'layout_mode' in config:
                    self.layout_mode.set(config['layout_mode'])
                if 'enable_margin' in config:
                    self.enable_margin.set(config['enable_margin'])
                if 'margin_mm' in config:
                    self.margin_mm.set(config['margin_mm'])
                if 'fit_mode' in config:
                    self.fit_mode.set(normalize_fit_mode(config['fit_mode']))
                elif 'crop_mode' in config:
                    self.fit_mode.set(normalize_fit_mode(config['crop_mode']))
                if 'middle_margin_mm' in config:
                    self.middle_margin_mm.set(config['middle_margin_mm'])
                if 'show_guides' in config:
                    self.show_guides.set(config['show_guides'])
                if 'draw_cut_line' in config:
                    self.draw_cut_line.set(config['draw_cut_line'])
                if 'auto_rotate' in config:
                    self.auto_rotate.set(config['auto_rotate'])
                if 'dpi' in config:
                    self.dpi.set(int(config['dpi']))
                if 'print_method' in config and config['print_method'] in PRINT_METHOD_OPTIONS:
                    self.print_method.set(config['print_method'])
                if hasattr(self, "paper_orientation"):
                    orientation = config.get("paper_orientation", PAPER_ORIENTATION_AUTO)
                    self.paper_orientation.set(orientation if orientation in PAPER_ORIENTATION_OPTIONS else PAPER_ORIENTATION_AUTO)
                if 'selected_printer_name' in config:
                    self.selected_printer_name.set(config['selected_printer_name'])
                self.printer_preferences = config.get('printer_preferences', {})
                host = platform.node().casefold()
                if host in self.printer_preferences:
                    preference = self.printer_preferences[host]
                    self.follow_system_printer.set(preference.get("follow_default", True))
                    self.manual_printer_name = preference.get("fixed_queue", "")
                    aliases = preference.get("aliases", {})
                    if isinstance(aliases, dict):
                        self.printer_aliases = {
                            queue.strip().casefold(): alias.strip() for queue, alias in aliases.items()
                            if isinstance(queue, str) and isinstance(alias, str) and queue.strip() and alias.strip()
                        }
                elif 'printer_preferences' not in config:
                    # Older versions persisted the effective queue for both modes.
                    # At first discovery compare it with this PC's actual default.
                    self.legacy_selected_printer = self.selected_printer_name.get()
                self.printer_calibration = config.get('printer_calibration', {})
                previous_printer = self.selected_printer_name.get()
                if previous_printer and 'printer_calibration' not in config:
                    self.printer_calibration[previous_printer] = config.get('print_offsets_by_template', {})
                self.load_template_offsets()

                # 恢复照片状态
                if 'rotation_angles' in config:
                    self.rotation_angles = (config['rotation_angles'] + [0, 0])[:2]
                if 'horizontal_offset' in config:
                    self.horizontal_offset = (config['horizontal_offset'] + [0, 0])[:2]
                if 'vertical_offset' in config:
                    self.vertical_offset = (config['vertical_offset'] + [0, 0])[:2]

                print("已加载保存的配置")
        except Exception as e:
            print(f"加载配置失败: {e}")


    def save_config(self):
        """保存当前配置"""
        try:
            preferences = self.printer_preferences.copy()
            if not self.legacy_selected_printer:
                host = platform.node().casefold()
                preferences[host] = {
                    **preferences.get(host, {}),
                    "follow_default": bool(self.follow_system_printer.get()),
                    "fixed_queue": self.manual_printer_name,
                    "aliases": self.printer_aliases.copy(),
                }
            config = {
                'layout_mode': self.layout_mode.get(),
                'enable_margin': self.enable_margin.get(),
                'margin_mm': self.margin_mm.get(),
                'fit_mode': self.fit_mode.get(),
                'crop_mode': self.fit_mode.get() == FIT_MODE_CROP,
                'middle_margin_mm': self.middle_margin_mm.get(),
                'show_guides': self.show_guides.get(),
                'draw_cut_line': self.draw_cut_line.get(),
                'auto_rotate': self.auto_rotate.get(),
                'dpi': self.dpi.get(),
                'print_method': self.print_method.get(),
                'paper_orientation': self.paper_orientation.get() if hasattr(self, "paper_orientation") else PAPER_ORIENTATION_AUTO,
                'printer_calibration': getattr(self, 'printer_calibration', {}),
                'driver_page_profiles': getattr(self, 'driver_page_profiles', {}),
                'selected_printer_name': self.legacy_selected_printer or self.selected_printer_name.get(),
                'printer_preferences': preferences,
                'rotation_angles': self.rotation_angles,
                'horizontal_offset': self.horizontal_offset,
                'vertical_offset': self.vertical_offset,
            }
            if self.legacy_selected_printer and not self.printer_preferences:
                config.pop('printer_preferences')
            write_config_file(config)
            self.printer_preferences = preferences
            print("配置已保存")
            return True
        except Exception as e:
            self.last_config_error = str(e)
            print(f"保存配置失败: {e}")
            return False

    def _driver_profile_scope(self, queue, paper_mm):
        host = platform.node().strip().casefold()
        if not host or not host.isprintable():
            raise ValueError("无法识别当前电脑，不能保存或沿用打印机页面设置")
        if not isinstance(queue, str) or not queue.strip() or not queue.strip().isprintable():
            raise ValueError("请先选择 Windows 打印机")
        if len(host) > 1024 or len(queue) > 1024:
            raise ValueError("电脑或打印机名称过长")
        try:
            width, height = paper_mm
            if any(isinstance(n, bool) or not math.isfinite(n) or n <= 0 for n in (width, height)):
                raise ValueError("无效尺寸")
            key = paper_profile_key((width, height))
            if not _PAPER_PROFILE_PATTERN.fullmatch(key):
                raise ValueError("无效尺寸")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("打印机页面设置需要有效的纸张宽高和方向") from error
        return host, queue.strip().casefold(), key

    def _driver_profile_branch(self, queue, paper_mm):
        host, printer, paper = self._driver_profile_scope(queue, paper_mm)
        profiles = _profile_mapping(getattr(self, "driver_page_profiles", {}), "电脑列表")
        printers = _profile_mapping(profiles.get(host, {}), "打印机列表")
        papers = _profile_mapping(printers.get(printer, {}), "纸张列表", paper_keys=True)
        return host, printer, paper, profiles, printers, papers

    def get_driver_page_profile(self, queue, paper_mm):
        """Return this machine's exact queue/paper settings, or fail explicitly."""
        _host, _printer, paper, _profiles, _printers, papers = self._driver_profile_branch(queue, paper_mm)
        if paper not in papers:
            return None
        return _decode_driver_profile(papers[paper])

    def _persist_driver_page_profiles(self, updated):
        previous = getattr(self, "driver_page_profiles", {})
        self.driver_page_profiles = updated
        try:
            if not self.save_config():
                raise OSError(getattr(self, "last_config_error", "无法保存打印机页面设置"))
        except Exception as error:
            self.driver_page_profiles = previous
            if isinstance(error, OSError):
                raise
            raise OSError(str(error)) from error
        self.driver_page_profile_errors = _driver_profile_load_errors(updated)
        return True

    def save_driver_page_profile(self, queue, paper_mm, devmode_bytes, driver_identity):
        """Save the complete DEVMODE without interpreting private driver bytes."""
        if not isinstance(devmode_bytes, bytes) or not 0 < len(devmode_bytes) <= MAX_DRIVER_DEVMODE_BYTES:
            raise ValueError("打印机页面设置必须是有效的完整 DEVMODE 数据，且不超过 2 MiB")
        _validate_driver_identity(driver_identity)
        host, printer, paper, profiles, printers, papers = self._driver_profile_branch(queue, paper_mm)
        record = {
            "version": 1,
            "devmode_base64": base64.b64encode(devmode_bytes).decode("ascii"),
            "driver_identity": copy.deepcopy(driver_identity),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        updated = {**profiles, host: {**printers, printer: {**papers, paper: record}}}
        return self._persist_driver_page_profiles(updated)

    def reset_driver_page_profile(self, queue, paper_mm):
        """Remove only the selected profile, including a corrupt payload."""
        host, printer, paper, profiles, printers, papers = self._driver_profile_branch(queue, paper_mm)
        if paper not in papers:
            return False
        updated, new_printers, new_papers = profiles.copy(), printers.copy(), papers.copy()
        del new_papers[paper]
        if new_papers:
            new_printers[printer] = new_papers
        else:
            del new_printers[printer]
        if new_printers:
            updated[host] = new_printers
        else:
            del updated[host]
        return self._persist_driver_page_profiles(updated)

    def printer_alias_for(self, queue):
        return getattr(self, "printer_aliases", {}).get(queue.strip().casefold(), "")

    def printer_display_name(self, queue):
        alias = self.printer_alias_for(queue)
        return f"{alias} · {queue}" if alias else queue

    def set_printer_alias(self, queue, alias):
        """Persist a local display name; all printer APIs continue using the queue name."""
        key = queue.strip().casefold()
        if not key:
            raise ValueError("请先选择要命名的打印机")
        if self.legacy_selected_printer:
            raise ValueError("请刷新或重新选择打印机后再设置别名")
        name = alias.strip()
        folded = name.casefold()
        if folded == key:
            name = ""
        if name:
            if any(ch in name for ch in "\r\n\t") or not name.isprintable():
                raise ValueError("打印机别名不能包含换行或控制字符")
            real_names = {q.strip().casefold() for q in self.printer_names}
            real_names.update(self.printer_aliases)
            real_names.add(self.manual_printer_name.strip().casefold())
            if folded in real_names - {key}:
                raise ValueError("该名称已被其他 Windows 打印队列使用")
            if any(q != key and value.casefold() == folded for q, value in self.printer_aliases.items()):
                raise ValueError("该别名已被另一台打印机使用")
        previous = self.printer_aliases
        if previous.get(key, "") == name:
            return
        self.printer_aliases = previous.copy()
        if name:
            self.printer_aliases[key] = name
        else:
            self.printer_aliases.pop(key, None)
        try:
            if not self.save_config():
                raise OSError(getattr(self, "last_config_error", "无法保存打印机别名"))
        except Exception:
            self.printer_aliases = previous
            raise

    def calibration_offsets_for(self, printer_name, template, paper_mm=None):
        profiles = getattr(self, "printer_calibration", {}).get(printer_name, {})
        template_paper = LAYOUT_OPTIONS.get(template, {}).get("paper_mm")
        if paper_mm is None:
            paper_mm = template_paper
        offsets = profiles.get(paper_profile_key(paper_mm)) if paper_mm else None
        if offsets is None:
            # Legacy template offsets describe that template's original axes.
            # A newly selected output orientation must use its own paper profile.
            same_paper = (paper_mm is None or (template_paper is not None and
                          paper_profile_key(paper_mm) == paper_profile_key(template_paper)))
            offsets = profiles.get(template, {}) if same_paper else {}
        return float(offsets.get("x", 0)), float(offsets.get("y", 0))

    def load_template_offsets(self):
        layout = self.layout_mode.get()
        paper = LAYOUT_OPTIONS.get(layout, {}).get("paper_mm")
        if paper is not None:
            orientation = self.paper_orientation.get() if hasattr(self, "paper_orientation") else PAPER_ORIENTATION_AUTO
            paper = orient_paper_size(paper, orientation)
        x, y = self.calibration_offsets_for(self.selected_printer_name.get(), layout, paper)
        self.print_offset_x_mm.set(x)
        self.print_offset_y_mm.set(y)


    def save_template_offsets(self):
        base = self.get_layout_base()
        orientation = self.paper_orientation.get() if hasattr(self, "paper_orientation") else PAPER_ORIENTATION_AUTO
        paper = orient_paper_size(base["paper_mm"], orientation)
        return self.save_paper_offsets(self.selected_printer_name.get(), paper,
                                       self.print_offset_x_mm.get(), self.print_offset_y_mm.get())

    def save_paper_offsets(self, printer, paper_mm, x, y):
        """Save a calibration atomically, raising OSError if it cannot be persisted."""
        previous = getattr(self, "printer_calibration", {})
        updated = previous.copy()
        profiles = updated.get(printer, {}).copy()
        profiles[paper_profile_key(paper_mm)] = {"x": x, "y": y}
        updated[printer] = profiles
        self.printer_calibration = updated
        try:
            if not self.save_config():
                raise OSError(getattr(self, "last_config_error", "无法保存打印校准"))
        except Exception as error:
            self.printer_calibration = previous
            self.load_template_offsets()
            if isinstance(error, OSError):
                raise
            raise OSError(str(error)) from error
        self.load_template_offsets()
        return True


