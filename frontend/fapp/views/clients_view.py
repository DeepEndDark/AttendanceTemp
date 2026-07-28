"""Admin — full client list with detail panel showing subscriptions,
attendance history, sales history, locker info."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import set_window_icon


class ClientsView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
        super().__init__(master, bg="white")
        self._queue   = display_queue
        self._loading = False
        self._all_clients: list[dict] = []
        self._client_plan_map: dict[str, list[str]] = {}
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, columnspan=2,
                 sticky="ew", padx=16, pady=(10, 4))
        tk.Label(bar, text="Client List",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Add Plan", command=self._add_plan,
                  bg="#0F6E56", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Enroll New", command=self._enroll,
                  bg="#E8500A", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # ── Filter row ─────────────────────────────────────────
        filt = tk.Frame(self, bg="white")
        filt.grid(row=1, column=0, columnspan=2, sticky="ew",
                  padx=16, pady=(0, 6))
        tk.Label(filt, text="Filter by plan:", bg="white",
                 font=("", 9)).pack(side="left")
        self._plan_filter_var = tk.StringVar(value="All Plans")
        self._plan_filter_cb = ttk.Combobox(
            filt, textvariable=self._plan_filter_var,
            values=["All Plans"], state="readonly", width=20)
        self._plan_filter_cb.pack(side="left", padx=4)
        self._plan_filter_cb.bind("<<ComboboxSelected>>",
                                  lambda _e: self._apply_plan_filter())

        cols = ("uid", "name", "status", "days", "trainer", "locker", "expires")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("uid",     "UID",     50),  ("name",    "Name",    140),
            ("status",  "In/Out",  55),  ("days",    "Days",     55),
            ("trainer", "Trainer", 60),  ("locker",  "Locker",   55),
            ("expires", "Expires", 100),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("in",      foreground="#0F6E56")
        self._tree.tag_configure("warn",    foreground="#BA7517")
        self._tree.tag_configure("expired", foreground="#C0392B")
        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(16, 0), pady=4)
        sb.grid(row=2, column=1, sticky="nsw", pady=4)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._detail = _ClientDetailPanel(self)
        self._detail.grid(row=2, column=1, sticky="nsew",
                          padx=(4, 16), pady=4)

        self._status_lbl = tk.Label(self, text="", fg="gray",
                                    bg="white", anchor="w")
        self._status_lbl.grid(row=3, column=0, columnspan=2,
                               sticky="ew", padx=16, pady=4)
        self.refresh()

    # ---------------------------------------------------------
    # Async helpers
    # ---------------------------------------------------------

    def _run_worker(self, target, name: str):
        threading.Thread(target=target, daemon=True, name=name).start()

    def _show_error(self, msg: str):
        self._loading = False
        self._status_lbl.config(text=msg, fg="red")

    # ---------------------------------------------------------
    # Refresh — background
    # ---------------------------------------------------------

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self._status_lbl.config(text="Loading...", fg="gray")
        self._run_worker(self._refresh_worker, "clients-refresh")

    def _refresh_worker(self):
        try:
            clients = api.list_clients()
            try:
                subs = api.list_subscriptions()
            except Exception:
                subs = []
            self.after(0, lambda: self._refresh_complete(clients, subs))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _refresh_complete(self, clients: list, subs: list | None = None):
        self._loading = False
        self._all_clients = clients

        # Reconciled against a live collection_group check rather than
        # trusting active_subscription_names on its own — see
        # api.get_reconciled_client_plans for why this matters.
        self._client_plan_map = api.get_reconciled_client_plans(clients)

        if subs is not None:
            plan_names = api.get_all_plan_names(subs, self._client_plan_map)
            current = self._plan_filter_var.get()
            self._plan_filter_cb["values"] = ["All Plans"] + plan_names
            # Keep current selection if it's still valid, else reset
            if current not in (["All Plans"] + plan_names):
                self._plan_filter_var.set("All Plans")

        self._apply_plan_filter()

    def _apply_plan_filter(self):
        """Render the tree from cached clients, filtered by selected plan."""
        plan = self._plan_filter_var.get()
        if plan and plan != "All Plans":
            key = api.plan_filter_key(plan)
            visible = [
                c for c in self._all_clients
                if key in self._client_plan_map.get(c["client_name"], [])
            ]
        else:
            visible = self._all_clients
        self._render_tree(visible)

    def _render_tree(self, clients: list):
        sel_name = self._selected_name(warn=False)
        self._tree.delete(*self._tree.get_children())
        for c in clients:
            days    = c["client_days_remaining"]
            expires = (c.get("last_plan_expires_at") or "")[:10]
            lockers = c.get("lockers", [])
            if not lockers and c.get("locker_number"):
                lockers = [{"locker_number": c["locker_number"]}]
            if len(lockers) > 1:
                locker = f"#{lockers[0]['locker_number']}+{len(lockers)-1}"
            elif lockers:
                locker = str(lockers[0]["locker_number"])
            else:
                locker = "—"
            trainer = c["client_trainer_days_remaining"]
            tag = ("expired" if days == 0
                   else "warn" if days <= 2
                   else "in" if c["client_status"]
                   else "")
            self._tree.insert("", "end", tags=(tag,), values=(
                c["client_uid"], c["client_name"],
                "In" if c["client_status"] else "Out",
                days, trainer if trainer > 0 else "—",
                locker, expires,
            ))
        self._status_lbl.config(text=f"{len(clients)} client(s)", fg="gray")
        # Build name→iid map for O(1) selection restore
        name_to_iid = {
            self._tree.item(iid)["values"][1]: iid
            for iid in self._tree.get_children()
        }
        if sel_name and sel_name in name_to_iid:
            iid = name_to_iid[sel_name]
            self._tree.selection_set(iid)
            self._tree.see(iid)

    # ---------------------------------------------------------
    # Selection
    # ---------------------------------------------------------

    def _selected_name(self, warn: bool = True):
        sel = self._tree.selection()
        if not sel:
            if warn:
                messagebox.showwarning("Select", "Select a client first.")
            return None
        return self._tree.item(sel[0])["values"][1]

    def _on_select(self, _=None):
        name = self._selected_name(warn=False)
        if name:
            self._detail.load(name)

    # ---------------------------------------------------------
    # Enroll New — load subs in background, then dialog
    # ---------------------------------------------------------

    def _enroll(self):
        if self._loading:
            return
        self._loading = True
        self._status_lbl.config(text="Loading plans...", fg="gray")
        self._run_worker(self._enroll_worker, "clients-enroll-load")

    def _enroll_worker(self):
        try:
            subs = api.list_subscriptions()
            self.after(0, lambda: self._enroll_dialog(subs))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _enroll_dialog(self, subs: list):
        self._loading = False
        self._status_lbl.config(text="", fg="gray")
        if not subs:
            messagebox.showwarning("No plans", "Add subscription plans first.")
            return
        dlg = _EnrollDialog(self, subs)
        if dlg.result:
            self.refresh()

    # ---------------------------------------------------------
    # Add Plan — load subs in background, then dialog
    # ---------------------------------------------------------

    def _add_plan(self):
        name = self._selected_name()
        if not name or self._loading:
            return
        self._loading = True
        self._status_lbl.config(text="Loading plans...", fg="gray")
        self._run_worker(
            lambda: self._add_plan_worker(name),
            "clients-add-plan-load")

    def _add_plan_worker(self, name: str):
        try:
            subs = api.list_subscriptions()
            self.after(0, lambda: self._add_plan_dialog(name, subs))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _add_plan_dialog(self, name: str, subs: list):
        self._loading = False
        self._status_lbl.config(text="", fg="gray")
        if not subs:
            messagebox.showwarning("No plans", "Add subscription plans first.")
            return
        dlg = _AddPlanDialog(self, name, subs)
        if not dlg.result:
            return
        self._loading = True
        self._status_lbl.config(text="Adding plan...", fg="gray")
        self._run_worker(
            lambda: self._add_plan_save_worker(name, dlg.result),
            "clients-add-plan-save")

    def _add_plan_save_worker(self, name: str, sub: str):
        try:
            resp = api.re_enroll_client(name, sub)
            self.after(0, lambda: self._add_plan_complete(name, resp))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _add_plan_complete(self, name: str, resp: dict):
        self._loading = False
        if resp.get("warning"):
            messagebox.showwarning("Note", resp["warning"])
        self._detail.load(name)   # reload detail only — no full list refresh needed
        self._status_lbl.config(text="Plan added.", fg="gray")

    # ---------------------------------------------------------
    # Edit — load client in background, then dialog
    # ---------------------------------------------------------

    def _edit(self):
        name = self._selected_name()
        if not name or self._loading:
            return
        self._loading = True
        self._status_lbl.config(text="Loading client...", fg="gray")
        self._run_worker(
            lambda: self._edit_worker(name),
            "clients-edit-load")

    def _edit_worker(self, name: str):
        try:
            client = api.get_client(name)
            self.after(0, lambda: self._edit_dialog(name, client))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _edit_dialog(self, name: str, client: dict):
        self._loading = False
        self._status_lbl.config(text="", fg="gray")
        dlg = _EditDialog(self, client)
        if not dlg.result:
            return
        self._loading = True
        self._status_lbl.config(text="Saving...", fg="gray")
        self._run_worker(
            lambda: self._edit_save_worker(name, dlg.result),
            "clients-edit-save")

    def _edit_save_worker(self, name: str, payload: dict):
        try:
            api.update_client(name, payload)
            self.after(0, lambda: self._edit_complete(name))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _edit_complete(self, name: str):
        self._loading = False
        self._detail.load(name)
        self._status_lbl.config(text="Client updated.", fg="gray")
        self.refresh()

    # ---------------------------------------------------------
    # Delete — background
    # ---------------------------------------------------------

    def _delete(self):
        name = self._selected_name()
        if not name or self._loading:
            return
        if not messagebox.askyesno("Confirm", f"Delete client '{name}'?"):
            return
        self._loading = True
        self._status_lbl.config(text="Deleting...", fg="gray")
        self._run_worker(
            lambda: self._delete_worker(name),
            "clients-delete")

    def _delete_worker(self, name: str):
        try:
            api.delete_client(name)
            self.after(0, lambda: self._delete_complete())
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _delete_complete(self):
        self._loading = False
        self._detail.clear()
        self._status_lbl.config(text="Client deleted.", fg="gray")
        self.refresh()


# ── Detail panel ──────────────────────────────────────────────

class _ClientDetailPanel(tk.Frame):
    """Right-side panel: identity, subscriptions, locker, attendance, sales."""

    def __init__(self, master):
        super().__init__(master, bg="white", relief="groove", bd=1)
        self._loading_name: str | None = None
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.rowconfigure(5, weight=1)

        # Loading indicator
        self._loading_lbl = tk.Label(
            self, text="", fg="#E8500A", bg="white", font=("", 9))
        self._loading_lbl.grid(row=0, column=0, sticky="w", padx=8, pady=2)

        # ── Section 1: Identity ──────────────────────────────
        s1 = tk.LabelFrame(self, text="Client Info",
                           bg="white", padx=8, pady=6)
        s1.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 4))
        self._info_labels = {}
        fields = [
            ("UID",          "uid"),    ("Name",        "name"),
            ("Contact",      "contact"),("Address",     "address"),
            ("Registered",   "created"),("Last Renewed","renewed"),
            ("Plan Expires", "expires"),("Fingerprint", "fp"),
        ]
        for i, (lbl, key) in enumerate(fields):
            tk.Label(s1, text=f"{lbl}:", bg="white",
                     font=("", 9), anchor="w").grid(
                row=i, column=0, sticky="w")
            v = tk.Label(s1, text="—", bg="white",
                         font=("", 9), anchor="w", wraplength=200)
            v.grid(row=i, column=1, sticky="w", padx=(8, 0))
            self._info_labels[key] = v

        # ── Section 2: Active subscriptions ──────────────────
        s2 = tk.LabelFrame(self, text="Active Subscriptions",
                           bg="white", padx=8, pady=6)
        s2.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self._sub_tree = ttk.Treeview(
            s2,
            columns=("plan", "days", "trainer", "hardcap", "expires"),
            show="headings", height=3)
        for col, txt, w in [
            ("plan",    "Plan",    110), ("days",    "Days",   45),
            ("trainer", "Trainer",  55), ("hardcap", "Hardcap",55),
            ("expires", "Expires",  90),
        ]:
            self._sub_tree.heading(col, text=txt)
            self._sub_tree.column(col, width=w, anchor="center")
        self._sub_tree.pack(fill="x")

        # ── Section 3: Locker ─────────────────────────────────
        s3 = tk.LabelFrame(self, text="Locker",
                           bg="white", padx=8, pady=6)
        s3.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        self._locker_lbl = tk.Label(s3, text="No locker assigned.",
                                    bg="white", font=("", 9))
        self._locker_lbl.pack(anchor="w")

        # ── Section 4: Attendance ─────────────────────────────
        s4 = tk.LabelFrame(self, text="Attendance History",
                           bg="white", padx=8, pady=6)
        s4.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        s4.rowconfigure(0, weight=1)
        s4.columnconfigure(0, weight=1)
        self._att_tree = ttk.Treeview(
            s4,
            columns=("uid", "date", "in", "out"),
            show="headings", height=4)
        for col, txt, w in [
            ("uid",  "UID",       45), ("date", "Date",     90),
            ("in",   "Time In",   75), ("out",  "Time Out", 75),
        ]:
            self._att_tree.heading(col, text=txt)
            self._att_tree.column(col, width=w, anchor="center")
        # Hide UID — system-side only
        self._att_tree.column("uid", width=0, minwidth=0, stretch=False)
        self._att_tree.heading("uid", text="")
        asb = ttk.Scrollbar(s4, orient="vertical",
                            command=self._att_tree.yview)
        self._att_tree.configure(yscrollcommand=asb.set)
        self._att_tree.grid(row=0, column=0, sticky="nsew")
        asb.grid(row=0, column=1, sticky="ns")

        # ── Section 5: Sales ──────────────────────────────────
        s5 = tk.LabelFrame(self, text="Sales History",
                           bg="white", padx=8, pady=6)
        s5.grid(row=5, column=0, sticky="nsew", padx=8, pady=(4, 8))
        s5.rowconfigure(0, weight=1)
        s5.columnconfigure(0, weight=1)
        self._sales_tree = ttk.Treeview(
            s5,
            columns=("uid", "date", "items", "total", "status"),
            show="headings", height=4)
        for col, txt, w in [
            ("uid",    "UID",      45), ("date",   "Date",    90),
            ("items",  "Items",   130), ("total",  "Total ₱", 70),
            ("status", "Status",   60),
        ]:
            self._sales_tree.heading(col, text=txt)
            self._sales_tree.column(col, width=w, anchor="center")
        # Hide UID — system-side only
        self._sales_tree.column("uid", width=0, minwidth=0, stretch=False)
        self._sales_tree.heading("uid", text="")
        ssb = ttk.Scrollbar(s5, orient="vertical",
                            command=self._sales_tree.yview)
        self._sales_tree.configure(yscrollcommand=ssb.set)
        self._sales_tree.grid(row=0, column=0, sticky="nsew")
        ssb.grid(row=0, column=1, sticky="ns")

    # ---------------------------------------------------------
    # Load — background, stale-response guard
    # ---------------------------------------------------------

    def load(self, client_name: str):
        self._loading_name = client_name
        self._loading_lbl.config(text=f"Loading {client_name}...")
        threading.Thread(
            target=self._load_worker,
            args=(client_name,),
            daemon=True,
            name="detail-load",
        ).start()

    def _load_worker(self, name: str):
        results = {}
        errors  = []

        def _fetch(key, fn):
            try:
                results[key] = fn()
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=_fetch, args=("client", lambda: api.get_client(name)),                   daemon=True),
            threading.Thread(target=_fetch, args=("subs",   lambda: api.get_client_subscriptions(name)),     daemon=True),
            threading.Thread(target=_fetch, args=("logs",   lambda: api.get_client_attendance(name)),        daemon=True),
            threading.Thread(target=_fetch, args=("sales",  lambda: api.get_client_sales(name)),             daemon=True),
        ]
        for t in threads: t.start()
        for t in threads: t.join()

        if errors or "client" not in results:
            msg = errors[0] if errors else "Failed to load client"
            self.after(0, lambda msg=msg: self._load_error(name, msg))
            return

        self.after(0, lambda: self._load_complete(
            name,
            results["client"],
            results.get("subs", []),
            results.get("logs", []),
            results.get("sales", []),
        ))

    def _load_complete(self, name: str, c: dict, subs: list,
                       logs: list, sales: list):
        # Discard if user clicked a different client while loading
        if self._loading_name != name:
            return
        self._loading_name = None
        self._loading_lbl.config(text="")

        # Identity
        lbl = self._info_labels
        lbl["uid"].config(text=str(c.get("client_uid", "—")))
        lbl["name"].config(text=c["client_name"])
        lbl["contact"].config(text=c.get("contact_number") or "—")
        lbl["address"].config(text=c.get("address") or "—")
        lbl["created"].config(text=(c.get("created_at") or "—")[:10])
        lbl["renewed"].config(text=(c.get("last_enrolled_at") or "—")[:10])
        lbl["expires"].config(
            text=(c.get("last_plan_expires_at") or "No active plan")[:10])
        lbl["fp"].config(
            text="Enrolled" if c.get("fingerprint_enrolled") else "Not enrolled")

        # Subscriptions
        self._sub_tree.delete(*self._sub_tree.get_children())
        for s in subs:
            if s["is_active"]:
                trainer = s["trainer_days_remaining"] if s["trainer_days_remaining"] > 0 else "—"
                hardcap = s["trainer_hardcap_remaining"] if s["trainer_hardcap_remaining"] > 0 else "—"
                self._sub_tree.insert("", "end", values=(
                    s["subscription_name"],
                    s["days_remaining"],
                    trainer, hardcap,
                    s["expires_at"][:10],
                ))

        # Locker(s)
        lockers = c.get("lockers", [])
        if not lockers and c.get("locker_number"):
            lockers = [{"locker_number": c["locker_number"],
                        "days_remaining": c.get("client_locker_days_remaining", 0)}]
        if lockers:
            lines = [f"#{l['locker_number']} — {l.get('days_remaining', 0)} day(s)"
                     for l in lockers]
            self._locker_lbl.config(text="  |  ".join(lines))
        else:
            self._locker_lbl.config(text="No locker assigned.")

        # Attendance — hide UID
        self._att_tree.delete(*self._att_tree.get_children())
        for l in logs[:50]:
            self._att_tree.insert("", "end", values=(
                l["log_uid"], l["log_date"],
                l["time_in"], l.get("time_out") or "—"))

        # Sales — hide UID
        self._sales_tree.delete(*self._sales_tree.get_children())
        for s in sales[:50]:
            items_str = ", ".join(
                f"{i['item_name']} x{i['item_qty']}"
                for i in s.get("item_list", []))
            self._sales_tree.insert("", "end", values=(
                s["sales_uid"], s["sale_date"],
                items_str, f"{s['total_price']:.2f}",
                s["sale_status"].capitalize()))

    def _load_error(self, name: str, msg: str):
        if self._loading_name != name:
            return
        self._loading_name = None
        self._loading_lbl.config(text=f"Error: {msg}", fg="red")

    def clear(self):
        self._loading_name = None
        self._loading_lbl.config(text="")
        for v in self._info_labels.values():
            v.config(text="—")
        self._sub_tree.delete(*self._sub_tree.get_children())
        self._att_tree.delete(*self._att_tree.get_children())
        self._sales_tree.delete(*self._sales_tree.get_children())
        self._locker_lbl.config(text="No locker assigned.")


# ── Dialogs ───────────────────────────────────────────────────

class _AddPlanDialog(tk.Toplevel):
    def __init__(self, parent, client_name: str, subs: list):
        super().__init__(parent)
        self.title(f"Add Plan — {client_name}")
        self.configure(bg="white")
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None

        frame = tk.Frame(self, bg="white", padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=f"Add Plan: {client_name}",
                 font=("", 11, "bold"), bg="white",
                 fg="#0F6E56").grid(row=0, column=0, columnspan=2,
                                    sticky="w", pady=(0, 12))
        tk.Label(frame,
                 text="Adds days on top of any existing subscription.",
                 font=("", 9), fg="#666", bg="white").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(frame, text="Subscription:", bg="white",
                 font=("", 9)).grid(row=2, column=0, sticky="w", pady=6)
        self._sub_var = tk.StringVar()
        cb = ttk.Combobox(frame, textvariable=self._sub_var,
                          values=[s["subscription_name"] for s in subs],
                          state="readonly", width=25)
        cb.grid(row=2, column=1, padx=(10, 0), pady=6)
        if subs:
            cb.current(0)

        self._err = tk.Label(frame, text="", fg="red",
                             bg="white", font=("", 9))
        self._err.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btn_row = tk.Frame(frame, bg="white")
        btn_row.grid(row=4, column=0, columnspan=2, pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Add Plan", command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#0F6E56", fg="white").pack(side="right")
        self.wait_window()

    def _save(self):
        sub = self._sub_var.get()
        if not sub:
            self._err.config(text="Select a plan.")
            return
        self.result = sub
        self.destroy()


class _EnrollDialog(tk.Toplevel):
    """Phase 1: fill details + subscription → Enroll.
    Phase 2: confirmation + optional fingerprint enrollment inline."""

    def __init__(self, parent, subs: list[dict]):
        super().__init__(parent)
        self.title("Enroll New Client")
        self.configure(bg="white")
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None
        self._subs = subs
        self._build_phase1()
        self.wait_window()

    def _build_phase1(self):
        self._phase1 = tk.Frame(self, bg="white", padx=20, pady=16)
        self._phase1.pack(fill="both", expand=True)

        tk.Label(self._phase1, text="New Client",
                 font=("", 12, "bold"), bg="white",
                 fg="#E8500A").grid(row=0, column=0, columnspan=2,
                                    sticky="w", pady=(0, 12))

        fields = [("Client name *", "_name"),
                  ("Contact number", "_contact"),
                  ("Address", "_address")]
        self._entries = {}
        for i, (lbl, key) in enumerate(fields, start=1):
            tk.Label(self._phase1, text=lbl, bg="white",
                     font=("", 9)).grid(row=i, column=0, sticky="w", pady=5)
            e = tk.Entry(self._phase1, width=28, relief="solid", bd=1)
            e.grid(row=i, column=1, padx=(10, 0), pady=5, sticky="ew")
            self._entries[key] = e

        tk.Label(self._phase1, text="Subscription *", bg="white",
                 font=("", 9)).grid(row=4, column=0, sticky="w", pady=5)
        self._sub_var = tk.StringVar()
        cb = ttk.Combobox(self._phase1, textvariable=self._sub_var,
                          values=[s["subscription_name"] for s in self._subs],
                          state="readonly", width=25)
        cb.grid(row=4, column=1, padx=(10, 0), pady=5, sticky="ew")
        if self._subs:
            cb.current(0)

        self._status = tk.Label(self._phase1, text="", bg="white",
                                fg="red", font=("", 9), wraplength=280)
        self._status.grid(row=5, column=0, columnspan=2,
                          sticky="w", pady=(4, 0))

        btn_row = tk.Frame(self._phase1, bg="white")
        btn_row.grid(row=6, column=0, columnspan=2, pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Enroll", command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#E8500A", fg="white").pack(side="right")
        self._entries["_name"].focus_set()

    def _save(self):
        name = self._entries["_name"].get().strip()
        sub  = self._sub_var.get()
        if not name or not sub:
            self._status.config(text="Client name and subscription are required.")
            return
        payload = {
            "client_name":       name,
            "contact_number":    self._entries["_contact"].get().strip() or None,
            "address":           self._entries["_address"].get().strip() or None,
            "subscription_name": sub,
        }
        try:
            from fapp.api_client import api
            resp = api.create_client(payload)
            if resp.get("warning"):
                messagebox.showwarning("Note", resp["warning"])
            self.result = payload
        except Exception as e:
            self._status.config(text=str(e), fg="red")
            return
        self._phase1.destroy()
        self._build_phase2(name)

    def _build_phase2(self, name: str):
        self._phase2 = tk.Frame(self, bg="white", padx=24, pady=20)
        self._phase2.pack(fill="both", expand=True)

        tk.Label(self._phase2, text="Client Enrolled",
                 font=("", 13, "bold"), bg="white",
                 fg="#0F6E56").pack(anchor="w")
        tk.Label(self._phase2, text=name,
                 font=("", 11), bg="white", fg="#333").pack(anchor="w",
                                                             pady=(2, 16))
        tk.Frame(self._phase2, bg="#e0e0e0",
                 height=1).pack(fill="x", pady=(0, 16))

        tk.Label(self._phase2, text="Enroll fingerprint?",
                 font=("", 10, "bold"), bg="white").pack(anchor="w")
        tk.Label(self._phase2,
                 text="Scan 3 times to register this client.\n"
                      "You can skip and do this later from the client list.",
                 font=("", 9), fg="#666", bg="white",
                 justify="left").pack(anchor="w", pady=(4, 14))

        self._fp_status = tk.Label(self._phase2, text="", bg="white",
                                   font=("", 9), fg="#E8500A", wraplength=280)
        self._fp_status.pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(self._phase2, bg="white")
        btn_row.pack(anchor="w")
        self._fp_btn = tk.Button(
            btn_row, text="Scan Fingerprint",
            command=lambda: self._start_fp(name),
            relief="flat", padx=12, pady=6,
            bg="#E8500A", fg="white")
        self._fp_btn.pack(side="left", padx=(0, 8))
        self._done_btn = tk.Button(
            btn_row, text="Done", command=self.destroy,
            relief="flat", padx=12, pady=6, bg="#f0f0f0")
        self._done_btn.pack(side="left")

    def _start_fp(self, name: str):
        self._fp_btn.config(state="disabled", text="Scanning...")
        self._fp_status.config(text="Place finger on scanner 3 times...",
                               fg="#E8500A")
        self._check_fp_progress()
        threading.Thread(target=self._fp_worker,
                         args=(name,), daemon=True).start()

    def _fp_worker(self, name: str):
        try:
            api.enroll_fingerprint(name)
            self.after(0, self._fp_done_ok)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._fp_done_err(msg))

    def _check_fp_progress(self):
        threading.Thread(target=self._fetch_fp_progress, daemon=True).start()

    def _fetch_fp_progress(self):
        try:
            n = api.get_enroll_progress().get("progress", 0)
            if n > 0:
                self.after(0, lambda v=n: self._apply_fp_progress(v))
                return
        except Exception:
            pass
        self.after(0, self._maybe_continue_fp_poll)

    def _apply_fp_progress(self, n: int):
        try:
            if n == -1:
                self._fp_status.config(
                    text="Enrollment failed — scanner error. Try again.",
                    fg="red")
                self._fp_btn.config(state="normal", text="Try Again")
                return
            self._fp_status.config(
                text=f"Scan {n}/3 — lift finger, scan again...",
                fg="#E8500A")
        except Exception:
            pass
        self._maybe_continue_fp_poll()

    def _maybe_continue_fp_poll(self):
        try:
            if str(self._fp_btn.cget("state")) == "disabled":
                self.after(200, self._check_fp_progress)
        except Exception:
            pass

    def _fp_done_ok(self):
        self._fp_status.config(text="Fingerprint enrolled.", fg="#0F6E56")
        self._fp_btn.pack_forget()
        self._done_btn.config(bg="#E8500A", fg="white", text="Done")

    def _fp_done_err(self, msg: str):
        self._fp_status.config(text=f"Failed: {msg}", fg="red")
        self._fp_btn.config(state="normal", text="Try Again")


class _EditDialog(tk.Toplevel):
    def __init__(self, parent, client: dict):
        super().__init__(parent)
        self.title(f"Edit — {client['client_name']}")
        self.configure(bg="white")
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None
        self._client_name = client["client_name"]

        frame = tk.Frame(self, bg="white", padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=f"Edit: {client['client_name']}",
                 font=("", 11, "bold"), bg="white",
                 fg="#E8500A").grid(row=0, column=0, columnspan=2,
                                    sticky="w", pady=(0, 12))

        fields = [("Contact number:", "contact_number"),
                  ("Address:", "address")]
        self._entries = {}
        for i, (lbl, key) in enumerate(fields, start=1):
            tk.Label(frame, text=lbl, bg="white",
                     font=("", 9)).grid(row=i, column=0, sticky="w", pady=6)
            e = tk.Entry(frame, width=28, relief="solid", bd=1)
            e.insert(0, client.get(key) or "")
            e.grid(row=i, column=1, padx=(10, 0), pady=6, sticky="ew")
            self._entries[key] = e

        tk.Frame(frame, bg="#e0e0e0", height=1).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(12, 8))

        fp_label = ("Fingerprint: Enrolled"
                    if client.get("fingerprint_enrolled")
                    else "Fingerprint: Not enrolled")
        fp_color = "#0F6E56" if client.get("fingerprint_enrolled") else "#888"
        tk.Label(frame, text=fp_label, bg="white",
                 fg=fp_color, font=("", 9)).grid(
            row=4, column=0, columnspan=2, sticky="w")

        self._fp_status = tk.Label(frame, text="", bg="white",
                                   fg="#E8500A", font=("", 9), wraplength=260)
        self._fp_status.grid(row=5, column=0, columnspan=2,
                             sticky="w", pady=(2, 0))

        self._fp_btn = tk.Button(frame, text="Re-scan Fingerprint",
                                 command=self._start_fp,
                                 relief="flat", padx=10, pady=4,
                                 bg="#E8500A", fg="white")
        self._fp_btn.grid(row=6, column=0, columnspan=2,
                          sticky="w", pady=(6, 0))

        btn_row = tk.Frame(frame, bg="white")
        btn_row.grid(row=7, column=0, columnspan=2, pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Save", command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#E8500A", fg="white").pack(side="right")
        self.wait_window()

    def _start_fp(self):
        self._fp_btn.config(state="disabled", text="Scanning...")
        self._fp_status.config(text="Place finger 3 times...", fg="#E8500A")
        self._check_fp_progress()
        threading.Thread(target=self._fp_worker, daemon=True).start()

    def _fp_worker(self):
        try:
            api.enroll_fingerprint(self._client_name)
            self.after(0, lambda: self._fp_done(ok=True))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._fp_done(ok=False, msg=msg))

    def _fp_done(self, ok: bool, msg: str = ""):
        try:
            if ok:
                self._fp_status.config(text="Fingerprint updated.", fg="#0F6E56")
                self._fp_btn.config(state="normal", text="Re-scan Fingerprint")
            else:
                self._fp_status.config(text=f"Failed: {msg}", fg="red")
                self._fp_btn.config(state="normal", text="Try Again")
        except Exception:
            pass

    def _check_fp_progress(self):
        threading.Thread(target=self._fetch_fp_progress, daemon=True).start()

    def _fetch_fp_progress(self):
        try:
            n = api.get_enroll_progress().get("progress", 0)
            if n > 0:
                self.after(0, lambda v=n: self._apply_fp_progress(v))
                return
        except Exception:
            pass
        self.after(0, self._maybe_continue_fp_poll)

    def _apply_fp_progress(self, n: int):
        try:
            if n == -1:
                self._fp_status.config(
                    text="Enrollment failed — scanner error. Try again.",
                    fg="red")
                self._fp_btn.config(state="normal", text="Try Again")
                return
            self._fp_status.config(
                text=f"Scan {n}/3 — lift finger, scan again...",
                fg="#E8500A")
        except Exception:
            pass
        self._maybe_continue_fp_poll()

    def _maybe_continue_fp_poll(self):
        try:
            if str(self._fp_btn.cget("state")) == "disabled":
                self.after(200, self._check_fp_progress)
        except Exception:
            pass

    def _save(self):
        self.result = {
            "contact_number": self._entries["contact_number"].get().strip() or None,
            "address":        self._entries["address"].get().strip() or None,
        }
        self.destroy()