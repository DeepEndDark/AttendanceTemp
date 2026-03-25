import tkinter as tk
from tkinter import ttk

from app.api_client import api
from app.views.login_view import LoginView


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Attendance & Sales System")
        self.geometry("1000x660")
        self.minsize(800, 540)
        self._current_view = None
        self._nav_buttons = {}
        self._show_login()

    # ── Login ────────────────────────────────────────────────

    def _show_login(self):
        self._clear()
        LoginView(self, on_success=self._show_main).pack(fill="both", expand=True)

    # ── Main shell ───────────────────────────────────────────

    def _show_main(self):
        self._clear()
        self.title(f"Attendance & Sales — {api.account_name}")

        # ── Header ───────────────────────────────────────────
        header = tk.Frame(self, bg="#185FA5", height=46)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="  Attendance & Sales System",
            bg="#185FA5", fg="white", font=("", 12, "bold")
        ).pack(side="left", padx=8)

        tk.Button(
            header, text="Logout",
            bg="#185FA5", fg="#B5D4F4", relief="flat",
            activebackground="#0C447C", activeforeground="white",
            cursor="hand2", command=self._logout, padx=10
        ).pack(side="right", pady=8, padx=12)

        role_color = "#9FE1CB" if api.is_admin else "#FAC775"
        tk.Label(
            header,
            text=f"{api.account_name}  [{api.account_type.upper()}]",
            bg="#185FA5", fg=role_color, font=("", 9)
        ).pack(side="right", padx=4)

        # ── Body (sidebar + content) ──────────────────────────
        body = tk.Frame(self)
        body.pack(fill="both", expand=True)

        # Sidebar
        self._sidebar = tk.Frame(body, bg="#1a1a2e", width=170)
        self._sidebar.pack(fill="y", side="left")
        self._sidebar.pack_propagate(False)

        # Content area
        self._content = tk.Frame(body, bg="white")
        self._content.pack(fill="both", expand=True, side="left")

        self._build_nav()

    def _build_nav(self):
        from app.views.enroll_view import EnrollView
        from app.views.sales_open_view import SalesOpenView
        from app.views.admin_sales_view import AdminSalesView
        from app.views.admin_attendance_view import AdminAttendanceView
        from app.views.clients_view import ClientsView
        from app.views.items_view import ItemsView
        from app.views.reports_view import ReportsView
        from app.views.accounts_view import AccountsView

        if api.is_admin:
            nav_items = [
                ("Attendance Logs", AdminAttendanceView),
                ("Sales Logs", AdminSalesView),
                ("Client List", ClientsView),
                ("Item Catalogue", ItemsView),
                ("Daily Reports", ReportsView),
                ("Accounts", AccountsView),
            ]
        else:
            nav_items = [
                ("Enroll Client", EnrollView),
                ("Sales", SalesOpenView),
            ]

        tk.Label(
            self._sidebar, text="NAVIGATION",
            bg="#1a1a2e", fg="#5F5E5A", font=("", 8), pady=12
        ).pack(fill="x", padx=12)

        self._nav_buttons = {}
        self._view_classes = {}
        self._view_cache = {}

        for label, ViewClass in nav_items:
            btn = tk.Button(
                self._sidebar, text=label,
                bg="#1a1a2e", fg="#B4B2A9",
                relief="flat", anchor="w", padx=14, pady=10,
                activebackground="#185FA5", activeforeground="white",
                cursor="hand2",
                command=lambda l=label: self._switch_view(l),
            )
            btn.pack(fill="x")
            self._nav_buttons[label] = btn
            self._view_classes[label] = ViewClass

        # Show first view
        first = nav_items[0][0]
        self._switch_view(first)

    def _switch_view(self, label: str):
        # Update button highlight
        for lbl, btn in self._nav_buttons.items():
            btn.config(
                bg="#185FA5" if lbl == label else "#1a1a2e",
                fg="white" if lbl == label else "#B4B2A9",
            )

        # Hide current
        if self._current_view:
            self._current_view.pack_forget()

        # Create or reuse view
        if label not in self._view_cache:
            ViewClass = self._view_classes[label]
            view = ViewClass(self._content)
            view.pack(fill="both", expand=True)
            self._view_cache[label] = view
        else:
            view = self._view_cache[label]
            view.pack(fill="both", expand=True)
            if hasattr(view, "refresh"):
                view.refresh()

        self._current_view = view

    def _logout(self):
        api.logout()
        self._show_login()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()
        self._current_view = None
        self._nav_buttons = {}


if __name__ == "__main__":
    App().mainloop()
