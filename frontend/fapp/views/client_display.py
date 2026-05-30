"""
Client-facing display window.
Receives events from staff window via a thread-safe queue.
One banner at a time, no stacking, 5-second auto-dismiss.
"""
import tkinter as tk
from datetime import datetime
import queue


class ClientDisplayWindow(tk.Toplevel):
    def __init__(self, master, event_queue: queue.Queue):
        super().__init__(master)
        self.title("Client Display")
        self.configure(bg="#1a1a2e")
        self.geometry("800x480")
        self.resizable(True, True)
        self._queue = event_queue
        self._banner_job = None
        self._build()
        self._tick_clock()
        self._poll_queue()

    def _build(self):
        # Idle screen
        self._idle_frame = tk.Frame(self, bg="#1a1a2e")
        self._idle_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        tk.Label(self._idle_frame, text="Welcome",
                 bg="#1a1a2e", fg="#185FA5",
                 font=("", 36, "bold")).pack(expand=True, pady=(60, 0))

        tk.Label(self._idle_frame,
                 text="Place your finger on the scanner",
                 bg="#1a1a2e", fg="#5F5E5A",
                 font=("", 14)).pack(pady=(8, 0))

        self._clock_lbl = tk.Label(self._idle_frame, text="",
                                   bg="#1a1a2e", fg="#B4B2A9",
                                   font=("", 20))
        self._clock_lbl.pack(pady=(20, 0))

        # Banner overlay
        self._banner_frame = tk.Frame(self, bg="#1a1a2e")
        self._banner_title = tk.Label(self._banner_frame, text="",
                                      font=("", 28, "bold"),
                                      bg="#1a1a2e", fg="white",
                                      wraplength=720, justify="center")
        self._banner_title.pack(expand=True, pady=(60, 8))

        self._banner_sub = tk.Label(self._banner_frame, text="",
                                    font=("", 16),
                                    bg="#1a1a2e", fg="white",
                                    wraplength=720, justify="center")
        self._banner_sub.pack(pady=(0, 20))

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
            "scanning":     ("#7B8CDE", "white", "#1a1a2e"),   # soft blue-purple
            "time_in":      ("#1D9E75", "white", "#0a3d2e"),
            "time_out":     ("#185FA5", "white", "#0a2240"),
            "expiry_warn":  ("#BA7517", "white", "#3d2800"),
            "expired":      ("#C0392B", "white", "#3d0a0a"),
            "no_match":     ("#E67E22", "white", "#3d1f00"),
            "scanner_error":("#E67E22", "white", "#3d1f00"),
        }

        accent, fg, bg = configs.get(etype, ("#185FA5", "white", "#0a2240"))
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