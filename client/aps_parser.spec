# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

ctk_datas = collect_data_files("customtkinter", include_py_files=False)

try:
    dnd_datas = collect_data_files("tkinterdnd2")
except Exception:
    dnd_datas = []

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # assets/ — внутри лежит WV_template.xlsm и theme/icon
        ("assets",  "assets"),
        ("locales", "locales"),
        *ctk_datas,
        *dnd_datas,
    ],
    hiddenimports=[
        *collect_submodules("customtkinter"),

        # Модули проекта
        "services",
        "services.config",
        "services.api_service",
        "services.excel_generator",

        "assets",
        "assets.theme",

        "locales",
        "locales.strings",

        "ui",
        "ui.main_window",

        "ui.dialogs",
        "ui.dialogs.auth_dialog",

        "ui.pages",
        "ui.pages.upload_page",
        "ui.pages.preview_page",
        "ui.pages.database_page",

        # tkinter
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.simpledialog",
        "tkinterdnd2",

        # openpyxl
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.styles.borders",
        "openpyxl.styles.fills",
        "openpyxl.styles.fonts",
        "openpyxl.styles.alignment",
        "openpyxl.utils",
        "openpyxl.utils.cell",

        # requests
        "requests",
        "charset_normalizer",
        "idna",
        "urllib3",
        "certifi",

        # Pillow (для логотипа)
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "PIL.PngImagePlugin",
        "PIL.IcoImagePlugin",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "cv2"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GQ-Builder 0.2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
