"""
Single-file entry point for PyInstaller --onefile build.
Starts FastAPI/uvicorn in a daemon thread, shows splash,
then opens the Tkinter staff window.
"""
import sys
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

# ── Path resolution ──────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR  = BASE_DIR

BACKEND_DIR  = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, FRONTEND_DIR)
sys.path.insert(0, BASE_DIR)

# Firebase credentials path — next to exe in production
os.environ.setdefault(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(EXE_DIR, "firebase_credentials.json"),
)

_SERVER_ERROR: list[str] = []


# ── Backend thread ───────────────────────────────────────────

def _run_server():
    try:
        log_path = os.path.join(EXE_DIR, "server.log")
        sys.stdout = open(log_path, "w", buffering=1)
        sys.stderr = sys.stdout

        import uvicorn
        from main import app as fastapi_app
        uvicorn.run(
            fastapi_app,
            host="127.0.0.1",
            port=8000,
            reload=False,
            workers=1,
            log_config=None,
            log_level="warning",
        )
    except Exception:
        import traceback
        _SERVER_ERROR.append(traceback.format_exc())


def _wait_for_backend(timeout: int = 30) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _SERVER_ERROR:
            return False
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:8000/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.4)
    return False


# ── Splash ───────────────────────────────────────────────────

class _Splash(tk.Tk):
    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        w, h = 380, 110
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#185FA5")
        tk.Label(self, text="Attendance & Sales System",
                 bg="#185FA5", fg="white",
                 font=("", 13, "bold")).pack(expand=True)
        self._lbl = tk.Label(self,
                             text="Starting server, please wait...",
                             bg="#185FA5", fg="#B5D4F4",
                             font=("", 9))
        self._lbl.pack(pady=(0, 16))

    def status(self, txt: str):
        self._lbl.config(text=txt)
        self.update()


# ── Entry point ──────────────────────────────────────────────

def main():
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    splash = _Splash()
    splash.update()

    ready = _wait_for_backend(timeout=30)
    splash.destroy()

    if not ready:
        detail = ("\n\nError:\n" + _SERVER_ERROR[0]
                  if _SERVER_ERROR
                  else "\n\nServer did not respond in 30 seconds.\n"
                       "Check that port 8000 is free and "
                       "firebase_credentials.json is present.")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Startup Failed",
                             "The backend could not start." + detail)
        root.destroy()
        sys.exit(1)

    from frontend_main import App
    App().mainloop()


if __name__ == "__main__":
    main()
