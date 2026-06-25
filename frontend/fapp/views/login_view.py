"""
login_view.py

- Polls /health every 5 seconds via api.ping() to show live backend status.
- Sign In is disabled until the backend process is reachable.
- If Firebase credentials are missing, a collapsed "Admin Setup" link
  appears. Clicking it prompts for the local-admin credential (which works
  even without Firestore) and reveals a Firebase config upload panel.
"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from fapp.api_client import api, APIError, NetworkError
from fapp.views.admin_attendance_view import set_window_icon

POLL_INTERVAL_MS = 5_000   # 5 seconds between pings


class LoginView(tk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, bg="white")
        self.on_success = on_success
        self._destroyed       = False
        self._network_ok      = False   # backend process reachable
        self._firebase_status = "unknown"
        self._poll_job_id     = None
        self._setup_visible   = False
        self._build()
        self._start_network_poller()

    # ── UI ────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg="#E8500A", height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        tk.Label(header, text="Tiger's Fitness Gym",
                 bg="#E8500A", fg="white",
                 font=("", 14, "bold")).pack(expand=True)

        # Network status banner — hidden when backend is reachable
        self._net_frame = tk.Frame(self, bg="#7C2D12", height=28)
        self._net_frame.grid(row=1, column=0, sticky="ew")
        self._net_frame.grid_propagate(False)
        self._net_label = tk.Label(
            self._net_frame, text="⚠  Waiting for backend…",
            bg="#7C2D12", fg="#FED7AA", font=("", 9))
        self._net_label.pack(expand=True)

        # Firebase-missing banner — shown only when backend is up but
        # Firestore credentials are missing
        self._fb_frame = tk.Frame(self, bg="#92400E", height=26)
        self._fb_frame.grid(row=2, column=0, sticky="ew")
        self._fb_frame.grid_propagate(False)
        self._fb_frame.grid_remove()
        fb_inner = tk.Frame(self._fb_frame, bg="#92400E")
        fb_inner.pack(expand=True)
        tk.Label(fb_inner, text="⚠  Database not configured.",
                 bg="#92400E", fg="#FEF3C7", font=("", 9)).pack(side="left")
        self._setup_link = tk.Label(
            fb_inner, text="  Admin Setup",
            bg="#92400E", fg="#FED7AA", font=("", 9, "underline"),
            cursor="hand2")
        self._setup_link.pack(side="left")
        self._setup_link.bind("<Button-1>", lambda _e: self._open_admin_setup())

        tk.Label(self, text="Sign in to continue",
                 font=("", 10), fg="gray",
                 bg="white").grid(row=3, column=0, pady=(24, 4))

        form = tk.Frame(self, bg="white", padx=30, pady=20,
                        relief="groove", bd=1)
        form.grid(row=4, column=0, ipadx=20)

        tk.Label(form, text="Username", bg="white",
                 anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        self._user = tk.Entry(form, width=28)
        self._user.grid(row=1, column=0, pady=(0, 12))
        self._user.focus()

        tk.Label(form, text="Password", bg="white",
                 anchor="w").grid(row=2, column=0, sticky="w", pady=4)
        self._pass = tk.Entry(form, show="*", width=28)
        self._pass.grid(row=3, column=0, pady=(0, 16))
        self._pass.bind("<Return>", lambda _: self._login())

        self._sign_in_btn = tk.Button(
            form, text="Sign In", command=self._login,
            bg="#E8500A", fg="white", relief="flat",
            padx=16, pady=8, width=22, state="disabled")
        self._sign_in_btn.grid(row=4, column=0)

        self._status = tk.Label(self, text="", fg="red",
                                bg="white", font=("", 9))
        self._status.grid(row=5, column=0, pady=10)

        # Admin setup panel — built but hidden until requested
        self._setup_panel = None  # built lazily in _build_setup_panel()

    # ── Network / Firebase polling ─────────────────────────────

    def _start_network_poller(self):
        t = threading.Thread(target=self._ping_worker, daemon=True)
        t.start()

    def _ping_worker(self):
        reachable, firebase_status = api.ping()
        if not self._destroyed:
            self.after(0, lambda: self._on_ping_result(reachable, firebase_status))

    def _on_ping_result(self, reachable: bool, firebase_status: str):
        if self._destroyed:
            return

        if reachable and not self._network_ok:
            self._network_ok = True
            self._net_frame.grid_remove()
            self._sign_in_btn.config(state="normal")
            self._status.config(text="")
        elif not reachable and self._network_ok:
            self._network_ok = False
            self._net_label.config(text="⚠  Backend unreachable — retrying…")
            self._net_frame.grid()
            self._sign_in_btn.config(state="disabled")
            self._status.config(
                text="Cannot connect to server. Is the backend running?", fg="red")
        elif not reachable and not self._network_ok:
            dots = len(self._net_label.cget("text")) % 3 + 1
            self._net_label.config(
                text=f"⚠  Backend unreachable — retrying{'.' * dots}")

        self._firebase_status = firebase_status
        if reachable and firebase_status == "credentials_missing":
            self._fb_frame.grid()
        elif reachable and firebase_status == "ok":
            self._fb_frame.grid_remove()
            if self._setup_visible:
                self._close_admin_setup(refreshed_ok=True)

        self._poll_job_id = self.after(POLL_INTERVAL_MS, self._start_network_poller)

    def destroy(self):
        self._destroyed = True
        if self._poll_job_id:
            try:
                self.after_cancel(self._poll_job_id)
            except Exception:
                pass
        super().destroy()

    # ── Normal login ─────────────────────────────────────────

    def _login(self):
        if not self._network_ok:
            self._status.config(text="Backend is not reachable. Please wait.", fg="red")
            return

        u = self._user.get().strip()
        p = self._pass.get().strip()
        if not u or not p:
            self._status.config(text="Username and password required.")
            return

        self._sign_in_btn.config(state="disabled", text="Signing in…")
        self._status.config(text="")
        self.update_idletasks()

        try:
            api.login(u, p)
            self.on_success()
        except NetworkError:
            self._network_ok = False
            self._net_label.config(text="⚠  Lost connection during login — retrying…")
            self._net_frame.grid()
            self._status.config(text="Lost connection. Please wait for reconnection.", fg="red")
            self._sign_in_btn.config(state="disabled", text="Sign In")
        except APIError as e:
            self._status.config(text=str(e), fg="red")
            self._sign_in_btn.config(state="normal", text="Sign In")
        except Exception as e:
            self._status.config(text=f"Unexpected error: {e}", fg="red")
            self._sign_in_btn.config(state="normal", text="Sign In")

    # ── Admin Setup flow ─────────────────────────────────────

    def _open_admin_setup(self):
        """Prompt for the local-admin credential before showing the panel."""
        pw_win = tk.Toplevel(self)
        pw_win.title("Admin Setup — Verify")
        pw_win.geometry("320x200")
        set_window_icon(pw_win)
        pw_win.transient(self)
        pw_win.grab_set()

        tk.Label(pw_win, text="Enter admin credentials to configure Firebase",
                 wraplength=280, justify="left").pack(pady=(16, 10), padx=16)

        tk.Label(pw_win, text="Username").pack(anchor="w", padx=16)
        user_entry = tk.Entry(pw_win, width=30)
        user_entry.pack(padx=16)
        user_entry.focus()

        tk.Label(pw_win, text="Password").pack(anchor="w", padx=16, pady=(8, 0))
        pass_entry = tk.Entry(pw_win, show="*", width=30)
        pass_entry.pack(padx=16)

        err_label = tk.Label(pw_win, text="", fg="red", font=("", 8))
        err_label.pack(pady=(6, 0))

        def attempt():
            u, p = user_entry.get().strip(), pass_entry.get().strip()
            if not u or not p:
                err_label.config(text="Both fields are required.")
                return
            try:
                api.local_admin_login(u, p)
            except NetworkError:
                err_label.config(text="Cannot reach server.")
                return
            except APIError as e:
                err_label.config(text=str(e))
                return
            pw_win.destroy()
            self._show_admin_setup_panel()

        pass_entry.bind("<Return>", lambda _e: attempt())
        tk.Button(pw_win, text="Verify", command=attempt,
                  bg="#E8500A", fg="white", relief="flat",
                  padx=12, pady=6).pack(pady=14)

    def _show_admin_setup_panel(self):
        if self._setup_panel is not None:
            self._setup_panel.destroy()

        self._setup_panel = tk.Frame(self, bg="#FFF7ED", padx=20, pady=16,
                                     relief="groove", bd=1)
        self._setup_panel.grid(row=6, column=0, pady=(0, 16), padx=20, sticky="ew")

        tk.Label(self._setup_panel, text="Firebase Setup",
                 font=("", 11, "bold"), bg="#FFF7ED").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._fb_path_var = tk.StringVar()
        tk.Entry(self._setup_panel, textvariable=self._fb_path_var,
                 width=34, state="readonly").grid(row=1, column=0, sticky="ew")
        tk.Button(self._setup_panel, text="Browse…",
                  command=self._browse_fb_file,
                  relief="flat", bg="white", padx=10).grid(row=1, column=1, padx=(8, 0))

        self._setup_status = tk.Label(self._setup_panel, text="",
                                      bg="#FFF7ED", font=("", 8), anchor="w")
        self._setup_status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 8))

        btn_row = tk.Frame(self._setup_panel, bg="#FFF7ED")
        btn_row.grid(row=3, column=0, columnspan=2, sticky="w")
        tk.Button(btn_row, text="Apply Configuration",
                  command=self._apply_fb_config,
                  bg="#E8500A", fg="white", relief="flat",
                  padx=12, pady=6).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="Cancel",
                  command=lambda: self._close_admin_setup(refreshed_ok=False),
                  relief="flat", bg="white", padx=12, pady=6).pack(side="left")

        self._setup_visible = True

    def _browse_fb_file(self):
        path = filedialog.askopenfilename(
            title="Select Firebase service-account JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self._fb_path_var.set(path)
            self._setup_status.config(text="")

    def _apply_fb_config(self):
        path = self._fb_path_var.get().strip()
        if not path:
            self._setup_status.config(text="Please select a file first.", fg="red")
            return
        self._setup_status.config(text="Uploading and verifying…", fg="gray")
        self.update_idletasks()
        try:
            api.apply_firebase_config(path)
        except NetworkError:
            self._setup_status.config(text="Cannot reach server.", fg="red")
            return
        except APIError as e:
            self._setup_status.config(text=str(e), fg="red")
            return

        self._setup_status.config(text="✔ Firebase configured successfully.", fg="#0F6E56")
        self.after(1200, lambda: self._close_admin_setup(refreshed_ok=True))

    def _close_admin_setup(self, refreshed_ok: bool):
        if self._setup_panel is not None:
            self._setup_panel.destroy()
            self._setup_panel = None
        self._setup_visible = False
        if refreshed_ok:
            self._fb_frame.grid_remove()
            self._status.config(text="Database configured. You can now sign in.", fg="#0F6E56")