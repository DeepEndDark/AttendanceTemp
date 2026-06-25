"""
Admin — detailed client information panel.
Shows identity, active subscriptions, locker, attendance history, sales history.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import set_window_icon


class ClientInfoView(tk.Toplevel):
    def __init__(self, parent, client_name: str):
        super().__init__(parent)
        self.title(f"Client: {client_name}")
        self.geometry("860x680")
        self.resizable(True, True)
        set_window_icon(self)
        self._client_name = client_name
        self._build()
        self._load()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header
        hdr = tk.Frame(self, bg="#185FA5", height=44)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.pack_propagate(False)
        self._title_lbl = tk.Label(hdr, text=f"Client Profile — {self._client_name}",
                                   bg="#185FA5", fg="white", font=("", 12, "bold"))
        self._title_lbl.pack(side="left", padx=16, expand=True, anchor="w")

        # Notebook
        nb = ttk.Notebook(self)
        nb.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        self._tab_info = tk.Frame(nb, bg="white")
        self._tab_subs = tk.Frame(nb, bg="white")
        self._tab_att  = tk.Frame(nb, bg="white")
        self._tab_sales = tk.Frame(nb, bg="white")

        nb.add(self._tab_info,  text="  Identity & Locker  ")
        nb.add(self._tab_subs,  text="  Subscriptions  ")
        nb.add(self._tab_att,   text="  Attendance Logs  ")
        nb.add(self._tab_sales, text="  Sales History  ")

        self._build_info_tab()
        self._build_subs_tab()
        self._build_att_tab()
        self._build_sales_tab()

    # ── Identity tab ──────────────────────────────────────────

    def _build_info_tab(self):
        f = self._tab_info
        f.columnconfigure(1, weight=1)
        labels = [
            ("Client UID", "_uid"),
            ("Name", "_name"),
            ("Contact", "_contact"),
            ("Address", "_address"),
            ("Date Registered", "_created"),
            ("Last Renewed", "_renewed"),
            ("Plan Expires", "_plan_exp"),
            ("Fingerprint", "_fp"),
            ("Status", "_status"),
        ]
        self._info_vars = {}
        for i, (lbl, key) in enumerate(labels):
            tk.Label(f, text=lbl + ":", bg="white", font=("", 9),
                     fg="gray", anchor="e").grid(row=i, column=0, sticky="e",
                                                 padx=(16, 8), pady=5)
            var = tk.StringVar()
            self._info_vars[key] = var
            tk.Label(f, textvariable=var, bg="white", font=("", 10),
                     anchor="w").grid(row=i, column=1, sticky="w", pady=5)

        # Locker section
        sep = ttk.Separator(f, orient="horizontal")
        sep.grid(row=len(labels), column=0, columnspan=2,
                 sticky="ew", padx=16, pady=(12, 4))
        tk.Label(f, text="LOCKER", bg="white", font=("", 9, "bold"),
                 fg="#185FA5").grid(row=len(labels)+1, column=0,
                                    columnspan=2, sticky="w", padx=16)
        locker_labels = [
            ("Locker #", "_locker_num"),
            ("Days Remaining", "_locker_days"),
            ("Est. Expiry", "_locker_exp"),
        ]
        for j, (lbl, key) in enumerate(locker_labels):
            row = len(labels) + 2 + j
            tk.Label(f, text=lbl + ":", bg="white", font=("", 9),
                     fg="gray", anchor="e").grid(row=row, column=0,
                                                 sticky="e", padx=(16, 8), pady=4)
            var = tk.StringVar()
            self._info_vars[key] = var
            tk.Label(f, textvariable=var, bg="white", font=("", 10),
                     anchor="w").grid(row=row, column=1, sticky="w", pady=4)

    # ── Subscriptions tab ─────────────────────────────────────

    def _build_subs_tab(self):
        f = self._tab_subs
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("plan", "subscribed", "expires", "days",
                "trainer_days", "hardcap", "active")
        self._sub_tree = ttk.Treeview(f, columns=cols, show="headings")
        for col, txt, w in [
            ("plan", "Plan", 160), ("subscribed", "Subscribed", 100),
            ("expires", "Expires", 100), ("days", "Days Left", 80),
            ("trainer_days", "Trainer Days", 100),
            ("hardcap", "Hardcap Left", 100), ("active", "Active", 70)
        ]:
            self._sub_tree.heading(col, text=txt)
            self._sub_tree.column(col, width=w, anchor="center")
        self._sub_tree.tag_configure("active", foreground="#0F6E56")
        self._sub_tree.tag_configure("expired", foreground="#888")
        sb = ttk.Scrollbar(f, orient="vertical", command=self._sub_tree.yview)
        self._sub_tree.configure(yscrollcommand=sb.set)
        self._sub_tree.grid(row=0, column=0, sticky="nsew", padx=(8,0), pady=8)
        sb.grid(row=0, column=1, sticky="ns", pady=8)

    # ── Attendance tab ────────────────────────────────────────

    def _build_att_tab(self):
        f = self._tab_att
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("uid", "date", "time_in", "time_out")
        self._att_tree = ttk.Treeview(f, columns=cols, show="headings")
        for col, txt, w in [("uid", "UID", 70), ("date", "Date", 110),
                             ("time_in", "Time In", 100),
                             ("time_out", "Time Out", 100)]:
            self._att_tree.heading(col, text=txt)
            self._att_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self._att_tree.yview)
        self._att_tree.configure(yscrollcommand=sb.set)
        self._att_tree.grid(row=0, column=0, sticky="nsew", padx=(8,0), pady=8)
        sb.grid(row=0, column=1, sticky="ns", pady=8)

    # ── Sales tab ─────────────────────────────────────────────

    def _build_sales_tab(self):
        f = self._tab_sales
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("uid", "date", "items", "total", "status")
        self._sales_tree = ttk.Treeview(f, columns=cols, show="headings")
        for col, txt, w in [("uid", "UID", 70), ("date", "Date", 100),
                             ("items", "Items", 280), ("total", "Total", 90),
                             ("status", "Status", 80)]:
            self._sales_tree.heading(col, text=txt)
            self._sales_tree.column(col, width=w, anchor="center")
        self._sales_tree.tag_configure("open", foreground="#185FA5")
        sb = ttk.Scrollbar(f, orient="vertical",
                            command=self._sales_tree.yview)
        self._sales_tree.configure(yscrollcommand=sb.set)
        self._sales_tree.grid(row=0, column=0, sticky="nsew",
                              padx=(8,0), pady=8)
        sb.grid(row=0, column=1, sticky="ns", pady=8)

    # ── Data loading ──────────────────────────────────────────

    def _load(self):
        try:
            client = api.get_client(self._client_name)
            self._populate_info(client)
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return

        try:
            subs = api.get_client_subscriptions(self._client_name)
            self._populate_subs(subs)
        except APIError:
            pass

        try:
            logs = api.get_client_attendance(self._client_name)
            self._populate_att(logs)
        except APIError:
            pass

        try:
            sales = api.get_client_sales(self._client_name)
            self._populate_sales(sales)
        except APIError:
            pass

    def _populate_info(self, c: dict):
        from datetime import date
        iv = self._info_vars
        iv["_uid"].set(str(c.get("client_uid", "—")))
        iv["_name"].set(c.get("client_name", "—"))
        iv["_contact"].set(c.get("contact_number") or "—")
        iv["_address"].set(c.get("address") or "—")
        iv["_created"].set((c.get("created_at") or "—")[:10])
        iv["_renewed"].set((c.get("last_enrolled_at") or "—")[:10])
        iv["_plan_exp"].set(c.get("last_plan_expires_at") or "—")
        iv["_fp"].set("Enrolled" if c.get("fingerprint_enrolled") else "Not enrolled")
        iv["_status"].set("Timed In ●" if c.get("client_status") else "Out ○")

        locker = c.get("locker_number")
        locker_days = c.get("client_locker_days_remaining", 0)
        iv["_locker_num"].set(str(locker) if locker else "None")
        iv["_locker_days"].set(str(locker_days))
        if locker and locker_days > 0:
            from datetime import timedelta
            exp = (date.today() + timedelta(days=locker_days)).isoformat()
            iv["_locker_exp"].set(exp)
        else:
            iv["_locker_exp"].set("—")

    def _populate_subs(self, subs: list):
        self._sub_tree.delete(*self._sub_tree.get_children())
        for s in subs:
            active = s.get("is_active", False)
            tag = "active" if active else "expired"
            self._sub_tree.insert("", "end", values=(
                s["subscription_name"],
                s["subscribed_at"],
                s["expires_at"],
                s.get("days_remaining", 0),
                s.get("trainer_days_remaining", 0),
                s.get("trainer_hardcap_remaining", 0),
                "Yes" if active else "No",
            ), tags=(tag,))

    def _populate_att(self, logs: list):
        self._att_tree.delete(*self._att_tree.get_children())
        for l in logs:
            self._att_tree.insert("", "end", values=(
                l["log_uid"], l["log_date"],
                l["time_in"], l.get("time_out") or "—",
            ))

    def _populate_sales(self, sales: list):
        self._sales_tree.delete(*self._sales_tree.get_children())
        for s in sales:
            items_str = ", ".join(
                f"{si['item_name']} x{si['item_qty']}"
                for si in s.get("item_list", [])
            )
            tag = "open" if s["sale_status"] == "open" else ""
            self._sales_tree.insert("", "end", values=(
                s["sales_uid"], s["sale_date"], items_str,
                f"₱{s['total_price']:.2f}", s["sale_status"],
            ), tags=(tag,))