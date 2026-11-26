# Build with the workspace's dedicated Python 3.12 x64 environment.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH)
mfc = Path(sys.prefix) / 'Lib' / 'site-packages' / 'Pythonwin' / 'mfc140u.dll'
if not mfc.is_file():
    raise RuntimeError('The build machine is missing the x64 MFC runtime required by win32ui.')
datas = collect_data_files('tkinterdnd2')
datas.append((str(root / 'photo_layout' / 'assets' / 'startup.png'), 'photo_layout/assets'))
for distribution in ('Pillow', 'pywin32', 'tkinterdnd2'):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(root / 'portable_launcher.py')],
    pathex=[str(root)],
    binaries=[(str(mfc), 'pythonwin')],
    datas=datas,
    hiddenimports=['win32print', 'win32ui', 'win32con', 'pywintypes', 'PIL.ImageWin'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'pymupdf', 'fitz', 'numpy', 'matplotlib', 'IPython'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='照片排版工具', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='照片排版工具_Win10-11_64位')
