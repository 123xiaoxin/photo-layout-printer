"""Standalone Windows entry point with startup diagnostics."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description="照片排版工具")
    parser.add_argument("--self-check", type=Path, metavar="REPORT", help="检查内置环境并保存结果，不提交打印")
    args = parser.parse_args()
    directory = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    log_path = directory / "logs" / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        original_stdout, original_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = log
        try:
            print(f"\n[{datetime.now().isoformat(timespec='seconds')}] {sys.executable}")
            if args.self_check is not None:
                from photo_layout.portable_check import run_self_check
                return run_self_check(args.self_check)
            from photo_layout_printer import main as run_application
            run_application()
            return 0
        except Exception:
            traceback.print_exc()
            if args.self_check is None:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,
                    f"程序未能启动，请保留整个解压文件夹。\n错误详情已记录到：\n{log_path}",
                    "照片排版工具启动失败", 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = original_stdout, original_stderr


if __name__ == "__main__":
    raise SystemExit(main())
