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

_EYE_ICON_W, _EYE_ICON_H = 22, 16


def _draw_eye_icon(canvas: tk.Canvas, currently_visible: bool,
                   color: str = "#E8500A"):
    """
    Draws a small Material-style "eye" / "eye-off" glyph on a Canvas —
    hand-drawn with plain Tk primitives rather than a Unicode emoji glyph,
    since emoji-font rendering (and its availability at all) is
    inconsistent across Windows versions and in PyInstaller-bundled Tk,
    while this renders identically everywhere.

    currently_visible=True means the password IS currently shown, so this
    draws the "eye-off" (slashed) icon — the affordance to hide it again.
    currently_visible=False draws the plain open eye — the affordance to
    reveal it.
    """
    canvas.delete("all")
    # Almond-shaped eye outline via two smoothed curves meeting at the
    # inner/outer corners.
    canvas.create_line(2, 8, 7, 3, 15, 3, 20, 8,
                       smooth=True, fill=color, width=1.6,
                       capstyle="round")
    canvas.create_line(2, 8, 7, 13, 15, 13, 20, 8,
                       smooth=True, fill=color, width=1.6,
                       capstyle="round")
    canvas.create_oval(9, 6, 13, 10, outline=color, fill=color)
    if currently_visible:
        canvas.create_line(2, 13, 20, 3, fill=color, width=1.8,
                           capstyle="round")


