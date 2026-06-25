"""
Client-facing display window.
Receives events from staff window via a thread-safe queue.
One banner at a time, no stacking, 5-second auto-dismiss.
"""
import os
import sys
import tkinter as tk
from datetime import datetime
import queue

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def _resource_path(relative_path: str) -> str:
    """Resolve a bundled asset path for both dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    # In dev mode, assets/ lives at the repo root: client_display.py is at
    # frontend/fapp/views/, so go up three levels to reach it.
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, relative_path)


class ClientDisplayWindow(tk.Toplevel):
    def __init__(self, master, event_queue: queue.Queue):
        super().__init__(master)
        self.title("Tiger's Fitness Gym — Client Display")
        self.configure(bg="#0D0D0D")
        self.geometry("800x480")
        self.resizable(True, True)
        self._queue = event_queue
        self._banner_job = None
        self._bg_photo = None       # keep a reference so it isn't GC'd
        self._bg_label = None
        self._icon_photo = None    # keep a reference so it isn't GC'd
        self._set_icon()
        self._build()
        self._tick_clock()
        self._poll_queue()

    def _set_icon(self):
        """
        Sets both iconbitmap (.ico, title bar) and iconphoto (PNG via PIL,
        taskbar/Alt-Tab) — iconbitmap alone is unreliable for the taskbar
        on Windows, especially this early before the Toplevel has a fully
        realized HWND. update_idletasks() forces realization first.
        """
        try:
            icon_path = _resource_path("assets/tgym.ico")
            if not os.path.exists(icon_path):
                return

            self.update_idletasks()

            try:
                self.iconbitmap(default=icon_path)
            except Exception as e:
                print(f"Client display iconbitmap failed: {e}")

            if _PIL_AVAILABLE:
                try:
                    img = Image.open(icon_path)
                    self._icon_photo = ImageTk.PhotoImage(img)
                    self.iconphoto(False, self._icon_photo)  # False: this window only
                except Exception as e:
                    print(f"Client display iconphoto fallback failed: {e}")

        except Exception as e:
            print(f"Client display icon load failed: {e}")

    def _build(self):
        # Idle screen
        self._idle_frame = tk.Frame(self, bg="#0D0D0D")
        self._idle_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._set_idle_background()

        tk.Label(self._idle_frame, text="Welcome",
                 bg="#0D0D0D", fg="#E8500A",
                 font=("", 36, "bold")).pack(expand=True, pady=(60, 0))

        tk.Label(self._idle_frame,
                 text="Place your finger on the scanner",
                 bg="#0D0D0D", fg="#666060",
                 font=("", 14)).pack(pady=(8, 0))

        self._clock_lbl = tk.Label(self._idle_frame, text="",
                                   bg="#0D0D0D", fg="#A09890",
                                   font=("", 20))
        self._clock_lbl.pack(pady=(20, 0))

        # Banner overlay
        self._banner_frame = tk.Frame(self, bg="#0D0D0D")
        self._banner_title = tk.Label(self._banner_frame, text="",
                                      font=("", 28, "bold"),
                                      bg="#0D0D0D", fg="white",
                                      wraplength=720, justify="center")
        self._banner_title.pack(expand=True, pady=(60, 8))

        self._banner_sub = tk.Label(self._banner_frame, text="",
                                    font=("", 16),
                                    bg="#0D0D0D", fg="white",
                                    wraplength=720, justify="center")
        self._banner_sub.pack(pady=(0, 20))

    def _set_idle_background(self):
        """
        Loads assets/tgymbbg.jpg as the idle screen's background, scaled to
        cover the window. Falls back to the plain dark background (already
        set) if Pillow isn't available or the file is missing — the welcome
        text and clock remain fully legible either way.
        """
        if not _PIL_AVAILABLE:
            return
        bg_path = _resource_path("assets/tgymbbg.jpg")
        if not os.path.exists(bg_path):
            return
        try:
            self._bg_image_raw = Image.open(bg_path)
        except Exception as e:
            print(f"Client display background load failed: {e}")
            return

        self._bg_label = tk.Label(self._idle_frame, bg="#0D0D0D", bd=0)
        self._bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._bg_label.lower()  # stay behind the welcome text/clock labels
        self._render_bg_for_size()
        self.bind("<Configure>", self._on_resize_bg, add="+")

    def _render_bg_for_size(self):
        if self._bg_label is None:
            return
        w = max(self.winfo_width(), 800)
        h = max(self.winfo_height(), 480)
        try:
            resized = self._bg_image_raw.copy()
            resized = resized.resize((w, h), Image.LANCZOS)
            self._bg_photo = ImageTk.PhotoImage(resized)
            self._bg_label.configure(image=self._bg_photo)
        except Exception as e:
            print(f"Client display background render failed: {e}")

    def _on_resize_bg(self, event=None):
        # Debounce — only re-render after resizing settles for 150ms
        if getattr(self, "_resize_job", None):
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._render_bg_for_size)

    def _tick_clock(self):
        self._clock_lbl.config(text=datetime.now().strftime("%I:%M:%S %p"))
        self.after(1000, self._tick_clock)

    def _poll_queue(self):
        try:
            while True:
                event = self._queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_event(self, event: dict):
        etype = event.get("type")
        # Cancel existing banner timer immediately (no stacking)
        if self._banner_job:
            self.after_cancel(self._banner_job)
            self._banner_job = None

        # clear → back to idle
        if etype == "clear":
            self._show_idle()
            return

        configs = {
            "scanning":     ("#FF9A5C", "white", "#0D0D0D"),   # soft blue-purple
            "time_in":      ("#1D9E75", "white", "#0a3d2e"),
            "time_out":     ("#E8500A", "white", "#BF3D00"),
            "expiry_warn":  ("#BA7517", "white", "#3d2800"),
            "expired":      ("#C0392B", "white", "#3d0a0a"),
            "no_match":     ("#E67E22", "white", "#3d1f00"),
            "scanner_error":("#E67E22", "white", "#3d1f00"),
        }

        accent, fg, bg = configs.get(etype, ("#E8500A", "white", "#BF3D00"))
        title = event.get("title", "")
        subtitle = event.get("subtitle", "")

        # Show banner
        self._banner_frame.configure(bg=bg)
        self._banner_title.configure(text=title, bg=bg, fg=accent)
        self._banner_sub.configure(text=subtitle, bg=bg, fg=fg)
        self._banner_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._idle_frame.place_forget()

        # scanning holds until result overwrites it — no auto-dismiss
        if etype == "scanning":
            return

        # All other events auto-dismiss after 5 s
        self._banner_job = self.after(5000, self._show_idle)

    def _show_idle(self):
        self._banner_job = None
        self._banner_frame.place_forget()
        self._idle_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    def clear_banner(self):
        """Called by scanner on new scan attempt."""
        if self._banner_job:
            self.after_cancel(self._banner_job)
            self._banner_job = None
        self._show_idle()