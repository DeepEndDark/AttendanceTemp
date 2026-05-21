"""
Sales role — Enroll Client tab.
Left panel: new enrollment / re-enroll with subscription picker.
Right panel: time-in / time-out + locker rental.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class EnrollView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._queue = display_queue
        self._subs: list[dict] = []
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        tk.Label(self, text="Client Enrollment",
                 font=("", 14, "bold"),
                 bg="white").grid(row=0, column=0, columnspan=2,
                                  sticky="w", padx=20, pady=(16, 4))

        self._build_enroll_panel()
        self._build_action_panel()

    # ── Left: enroll ──────────────────────────────────────────

    def _build_enroll_panel(self):
        pane = tk.LabelFrame(self, text="New Enrollment / Re-enroll",
                             bg="white", padx=14, pady=14)
        pane.grid(row=1, column=0, sticky="nsew",
                  padx=(20, 8), pady=10)
        pane.columnconfigure(1, weight=1)

        fields = [
            ("Client name:", "_name"),
            ("Contact number:", "_contact"),
            ("Address:", "_address"),
        ]
        self._entries = {}
        for i, (lbl, key) in enumerate(fields):
            tk.Label(pane, text=lbl, bg="white").grid(
                row=i, column=0, sticky="w", pady=5)
            e = tk.Entry(pane, width=26)
            e.grid(row=i, column=1, sticky="ew",
                   padx=(8, 0), pady=5)
            self._entries[key] = e

        # Subscription picker
        tk.Label(pane, text="Subscription plan:",
                 bg="white").grid(row=3, column=0, sticky="w", pady=5)
        self._sub_var = tk.StringVar()
        self._sub_cb = ttk.Combobox(pane, textvariable=self._sub_var,
                                    state="readonly", width=24)
        self._sub_cb.grid(row=3, column=1, sticky="ew",
                          padx=(8, 0), pady=5)
        self._sub_cb.bind("<<ComboboxSelected>>", self._show_sub_detail)

        self._sub_detail = tk.Label(pane, text="", fg="#185FA5",
                                    bg="white", font=("", 9),
                                    wraplength=260, justify="left")
        self._sub_detail.grid(row=4, column=0, columnspan=2,
                               sticky="w", pady=(0, 8))

        # Fingerprint button
        self._fp_btn = tk.Button(pane, text="Enroll Fingerprint",
                                 command=self._enroll_fp,
                                 bg="#5B5AEF", fg="white",
                                 relief="flat", padx=10)
        self._fp_btn.grid(row=5, column=0, columnspan=2,
                          sticky="w", pady=(4, 8))

        btn_row = tk.Frame(pane, bg="white")
        btn_row.grid(row=6, column=0, columnspan=2, pady=(4, 0))
        tk.Button(btn_row, text="Enroll New",
                  command=self._enroll_new,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=12, pady=6).pack(side="left", padx=4)
        tk.Button(btn_row, text="Re-enroll",
                  command=self._re_enroll,
                  bg="#0F6E56", fg="white",
                  relief="flat", padx=12, pady=6).pack(side="left", padx=4)

        self._enroll_status = tk.Label(pane, text="", fg="#185FA5",
                                       bg="white", wraplength=280,
                                       font=("", 9))
        self._enroll_status.grid(row=7, column=0, columnspan=2,
                                  pady=(8, 0))

        # Recent list
        tk.Label(pane, text="Recent clients:",
                 bg="white", font=("", 9)).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(14, 2))

        self._recent = ttk.Treeview(
            pane,
            columns=("name", "plan", "expires", "days"),
            show="headings", height=5)
        for col, txt, w in [
            ("name", "Client", 120), ("plan", "Plan", 100),
            ("expires", "Expires", 100), ("days", "Days left", 70)
        ]:
            self._recent.heading(col, text=txt)
            self._recent.column(col, width=w, anchor="center")
        self._recent.grid(row=9, column=0, columnspan=2,
                          sticky="ew", pady=4)

        self._load_subs()
        self._load_recent()

    # ── Right: actions ────────────────────────────────────────

    def _build_action_panel(self):
        pane = tk.LabelFrame(self, text="Time-In / Time-Out & Locker",
                             bg="white", padx=14, pady=14)
        pane.grid(row=1, column=1, sticky="nsew",
                  padx=(8, 20), pady=10)
        pane.columnconfigure(0, weight=1)

        tk.Label(pane, text="Select client:",
                 bg="white").pack(anchor="w")
        self._att_var = tk.StringVar()
        self._att_cb = ttk.Combobox(pane, textvariable=self._att_var,
                                    state="readonly", width=26)
        self._att_cb.pack(fill="x", pady=(2, 10))

        btn_row = tk.Frame(pane, bg="white")
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="Time-In",
                  command=self._time_in,
                  bg="#30a060", fg="white",
                  padx=14, pady=8, relief="flat").pack(side="left", padx=4)
        tk.Button(btn_row, text="Time-Out",
                  command=self._time_out,
                  bg="#f0a030", padx=14, pady=8,
                  relief="flat").pack(side="left", padx=4)
        tk.Button(btn_row, text="Refresh",
                  command=self._load_clients,
                  padx=10, pady=8,
                  relief="flat").pack(side="right", padx=4)

        tk.Button(pane, text="Rent Locker",
                  command=self._rent_locker,
                  bg="#3C3489", fg="white",
                  padx=12, pady=6,
                  relief="flat").pack(fill="x", pady=(12, 4))

        self._locker_lbl = tk.Label(pane, text="",
                                    fg="gray", bg="white",
                                    font=("", 9))
        self._locker_lbl.pack(anchor="w")

        self._att_status = tk.Label(pane, text="", fg="gray",
                                    bg="white", wraplength=240,
                                    font=("", 9))
        self._att_status.pack(pady=(10, 0), anchor="w")

        tk.Label(pane, text="Currently timed in:",
                 bg="white", font=("", 9)).pack(anchor="w",
                                                pady=(16, 2))
        self._active_tree = ttk.Treeview(
            pane,
            columns=("name", "days"),
            show="headings", height=7)
        for col, txt, w in [("name", "Client", 160),
                             ("days", "Days left", 80)]:
            self._active_tree.heading(col, text=txt)
            self._active_tree.column(col, width=w, anchor="center")
        self._active_tree.pack(fill="both", expand=True, pady=4)
        self._active_tree.tag_configure("warn",
                                        foreground="#BA7517")

        self._load_clients()

    # ── Loaders ───────────────────────────────────────────────

    def _load_subs(self):
        try:
            self._subs = api.list_subscriptions()
            names = [s["subscription_name"] for s in self._subs]
            self._sub_cb["values"] = names
            if names:
                self._sub_cb.current(0)
                self._show_sub_detail()
        except APIError:
            pass

    def _show_sub_detail(self, _=None):
        name = self._sub_var.get()
        sub = next((s for s in self._subs
                    if s["subscription_name"] == name), None)
        if not sub:
            return
        trainer_txt = (f" | Trainer: {sub['trainer_duration_days']}d "
                       f"(hardcap {sub['trainer_hardcap_days']}d)"
                       if sub.get("has_trainer") else " | No trainer")
        self._sub_detail.config(
            text=f"{sub['duration_days']} days  |  "
                 f"₱{sub['price']:.2f}{trainer_txt}")

    def _load_recent(self):
        self._recent.delete(*self._recent.get_children())
        try:
            clients = sorted(
                api.list_clients(),
                key=lambda c: c.get("last_enrolled_at") or "",
                reverse=True)[:10]
            for c in clients:
                expires = (c.get("last_plan_expires_at") or "")[:10]
                tag = "warn" if c["client_days_remaining"] <= 2 else ""
                self._recent.insert("", "end", tags=(tag,), values=(
                    c["client_name"],
                    "",
                    expires,
                    c["client_days_remaining"],
                ))
        except APIError:
            pass
        self._recent.tag_configure("warn", foreground="#BA7517")

    def _load_clients(self):
        try:
            all_clients = api.list_clients()
            names = [c["client_name"] for c in all_clients]
            self._att_cb["values"] = names
            if names and not self._att_var.get():
                self._att_var.set(names[0])
            self._active_tree.delete(*self._active_tree.get_children())
            for c in all_clients:
                if c.get("client_status"):
                    tag = "warn" if c["client_days_remaining"] <= 2 else ""
                    self._active_tree.insert("", "end", tags=(tag,),
                                             values=(c["client_name"],
                                                     c["client_days_remaining"]))
            avail = api.get_locker_availability()
            self._locker_lbl.config(
                text=f"Lockers: {avail['available']}/{avail['total']} available  "
                     f"| ₱{avail['price']:.2f} / {avail['rental_days']} days")
        except APIError as e:
            self._att_status.config(text=str(e))

    # ── Actions ───────────────────────────────────────────────

    def _enroll_new(self):
        name = self._entries["_name"].get().strip()
        contact = self._entries["_contact"].get().strip()
        address = self._entries["_address"].get().strip()
        sub = self._sub_var.get()
        if not name or not sub:
            self._enroll_status.config(
                text="Client name and subscription required.", fg="red")
            return
        try:
            resp = api.create_client({
                "client_name": name,
                "contact_number": contact or None,
                "address": address or None,
                "subscription_name": sub,
            })
            if resp.get("warning"):
                messagebox.showwarning("Note", resp["warning"])
            expires = (resp["client"].get("last_plan_expires_at") or "")[:10]
            self._enroll_status.config(
                text=f"Enrolled '{name}' — {sub} | Expires: {expires}",
                fg="#0F6E56")
            for e in self._entries.values():
                e.delete(0, "end")
            self._load_recent()
            self._load_clients()
            if self._queue:
                self._queue.put({
                    "type": "time_in",
                    "title": f"Welcome, {name}!",
                    "subtitle": f"Package: {sub}",
                })
        except APIError as e:
            self._enroll_status.config(text=str(e), fg="red")

    def _re_enroll(self):
        name = self._entries["_name"].get().strip()
        sub = self._sub_var.get()
        if not name or not sub:
            self._enroll_status.config(
                text="Client name and subscription required.", fg="red")
            return
        try:
            resp = api.re_enroll_client(name, sub)
            if resp.get("warning"):
                if not messagebox.askyesno("Warning", resp["warning"] +
                                           "\n\nProceed?"):
                    return
            expires = (resp["client"].get("last_plan_expires_at") or "")[:10]
            self._enroll_status.config(
                text=f"Re-enrolled '{name}' — {sub} | Expires: {expires}",
                fg="#0F6E56")
            self._entries["_name"].delete(0, "end")
            self._load_recent()
        except APIError as e:
            self._enroll_status.config(text=str(e), fg="red")

    def _enroll_fp(self):
        name = self._entries["_name"].get().strip()
        if not name:
            self._enroll_status.config(
                text="Enter client name first.", fg="red")
            return
        self._enroll_status.config(
            text="Place finger on scanner 3 times...", fg="#185FA5")
        self.update()
        try:
            api.enroll_fingerprint(name)
            self._enroll_status.config(
                text="Fingerprint enrolled successfully.", fg="#0F6E56")
        except APIError as e:
            self._enroll_status.config(text=str(e), fg="red")

    def _time_in(self):
        name = self._att_var.get()
        if not name:
            return
        if self._queue:
            self._queue.put({"type": "clear"})
        try:
            log = api.time_in(name)
            msg = f"Time-In: {name} at {log['time_in']}"
            self._att_status.config(text=msg, fg="#0F6E56")
            if self._queue:
                evt_type = "expiry_warn" if log.get("expiry_warning") else "time_in"
                subtitle = (f"Timed in at {log['time_in']}"
                            if evt_type == "time_in"
                            else f"Timed in at {log['time_in']}  |  "
                                 f"{log.get('days_remaining', 0)} day(s) remaining")
                self._queue.put({
                    "type": evt_type,
                    "title": f"Welcome back, {name}",
                    "subtitle": subtitle,
                })
            self._load_clients()
        except APIError as e:
            self._att_status.config(text=str(e), fg="red")
            if self._queue and e.status_code == 403:
                self._queue.put({
                    "type": "expired",
                    "title": "Subscription Expired",
                    "subtitle": "Please see staff to renew.",
                })

    def _time_out(self):
        name = self._att_var.get()
        if not name:
            return
        try:
            log = api.time_out(name)
            self._att_status.config(
                text=f"Time-Out: {name} at {log['time_out']}",
                fg="#854F0B")
            if self._queue:
                self._queue.put({
                    "type": "time_out",
                    "title": f"Goodbye, {name}",
                    "subtitle": f"Timed out at {log['time_out']}",
                })
            self._load_clients()
        except APIError as e:
            self._att_status.config(text=str(e), fg="red")

    def _rent_locker(self):
        name = self._att_var.get()
        if not name:
            messagebox.showwarning("Select", "Select a client first.")
            return
        try:
            result = api.rent_locker(name)
            messagebox.showinfo("Locker Rented",
                                f"Locker #{result['locker_number']} assigned to {name}\n"
                                f"Days: {result['days_added']}  |  "
                                f"Expires: {result['expires_at']}")
            self._load_clients()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def refresh(self):
        self._load_subs()
        self._load_recent()
        self._load_clients()