class LoginView(tk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, bg="white")
        self.on_success = on_success
        self._destroyed       = False
        self._backend_reachable = False  # backend process reachable
        self._network_ok      = False    # reachable AND firebase ok — login-eligible
        self._firebase_status = "unknown"
        self._poll_job_id     = None
        self._setup_visible   = False
        self._login_in_flight = False    # True from click until the login
                                          # request resolves — see
                                          # _on_ping_result for why this
                                          # matters: the poller runs on its
                                          # own independent 5s timer and
                                          # must not touch the button while
                                          # an attempt is already running,
                                          # or a poll tick landing mid-
                                          # attempt can silently re-enable
                                          # (or re-disable) the button out
                                          # from under it.
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
        pass_row = tk.Frame(form, bg="white")
        pass_row.grid(row=3, column=0, pady=(0, 16), sticky="ew")
        self._pass = tk.Entry(pass_row, show="*", width=24)
        self._pass.pack(side="left")
        self._pass.bind("<Return>", lambda _: self._login())
        self._pass_visible = False
        self._pass_toggle = tk.Canvas(
            pass_row, width=_EYE_ICON_W, height=_EYE_ICON_H,
            bg="white", highlightthickness=0, cursor="hand2")
        self._pass_toggle.pack(side="left", padx=(6, 0))
        _draw_eye_icon(self._pass_toggle, self._pass_visible)
        self._pass_toggle.bind("<Button-1>",
                               lambda _e: self._toggle_password_visibility())

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

    def _toggle_password_visibility(self):
        self._pass_visible = not self._pass_visible
        self._pass.config(show="" if self._pass_visible else "*")
        _draw_eye_icon(self._pass_toggle, self._pass_visible)

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

        # ── Backend reachability banner ───────────────────────
        if reachable and not self._backend_reachable:
            self._backend_reachable = True
            self._net_frame.grid_remove()
            self._status.config(text="")
        elif not reachable and self._backend_reachable:
            self._backend_reachable = False
            self._net_label.config(text="⚠  Backend unreachable — retrying…")
            self._net_frame.grid()
            self._status.config(
                text="Cannot connect to server. Is the backend running?", fg="red")
        elif not reachable and not self._backend_reachable:
            dots = len(self._net_label.cget("text")) % 3 + 1
            self._net_label.config(
                text=f"⚠  Backend unreachable — retrying{'.' * dots}")

        # ── Firebase configuration banner ─────────────────────
        self._firebase_status = firebase_status
        if reachable and firebase_status == "credentials_missing":
            self._fb_frame.grid()
        elif reachable and firebase_status == "ok":
            self._fb_frame.grid_remove()
            if self._setup_visible:
                self._close_admin_setup(refreshed_ok=True)

        # ── Sign-in button ─────────────────────────────────────
        # Reachable alone isn't enough — a login attempt will still fail
        # (now as a clean 503, previously a raw 500) if Firestore itself
        # isn't usable yet. Only enable Sign In once both are true; the
        # Admin Setup link inside the Firebase banner remains the path
        # forward when credentials are missing/erroring.
        can_login = reachable and firebase_status == "ok"
        self._network_ok = can_login
        # Do NOT touch the button while a login attempt is actively in
        # flight — this poller runs on its own independent timer and a
        # tick landing mid-attempt would otherwise silently overwrite the
        # "Signing in…" disabled state set by _login(), leaving the
        # button re-enabled (or re-disabled) underneath a request that
        # hasn't resolved yet. _login_worker's own completion handlers
        # are responsible for the button once an attempt has started.
        if not self._login_in_flight:
            self._sign_in_btn.config(state="normal" if can_login else "disabled")

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
            if self._backend_reachable and self._firebase_status != "ok":
                self._status.config(
                    text="Database not configured yet. See Admin Setup above.",
                    fg="red")
            else:
                self._status.config(
                    text="Backend is not reachable. Please wait.", fg="red")
            return

        u = self._user.get().strip()
        p = self._pass.get().strip()
        if not u or not p:
            self._status.config(text="Username and password required.")
            return

        self._login_in_flight = True
        self._sign_in_btn.config(state="disabled", text="Signing in…")
        self._status.config(text="")

        # api.login() makes a real blocking HTTP request (up to the full
        # connect+read timeout if the backend is slow/unreachable). Running
        # it directly on the main thread freezes the whole window — the
        # title bar stops responding, nothing redraws — for that entire
        # duration. Run it in a background thread and marshal the result
        # back via self.after(), same pattern as the network poller.
        threading.Thread(
            target=self._login_worker, args=(u, p), daemon=True
        ).start()

    def _login_worker(self, u: str, p: str):
        try:
            api.login(u, p)
        except NetworkError:
            self.after(0, self._login_network_error)
            return
        except APIError as e:
            msg = str(e)
            self.after(0, lambda: self._login_error(msg))
            return
        except Exception as e:
            msg = f"Unexpected error: {e}"
            self.after(0, lambda: self._login_error(msg))
            return
        self.after(0, self._login_success)

    def _login_success(self):
        self._login_in_flight = False
        if self._destroyed:
            return
        self.on_success()

    def _login_network_error(self):
        self._login_in_flight = False
        if self._destroyed:
            return
        self._backend_reachable = False
        self._network_ok = False
        self._net_label.config(text="⚠  Lost connection during login — retrying…")
        self._net_frame.grid()
        self._status.config(text="Lost connection. Please wait for reconnection.", fg="red")
        self._sign_in_btn.config(state="disabled", text="Sign In")

    def _login_error(self, msg: str):
        self._login_in_flight = False
        if self._destroyed:
            return
        self._status.config(text=msg, fg="red")
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
        setup_pass_row = tk.Frame(pw_win)
        setup_pass_row.pack(padx=16, anchor="w")
        pass_entry = tk.Entry(setup_pass_row, show="*", width=26)
        pass_entry.pack(side="left")
        setup_pass_visible = {"v": False}
        setup_pass_toggle = tk.Canvas(
            setup_pass_row, width=_EYE_ICON_W, height=_EYE_ICON_H,
            bg=setup_pass_row.cget("bg"), highlightthickness=0,
            cursor="hand2")
        setup_pass_toggle.pack(side="left", padx=(6, 0))
        _draw_eye_icon(setup_pass_toggle, False)

        def toggle_setup_pass(_e=None):
            setup_pass_visible["v"] = not setup_pass_visible["v"]
            pass_entry.config(show="" if setup_pass_visible["v"] else "*")
            _draw_eye_icon(setup_pass_toggle, setup_pass_visible["v"])

        setup_pass_toggle.bind("<Button-1>", toggle_setup_pass)

        err_label = tk.Label(pw_win, text="", fg="red", font=("", 8))
        err_label.pack(pady=(6, 0))

        verify_btn = tk.Button(pw_win, text="Verify", command=lambda: None,
                  bg="#E8500A", fg="white", relief="flat",
                  padx=12, pady=6)

        def attempt():
            u, p = user_entry.get().strip(), pass_entry.get().strip()
            if not u or not p:
                err_label.config(text="Both fields are required.")
                return
            verify_btn.config(state="disabled", text="Verifying…")
            err_label.config(text="")
            threading.Thread(
                target=self._local_login_worker,
                args=(u, p, pw_win, err_label, verify_btn),
                daemon=True,
            ).start()

        verify_btn.config(command=attempt)
        pass_entry.bind("<Return>", lambda _e: attempt())
        verify_btn.pack(pady=14)

    def _local_login_worker(self, u: str, p: str, pw_win, err_label, verify_btn):
        try:
            api.local_admin_login(u, p)
        except NetworkError:
            self.after(0, lambda: self._local_login_fail(
                err_label, verify_btn, "Cannot reach server."))
            return
        except APIError as e:
            msg = str(e)
            self.after(0, lambda: self._local_login_fail(
                err_label, verify_btn, msg))
            return
        self.after(0, lambda: self._local_login_success(pw_win))

    def _local_login_fail(self, err_label, verify_btn, msg: str):
        if self._destroyed:
            return
        try:
            err_label.config(text=msg)
            verify_btn.config(state="normal", text="Verify")
        except tk.TclError:
            pass  # dialog was closed before the request finished

    def _local_login_success(self, pw_win):
        if self._destroyed:
            return
        try:
            pw_win.destroy()
        except tk.TclError:
            pass
        self._show_admin_setup_panel()

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
        threading.Thread(
            target=self._apply_fb_config_worker, args=(path,), daemon=True
        ).start()

    def _apply_fb_config_worker(self, path: str):
        try:
            api.apply_firebase_config(path)
        except NetworkError:
            self.after(0, lambda: self._fb_config_fail("Cannot reach server."))
            return
        except APIError as e:
            msg = str(e)
            self.after(0, lambda: self._fb_config_fail(msg))
            return
        self.after(0, self._fb_config_success)

    def _fb_config_fail(self, msg: str):
        if self._destroyed:
            return
        self._setup_status.config(text=msg, fg="red")

    def _fb_config_success(self):
        if self._destroyed:
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