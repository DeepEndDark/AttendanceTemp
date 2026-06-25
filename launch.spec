# launch.spec — PyInstaller single-exe build
# Run from project2 root:
#   python -m PyInstaller launch.spec
#
# Notes:
# - Keep console=True while debugging frozen EXE startup.
# - After server.log proves stable, switch console=False.
# - This spec intentionally FAILS the build if DPUruNet.dll is not found,
#   so you do not accidentally ship an EXE with broken fingerprint support.

from glob import glob
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None


# ── DigitalPersona SDK paths ──────────────────────────────────

DP_SDK_DOTNET_CANDIDATES = [
    r"C:\Program Files\DigitalPersona\U.are.U SDK\Windows\Lib\DotNET",
    r"C:\Program Files\Crossmatch\U.are.U SDK\Windows\Lib\DotNET",
    r"C:\Program Files (x86)\DigitalPersona\U.are.U SDK\Windows\Lib\DotNET",
    r"C:\Program Files (x86)\Crossmatch\U.are.U SDK\Windows\Lib\DotNET",
]

DP_SDK_BIN_CANDIDATES = [
    r"C:\Program Files\DigitalPersona\U.are.U SDK\Windows\Bin",
    r"C:\Program Files\Crossmatch\U.are.U SDK\Windows\Bin",
    r"C:\Program Files (x86)\DigitalPersona\U.are.U SDK\Windows\Bin",
    r"C:\Program Files (x86)\Crossmatch\U.are.U SDK\Windows\Bin",
    r"C:\Program Files\DigitalPersona\U.are.U RTE\Windows\Lib\DotNET"
    r"C:\Program Files\DigitalPersona\U.are.U SDK\Windows\Lib\x64",
    r"C:\Program Files\DigitalPersona\Bin"
]


def _find_file(filename: str, folders: list[str]) -> Path | None:
    for folder in folders:
        p = Path(folder) / filename
        if p.exists():
            return p
    return None


def _first_existing_dir(paths: list[str]) -> str | None:
    for p in paths:
        if Path(p).is_dir():
            return p
    return None


DPU_DLL = _find_file("DPUruNet.dll", DP_SDK_DOTNET_CANDIDATES)
DP_SDK_BIN = _first_existing_dir(DP_SDK_BIN_CANDIDATES)


if DPU_DLL is None:
    searched = "\n  - ".join(DP_SDK_DOTNET_CANDIDATES)
    raise FileNotFoundError(
        "DPUruNet.dll was not found. Build stopped intentionally.\n\n"
        "Install DigitalPersona/Crossmatch U.are.U SDK or add the actual "
        "DPUruNet.dll folder to DP_SDK_DOTNET_CANDIDATES in launch.spec.\n\n"
        "Searched:\n"
        f"  - {searched}"
    )


dp_binaries = [
    (str(DPU_DLL), "."),
]

if DP_SDK_BIN:
    dp_binaries.extend(
        (p, ".")
        for p in glob(str(Path(DP_SDK_BIN) / "*.dll"))
    )
else:
    raise FileNotFoundError(
        "DigitalPersona native Bin folder was not found. Build stopped intentionally.\n\n"
        "Install DigitalPersona/Crossmatch U.are.U SDK or add the actual "
        "Windows\\Bin folder to DP_SDK_BIN_CANDIDATES in launch.spec."
    )


# ── Hidden imports ────────────────────────────────────────────

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy")
    + collect_submodules("jose")
    + collect_submodules("reportlab")
    + collect_submodules("bcrypt")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_settings")
    + collect_submodules("starlette")
    + collect_submodules("fastapi")
    + collect_submodules("anyio")
    + collect_submodules("firebase_admin")
    + collect_submodules("google.cloud.firestore")
    + collect_submodules("google.auth")
    + collect_submodules("pythonnet")
    + collect_submodules("PIL")
    + [
        # Backend app package
        "app",
        "app.api",
        "app.api.v1",
        "app.api.v1.endpoints",
        "app.api.v1.endpoints.auth",
        "app.api.v1.endpoints.accounts",
        "app.api.v1.endpoints.subscriptions",
        "app.api.v1.endpoints.clients",
        "app.api.v1.endpoints.attendance",
        "app.api.v1.endpoints.items",
        "app.api.v1.endpoints.sales",
        "app.api.v1.endpoints.lockers",
        "app.api.v1.endpoints.reports",
        "app.api.v1.router",
        "app.api.dependencies",

        "app.core",
        "app.core.config",
        "app.core.firestore_client",
        "app.core.security",
        "app.core.daily_tick",
        "app.core.fingerprint",
        "app.core.report_generator",

        "app.schemas",
        "app.schemas.token",
        "app.schemas.account",
        "app.schemas.subscription",
        "app.schemas.client",
        "app.schemas.attendance",
        "app.schemas.item",
        "app.schemas.sales",
        "app.schemas.report",

        # Frontend fapp package
        "fapp",
        "fapp.api_client",
        "fapp.views",
        "fapp.views.client_display",
        "fapp.views.login_view",
        "fapp.views.enroll_view",
        "fapp.views.sales_open_view",
        "fapp.views.admin_attendance_view",
        "fapp.views.admin_sales_view",
        "fapp.views.clients_view",
        "fapp.views.client_info_view",
        "fapp.views.items_view",
        "fapp.views.subscriptions_view",
        "fapp.views.locker_view",
        "fapp.views.reports_view",
        "fapp.views.settings_view",
        "fapp.views.accounts_view",

        # pythonnet / DigitalPersona
        "clr",
        "pythonnet",
        "Python.Runtime",
        "DPUruNet",
        "System",
        "System.Drawing",
        "System.Windows.Forms",
        "System.Collections",
        "System.Collections.Generic",
        "Microsoft",
        "Microsoft.Win32",

        # Stdlib / system
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.sql.default_comparator",
        "email.mime.text",
        "email.mime.multipart",
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        "tkinter.filedialog",
        "tkinter.simpledialog",
        "multiprocessing",
        "_multiprocessing",
        "requests",
        "encodings.utf_8",
        "encodings.ascii",
        "encodings.latin_1",
        "pkg_resources",
    ]
)


# ── Analysis ──────────────────────────────────────────────────

a = Analysis(
    ["launch.py"],
    pathex=[
        ".",
        "backend",
        "frontend",
    ],
    binaries=dp_binaries,
    datas=[
        ("backend/app", "app"),
        ("backend/main.py", "."),
        ("frontend/fapp", "fapp"),
        ("frontend/frontend_main.py", "frontend_main.py"),
        ("assets/tgym.ico", "assets/tgym.ico"),
        ("assets/tgymbbg.jpg", "assets/tgymbbg.jpg")
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "numpy",
        "pandas",
    ],
    cipher=block_cipher,
    noarchive=False,
)


pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Tiger's Fitness Gym",
    icon="assets/tgym.ico",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,

    # Debugging recommendation:
    #   console=True  => see crashes live
    #   console=False => final production no-console mode
    console=False,

    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
