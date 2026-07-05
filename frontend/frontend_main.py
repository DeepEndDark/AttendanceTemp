"""
Staff-facing main Tkinter window.
Header (username + role) + sidebar navigation + content area.
Shares a thread-safe queue with the client display window.
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import os
import sys

def resource_path(relative_path: str) -> str:
    """Resolve a bundled asset path for both dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    # frontend_main.py lives at frontend/; assets/ is one level up at the
    # repo root, matching how launch.spec bundles ("assets/...", ...).
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)

from fapp.api_client import api, APIClient, APIError, NetworkError
from fapp.views.client_display import ClientDisplayWindow


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tiger's Fitness Gym")
        self.geometry("1100x680")
        self.minsize(860, 540)
        self._display_queue: queue.Queue = queue.Queue()
        self._att_queue:     queue.Queue = queue.Queue()
        self._apply_window_icon()

        self._client_win: ClientDisplayWindow | None = None
        self._current_view = None
        self._view_cache: dict = {}
        self._nav_buttons: dict = {}
        self._view_classes: dict = {}
        self._scanner_stop = threading.Event()
        self._show_login()

    def _apply_window_icon(self):
        """
        Sets both the title-bar icon (iconbitmap, .ico-based) and the
        taskbar/Alt-Tab icon (iconphoto, PNG-based via PIL).

        These are two separate Windows mechanisms — iconbitmap alone is
        not reliable for the taskbar entry, especially when called before
        the window has a fully realized HWND. update_idletasks() forces
        that realization first, and iconphoto is set as a true fallback/
        supplement so the taskbar consistently picks up the icon even when
        iconbitmap's effect is limited to the title bar.
        """
        try:
            icon_path = os.path.normpath(resource_path("assets/tgym.ico"))
            if not os.path.exists(icon_path):
                return

            # Force the window to realize its HWND before requesting an
            # icon change — setting it too early is the main reason this
            # silently fails to reach the taskbar on Windows.
            self.update_idletasks()

            try:
                self.iconbitmap(default=icon_path)
            except Exception as e:
                print(f"iconbitmap failed: {e}")

            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(img)  # keep a reference
                self.iconphoto(True, self._icon_photo)
            except Exception as e:
                print(f"iconphoto fallback failed: {e}")

        except Exception as e:
            print(f"Window icon load failed: {e}")


    # ── Login ────────────────────────────────────────────────

    def _show_login(self):
        self._clear()
        from fapp.views.login_view import LoginView
        LoginView(self, on_success=self._show_main).pack(
            fill="both", expand=True)

    # ── Main shell ───────────────────────────────────────────

    def _show_main(self):
        self._clear()
        self._view_cache.clear()
        self.title(f"Tiger's Fitness Gym — {api.account_name}")

        # Launch client display window
        self._client_win = ClientDisplayWindow(self, self._display_queue)
        self._client_win.protocol("WM_DELETE_WINDOW",
                                  lambda: None)  # prevent closing independently
        self._scanner_stop.clear()
        threading.Thread(target=self._scanner_loop, daemon=True).start()

        # Redirect to login on any 401 — token expired or invalidated
        APIClient.set_unauthorized_handler(
            lambda: self.after(0, self._on_unauthorized)
        )

        # Show a persistent banner when requests can't reach the backend
        APIClient.set_network_error_handler(
            lambda msg: self.after(0, lambda: self._show_network_banner(msg))
        )

        # ── Network banner (hidden by default) ────────────────
        self._net_banner = tk.Frame(self, bg="#7C2D12", height=28)
        self._net_banner.pack_propagate(False)
        self._net_banner_label = tk.Label(
            self._net_banner, text="",
            bg="#7C2D12", fg="#FED7AA", font=("", 9))
        self._net_banner_label.pack(expand=True)
        self._net_banner_visible = False
        self._net_banner_hide_id = None

        # ── Header ───────────────────────────────────────────
        header = tk.Frame(self, bg="#E8500A", height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        self._header_widget = header  # used to re-insert the banner above it

        tk.Label(header, text="  Tiger's Fitness Gym",
                 bg="#E8500A", fg="white",
                 font=("", 12, "bold")).pack(side="left", padx=4)

        role_color = "#FF6B2B" if api.is_admin else "#FFB347"
        tk.Label(header,
                 text=f"{api.account_name}  "
                      f"[{api.account_type.upper()}]",
                 bg="#E8500A", fg=role_color,
                 font=("", 9)).pack(side="right", padx=4)

        tk.Button(header, text="Logout",
                  bg="#E8500A", fg="#FFD4B0",
                  relief="flat", cursor="hand2",
                  activebackground="#BF3D00",
                  activeforeground="white",
                  command=self._logout,
                  padx=10).pack(side="right", pady=8, padx=12)

        # ── Body ─────────────────────────────────────────────
        body = tk.Frame(self)
        body.pack(fill="both", expand=True)

        self._sidebar = tk.Frame(body, bg="#0D0D0D", width=176)
        self._sidebar.pack(fill="y", side="left")
        self._sidebar.pack_propagate(False)

        self._content = tk.Frame(body, bg="white")
        self._content.pack(fill="both", expand=True, side="left")

        self._build_nav()

    def _build_nav(self):
        from fapp.views.enroll_view import EnrollView
        from fapp.views.sales_open_view import SalesOpenView
        from fapp.views.admin_attendance_view import AdminAttendanceView
        from fapp.views.admin_sales_view import AdminSalesView
        from fapp.views.clients_view import ClientsView
        from fapp.views.items_view import ItemsView
        from fapp.views.subscriptions_view import SubscriptionsView
        from fapp.views.locker_view import LockerView
        from fapp.views.reports_view import ReportsView
        from fapp.views.settings_view import SettingsView
        from fapp.views.accounts_view import AccountsView

        if api.is_admin:
            nav_items = [
                ("Attendance Logs",    AdminAttendanceView),
                ("Sales Logs",         AdminSalesView),
                ("Client List",        ClientsView),
                ("Item Catalogue",     ItemsView),
                ("Subscription Plans", SubscriptionsView),
                ("Locker Management",  LockerView),
                ("Reports",            ReportsView),
                ("Settings",           SettingsView),
                ("Accounts",           AccountsView),
            ]
        else:
            nav_items = [
                ("Enroll Client",     EnrollView),
                ("Sales",             SalesOpenView),
                ("Locker Management", LockerView),
            ]

        tk.Label(self._sidebar, text="NAVIGATION",
                 bg="#0D0D0D", fg="#666060",
                 font=("", 8), pady=12).pack(fill="x", padx=12)

        for label, ViewClass in nav_items:
            btn = tk.Button(
                self._sidebar, text=label,
                bg="#0D0D0D", fg="#A09890",
                relief="flat", anchor="w",
                padx=14, pady=10,
                activebackground="#E8500A",
                activeforeground="white",
                cursor="hand2",
                command=lambda l=label: self._switch_view(l),
            )
            btn.pack(fill="x")
            self._nav_buttons[label] = btn
            self._view_classes[label] = ViewClass

        # Show first view automatically
        first = nav_items[0][0]
        self._switch_view(first)

    def _switch_view(self, label: str):
        for lbl, btn in self._nav_buttons.items():
            btn.config(
                bg="#E8500A" if lbl == label else "#0D0D0D",
                fg="white" if lbl == label else "#A09890",
            )

        if self._current_view:
            self._current_view.pack_forget()

        if label not in self._view_cache:
            ViewClass = self._view_classes[label]
            import inspect
            sig = inspect.signature(ViewClass.__init__)
            kwargs = {"display_queue": self._display_queue}
            if "att_queue" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            ):
                kwargs["att_queue"] = self._att_queue
            view = ViewClass(self._content, **kwargs)
            view.pack(fill="both", expand=True)
            self._view_cache[label] = view
        else:
            view = self._view_cache[label]
            view.pack(fill="both", expand=True)

        self._current_view = view

    def _scanner_loop(self):
        """
        Stage 1 — /finger-touch: blocks silently up to 30 s.
                   Client display stays on idle. No banner shown.
        Stage 2 — show "Reading..." banner only after finger is detected.
        Stage 3 — /scan: FID already in queue, returns fast with result.
        """
        import time as _time

        net_backoff = 0  # seconds to wait after a network failure

        while not self._scanner_stop.is_set():

            if net_backoff:
                _time.sleep(net_backoff)
                net_backoff = 0

            # Stage 1 — wait for physical touch, client stays idle
            try:
                touched, scanner_available = api.finger_touch()
            except NetworkError:
                # Backend unreachable — banner already fired by api_client.
                # Back off and retry; do NOT treat this as a 401/session issue.
                self._display_queue.put({"type": "clear"})
                net_backoff = 10
                continue
            except APIError as e:
                # Non-2xx HTTP response (401 already triggers the
                # session-expired redirect via _raise() -> _on_unauthorized;
                # anything else — e.g. a transient 500/503 — back off
                # briefly and retry rather than silently killing this
                # thread, which would stop the scanner forever with no
                # indication anything went wrong.
                if e.status_code != 401:
                    self.after(0, lambda msg=str(e): self._show_network_banner(
                        f"Scanner error: {msg}"))
                self._display_queue.put({"type": "clear"})
                net_backoff = 5
                continue

            if self._scanner_stop.is_set():
                break

            # A successful call means connectivity is back — clear any banner
            self.after(0, self._hide_network_banner)

            if not touched:
                if not scanner_available:
                    # Scanner unavailable — back off 5s before retrying
                    _time.sleep(5.0)
                # else: normal 30s timeout — retry immediately
                continue

            # Stage 2 — finger detected, show "Reading..." now
            self._display_queue.put({
                "type":     "scanning",
                "title":    "Reading...",
                "subtitle": "Please hold still",
            })

            # Stage 3 — FID already processed, identify and get result
            try:
                event = api.fingerprint_scan()
            except NetworkError:
                self._display_queue.put({"type": "clear"})
                net_backoff = 10
                continue
            except APIError as e:
                if e.status_code != 401:
                    self.after(0, lambda msg=str(e): self._show_network_banner(
                        f"Scanner error: {msg}"))
                self._display_queue.put({"type": "clear"})
                net_backoff = 5
                continue

            if self._scanner_stop.is_set():
                break

            if event:
                self._display_queue.put(event)
                self.after(0, self._hide_network_banner)
                # Signal attendance view to refresh if a time-in/out occurred
                if event.get("type") in ("time_in", "time_out",
                                         "expiry_warn", "expired"):
                    self._att_queue.put(True)
            else:
                # Defensive fallback only — /attendance/scan always returns
                # a non-empty dict on a 200 response (even "no match" is a
                # dict with type: "no_match"), and HTTP/auth errors are now
                # caught above via except APIError. This branch shouldn't
                # be reachable in practice; kept in case r.json() ever
                # returns something unexpectedly falsy.
                self._display_queue.put({"type": "clear"})
                _time.sleep(1)

    def _show_network_banner(self, message: str = "No connection — retrying…"):
        """Show a persistent warning banner at the top of the window."""
        if not hasattr(self, "_net_banner") or not self._net_banner.winfo_exists():
            return
        if getattr(self, "_header_widget", None) is None or \
           not self._header_widget.winfo_exists():
            return  # main window isn't showing right now (e.g. mid-logout)
        if self._net_banner_hide_id:
            self.after_cancel(self._net_banner_hide_id)
            self._net_banner_hide_id = None
        self._net_banner_label.config(text=f"⚠  {message}")
        if not self._net_banner_visible:
            self._net_banner.pack(fill="x", side="top", before=self._header_widget)
            self._net_banner_visible = True
        # Auto-dismiss after 15 s — it reappears immediately if the next
        # request also fails, so this just clears stale messages. Must
        # exceed the scanner loop's longest backoff (10 s for NetworkError)
        # with margin, or the banner flickers off and back on every retry
        # cycle during a sustained outage instead of staying visible.
        self._net_banner_hide_id = self.after(15000, self._hide_network_banner)

    def _hide_network_banner(self):
        if not hasattr(self, "_net_banner") or not self._net_banner.winfo_exists():
            return
        self._net_banner.pack_forget()
        self._net_banner_visible = False
        self._net_banner_hide_id = None

    def _on_unauthorized(self):
        """Called on main thread when any API request returns 401."""
        APIClient.clear_unauthorized_handler()
        APIClient.clear_network_error_handler()
        self._scanner_stop.set()
        api.logout()
        if self._client_win:
            self._client_win.destroy()
            self._client_win = None
        self.title("Tiger's Fitness Gym")
        import tkinter.messagebox as mb
        mb.showwarning("Session Expired",
                       "Your session has expired. Please log in again.")
        self._show_login()

    def _logout(self):
        APIClient.clear_unauthorized_handler()
        APIClient.clear_network_error_handler()
        self._scanner_stop.set()
        api.logout()
        if self._client_win:
            self._client_win.destroy()
            self._client_win = None
        self.title("Tiger's Fitness Gym")
        self._show_login()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()
        self._current_view = None
        self._nav_buttons = {}
        self._view_cache = {}
        self._net_banner_visible = False
        self._net_banner_hide_id = None
        self._header_widget = None