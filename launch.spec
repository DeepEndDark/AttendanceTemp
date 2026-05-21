# launch.spec — PyInstaller single-exe build
# Run from project2 root:  python -m PyInstaller launch.spec

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy")   # kept for firebase-admin internals
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
    + [
        # Backend app package — lands at root/app
        "app", "app.api", "app.api.v1", "app.api.v1.endpoints",
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
        "app.core", "app.core.config", "app.core.firestore_client",
        "app.core.security", "app.core.daily_tick",
        "app.core.fingerprint", "app.core.report_generator",
        "app.schemas", "app.schemas.token", "app.schemas.account",
        "app.schemas.subscription", "app.schemas.client",
        "app.schemas.attendance", "app.schemas.item",
        "app.schemas.sales", "app.schemas.report",
        # Frontend fapp package — lands at root/fapp
        "fapp", "fapp.api_client",
        "fapp.views", "fapp.views.client_display",
        "fapp.views.login_view", "fapp.views.enroll_view",
        "fapp.views.sales_open_view",
        "fapp.views.admin_attendance_view",
        "fapp.views.admin_sales_view",
        "fapp.views.clients_view", "fapp.views.items_view",
        "fapp.views.subscriptions_view", "fapp.views.locker_view",
        "fapp.views.reports_view", "fapp.views.settings_view",
        "fapp.views.accounts_view",
        # Stdlib
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.sql.default_comparator",
        "email.mime.text", "email.mime.multipart",
        "tkinter", "tkinter.ttk", "tkinter.messagebox",
        "tkinter.filedialog", "tkinter.simpledialog",
        "multiprocessing", "_multiprocessing",
    ]
)

a = Analysis(
    ["launch.py"],
    pathex=["backend", "frontend"],
    binaries=[],
    datas=[
        ("backend/app",          "app"),
        ("backend/main.py",      "."),
        ("frontend/fapp",        "fapp"),
        ("frontend/frontend_main.py", "frontend_main.py"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="AttendanceSalesSystem",
    debug=False, strip=False, upx=False,
    runtime_tmpdir=None, console=False,
    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None, codesign_identity=None,
    entitlements_file=None,
)
