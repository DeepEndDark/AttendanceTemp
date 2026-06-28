"""
Single-file entry point for PyInstaller --onefile build.
Starts FastAPI/uvicorn in a daemon thread, shows splash,
then opens the Tkinter staff window.
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox


# ── Path resolution ──────────────────────────────────────────

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR = os.path.dirname(sys.executable)

    # In frozen build, datas are copied directly into _MEIPASS:
    #   app/
    #   fapp/
    #   main.py
    #   frontend_main.py
    BACKEND_DIR = BASE_DIR
    FRONTEND_DIR = BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BASE_DIR

    BACKEND_DIR = os.path.join(BASE_DIR, "backend")
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


for p in (BACKEND_DIR, FRONTEND_DIR, BASE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# Firebase credentials path — next to exe in production
os.environ.setdefault(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(EXE_DIR, "firebase_credentials.json"),
)


_SERVER_ERROR: list[str] = []


# ── Backend thread ───────────────────────────────────────────

def _run_server():
    """
    Runs uvicorn in a daemon thread.

    IMPORTANT: this used to do `sys.stdout = log_file` / `sys.stderr = log_file`
    — but those are process-wide module attributes, not thread-local. Once
    reassigned here, EVERY print() from every other thread in the process —
    including the Tkinter main thread and any frontend debugging output —
    silently redirects into server.log too, which is confusing when trying
    to debug frontend-side issues (e.g. icon/background loading) with
    console=True, since those prints never reach the console at all.

    Instead, write directly to the log file object without touching the
    global stdout/stderr, and point uvicorn's own logging at the same file
    via a dedicated logging config rather than relying on print()'s default
    destination.
    """
    log_file = None

    try:
        log_path = os.path.join(EXE_DIR, "server.log")

        log_file = open(
            log_path,
            "w",
            buffering=1,
            encoding="utf-8",
            errors="replace",
        )

        def _log(msg: str):
            log_file.write(msg + "\n")
            log_file.flush()

        _log("=== Backend starting ===")
        _log(f"BASE_DIR={BASE_DIR}")
        _log(f"EXE_DIR={EXE_DIR}")
        _log(f"BACKEND_DIR={BACKEND_DIR}")
        _log(f"FRONTEND_DIR={FRONTEND_DIR}")
        _log(f"FIREBASE_CREDENTIALS_PATH={os.environ.get('FIREBASE_CREDENTIALS_PATH')}")
        _log(f"sys.path={sys.path}")

        import uvicorn
        from main import app as fastapi_app

        # Route uvicorn's own loggers to the same file explicitly, instead
        # of relying on a global stdout/stderr swap that leaks into every
        # other thread in the process.
        uvicorn_log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                },
            },
            "handlers": {
                "server_log_file": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": log_file,
                },
            },
            "root": {
                "handlers": ["server_log_file"],
                "level": "WARNING",
            },
        }

        uvicorn.run(
            fastapi_app,
            host="127.0.0.1",
            port=8000,
            reload=False,
            workers=1,
            log_config=uvicorn_log_config,
            log_level="warning",
        )

    except Exception:
        import traceback

        err = traceback.format_exc()
        _SERVER_ERROR.append(err)

        try:
            with open(
                os.path.join(EXE_DIR, "server.log"),
                "a",
                encoding="utf-8",
                errors="replace",
            ) as f:
                f.write("\n--- STARTUP ERROR ---\n")
                f.write(err)
        except Exception:
            pass

    finally:
        try:
            if log_file:
                log_file.flush()
        except Exception:
            pass


def _wait_for_backend(timeout: int = 30) -> bool:
    import urllib.request

    deadline = time.time() + timeout

    while time.time() < deadline:
        if _SERVER_ERROR:
            return False

        try:
            urllib.request.urlopen(
                "http://127.0.0.1:8000/health",
                timeout=1,
            )
            return True

        except Exception:
            time.sleep(0.4)

    return False


def _set_windows_app_id():
    """
    Windows groups taskbar entries by "Application User Model ID". Without
    an explicit one, a PyInstaller-frozen Python app can get grouped under
    the generic Python identity and show the Python icon instead of ours.
    Must be called before any Tk window is created.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "tigersfitnessgym.attendance.sales.v1"
            )
        except Exception:
            pass


# ── Splash ───────────────────────────────────────────────────

class _Splash(tk.Tk):
    def __init__(self):
        super().__init__()

        self.overrideredirect(True)

        w, h = 380, 110
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#185FA5")

        tk.Label(
            self,
            text="Attendance & Sales System",
            bg="#185FA5",
            fg="white",
            font=("", 13, "bold"),
        ).pack(expand=True)

        self._lbl = tk.Label(
            self,
            text="Starting server, please wait...",
            bg="#185FA5",
            fg="#B5D4F4",
            font=("", 9),
        )

        self._lbl.pack(pady=(0, 16))

    def status(self, txt: str):
        self._lbl.config(text=txt)
        self.update()


# ── Entry point ──────────────────────────────────────────────

def main():
    _set_windows_app_id()

    t = threading.Thread(
        target=_run_server,
        daemon=True,
        name="BackendServer",
    )
    t.start()

    splash = _Splash()

    # _wait_for_backend() is a real blocking loop (up to 30s, sleeping
    # 0.4s between polls). Calling it directly on the main thread — as a
    # previous version of this function did — leaves the splash window's
    # Tk event loop not running for that whole duration: no redraws, no
    # responding to clicks/drags, which Windows reports as "Not Responding"
    # even though the app is working fine in the background.
    #
    # Instead, run the wait in a background thread and poll its result
    # via splash.after(), so splash.mainloop() keeps the window responsive
    # the entire time.
    result: dict[str, bool | None] = {"ready": None}

    def wait_worker():
        result["ready"] = _wait_for_backend(timeout=30)

    threading.Thread(
        target=wait_worker,
        daemon=True,
        name="BackendWaiter",
    ).start()

    def poll_backend_result():
        if result["ready"] is None:
            splash.after(100, poll_backend_result)
            return

        ready = result["ready"]

        try:
            splash.destroy()
        except Exception:
            pass

        if not ready:
            if _SERVER_ERROR:
                detail = "\n\nError:\n" + _SERVER_ERROR[0]
            else:
                detail = (
                    "\n\nServer did not respond in 30 seconds.\n"
                    "Check that port 8000 is free and "
                    "firebase_credentials.json is present.\n\n"
                    f"See server.log in:\n{EXE_DIR}"
                )

            root = tk.Tk()
            root.withdraw()

            messagebox.showerror(
                "Startup Failed",
                "The backend could not start." + detail,
            )

            root.destroy()
            sys.exit(1)

        from frontend_main import App

        App().mainloop()

    splash.after(100, poll_backend_result)
    splash.mainloop()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()