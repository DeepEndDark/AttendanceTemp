"""Admin — full client list with detail panel showing subscriptions,
attendance history, sales history, locker info."""
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class ClientsView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._queue = display_queue
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, columnspan=2,
                 sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Client List",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Enroll New", command=self._enroll,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Client list
        cols = ("uid", "name", "status", "days", "trainer", "locker", "expires")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("uid", "UID", 50), ("name", "Name", 140),
            ("status", "In/Out", 55), ("days", "Days", 55),
            ("trainer", "Trainer", 60), ("locker", "Locker", 55),
            ("expires", "Expires", 100),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("in", foreground="#0F6E56")
        self._tree.tag_configure("warn", foreground="#BA7517")
        self._tree.tag_configure("expired", foreground="#C0392B")
        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=1, column=0, sticky="nsew",
                        padx=(16, 0), pady=4)
        sb.grid(row=1, column=1, sticky="nsw", pady=4)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Detail panel
        self._detail = _ClientDetailPanel(self)
        self._detail.grid(row=1, column=1, sticky="nsew",
                          padx=(4, 16), pady=4)

        self._status_lbl = tk.Label(self, text="", fg="gray",
                                    bg="white", anchor="w")
        self._status_lbl.grid(row=2, column=0, columnspan=2,
                               sticky="ew", padx=16, pady=4)
        self.refresh()

    def refresh(self):
        try:
            clients = api.list_clients()
            self._tree.delete(*self._tree.get_children())
            for c in clients:
                days = c["client_days_remaining"]
                expires = (c.get("last_plan_expires_at") or "")[:10]
                locker = str(c["locker_number"]) if c.get("locker_number") else "—"
                trainer = c["client_trainer_days_remaining"]

                if days == 0:
                    tag = "expired"
                elif days <= 2:
                    tag = "warn"
                elif c["client_status"]:
                    tag = "in"
                else:
                    tag = ""

                self._tree.insert("", "end", tags=(tag,), values=(
                    c["client_uid"], c["client_name"],
                    "In" if c["client_status"] else "Out",
                    days, trainer if trainer > 0 else "—",
                    locker, expires,
                ))
            self._status_lbl.config(text=f"{len(clients)} client(s)")
        except APIError as e:
            self._status_lbl.config(text=str(e))

    def _selected_name(self, warn: bool = True):
        sel = self._tree.selection()
        if not sel:
            if warn:
                messagebox.showwarning("Select", "Select a client first.")
            return None
        return self._tree.item(sel[0])["values"][1]

    def _on_select(self, _=None):
        # Silent — no warning on programmatic or deselect events
        name = self._selected_name(warn=False)
        if name:
            self._detail.load(name)

    def _enroll(self):
        subs = api.list_subscriptions()
        if not subs:
            messagebox.showwarning("No plans",
                                   "Add subscription plans first.")
            return
        dlg = _EnrollDialog(self, subs)
        if dlg.result:
            self.refresh()   # client already created inside dialog

    def _edit(self):
        name = self._selected_name()
        if not name:
            return
        try:
            client = api.get_client(name)
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return
        dlg = _EditDialog(self, client)
        if dlg.result:
            try:
                api.update_client(name, dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        if messagebox.askyesno("Confirm", f"Delete client '{name}'?"):
            try:
                api.delete_client(name)
                self._detail.clear()
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _ClientDetailPanel(tk.Frame):
    """Right-side panel: identity, subscriptions, locker, attendance, sales."""
    def __init__(self, master):
        super().__init__(master, bg="white",
                         relief="groove", bd=1)
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.rowconfigure(5, weight=1)

        # ── Section 1: Identity ──────────────────────────────
        s1 = tk.LabelFrame(self, text="Client Info",
                           bg="white", padx=8, pady=6)
        s1.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._info_labels = {}
        fields = [
            ("UID", "uid"), ("Name", "name"),
            ("Contact", "contact"), ("Address", "address"),
            ("Registered", "created"), ("Last Renewed", "renewed"),
            ("Plan Expires", "expires"), ("Fingerprint", "fp"),
        ]
        for i, (lbl, key) in enumerate(fields):
            tk.Label(s1, text=f"{lbl}:", bg="white",
                     font=("", 9), anchor="w").grid(
                row=i, column=0, sticky="w")
            v = tk.Label(s1, text="—", bg="white",
                         font=("", 9), anchor="w",
                         wraplength=200)
            v.grid(row=i, column=1, sticky="w", padx=(8, 0))
            self._info_labels[key] = v

        # ── Section 2: Active subscriptions ──────────────────
        s2 = tk.LabelFrame(self, text="Active Subscriptions",
                           bg="white", padx=8, pady=6)
        s2.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self._sub_tree = ttk.Treeview(
            s2,
            columns=("plan", "days", "trainer", "hardcap", "expires"),
            show="headings", height=3)
        for col, txt, w in [
            ("plan", "Plan", 110), ("days", "Days", 45),
            ("trainer", "Trainer", 55), ("hardcap", "Hardcap", 55),
            ("expires", "Expires", 90),
        ]:
            self._sub_tree.heading(col, text=txt)
            self._sub_tree.column(col, width=w, anchor="center")
        self._sub_tree.pack(fill="x")

        # ── Section 3: Locker ─────────────────────────────────
        s3 = tk.LabelFrame(self, text="Locker",
                           bg="white", padx=8, pady=6)
        s3.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self._locker_lbl = tk.Label(s3, text="No locker assigned.",
                                    bg="white", font=("", 9))
        self._locker_lbl.pack(anchor="w")

        # ── Section 4: Attendance history ─────────────────────
        s4 = tk.LabelFrame(self, text="Attendance History",
                           bg="white", padx=8, pady=6)
        s4.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)
        s4.rowconfigure(0, weight=1)
        s4.columnconfigure(0, weight=1)
        self._att_tree = ttk.Treeview(
            s4,
            columns=("uid", "date", "in", "out"),
            show="headings", height=4)
        for col, txt, w in [
            ("uid", "UID", 45), ("date", "Date", 90),
            ("in", "Time In", 75), ("out", "Time Out", 75),
        ]:
            self._att_tree.heading(col, text=txt)
            self._att_tree.column(col, width=w, anchor="center")
        asb = ttk.Scrollbar(s4, orient="vertical",
                            command=self._att_tree.yview)
        self._att_tree.configure(yscrollcommand=asb.set)
        self._att_tree.grid(row=0, column=0, sticky="nsew")
        asb.grid(row=0, column=1, sticky="ns")

        # ── Section 5: Sales history ──────────────────────────
        s5 = tk.LabelFrame(self, text="Sales History",
                           bg="white", padx=8, pady=6)
        s5.grid(row=4, column=0, sticky="nsew", padx=8, pady=(4, 8))
        s5.rowconfigure(0, weight=1)
        s5.columnconfigure(0, weight=1)
        self._sales_tree = ttk.Treeview(
            s5,
            columns=("uid", "date", "items", "total", "status"),
            show="headings", height=4)
        for col, txt, w in [
            ("uid", "UID", 45), ("date", "Date", 90),
            ("items", "Items", 130), ("total", "Total ₱", 70),
            ("status", "Status", 60),
        ]:
            self._sales_tree.heading(col, text=txt)
            self._sales_tree.column(col, width=w, anchor="center")
        ssb = ttk.Scrollbar(s5, orient="vertical",
                            command=self._sales_tree.yview)
        self._sales_tree.configure(yscrollcommand=ssb.set)
        self._sales_tree.grid(row=0, column=0, sticky="nsew")
        ssb.grid(row=0, column=1, sticky="ns")

    def load(self, client_name: str):
        try:
            c = api.get_client(client_name)
        except APIError:
            return

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
        try:
            subs = api.get_client_subscriptions(client_name)
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
        except APIError:
            pass

        # Locker
        if c.get("locker_number"):
            self._locker_lbl.config(
                text=f"Locker #{c['locker_number']}  |  "
                     f"{c['client_locker_days_remaining']} day(s) remaining")
        else:
            self._locker_lbl.config(text="No locker assigned.")

        # Attendance
        self._att_tree.delete(*self._att_tree.get_children())
        try:
            logs = api.get_client_attendance(client_name)
            for l in logs[:50]:
                self._att_tree.insert("", "end", values=(
                    l["log_uid"], l["log_date"],
                    l["time_in"], l.get("time_out") or "—"))
        except APIError:
            pass

        # Sales
        self._sales_tree.delete(*self._sales_tree.get_children())
        try:
            sales = api.get_client_sales(client_name)
            for s in sales[:50]:
                items_str = ", ".join(
                    f"{i['item_name']} x{i['item_qty']}"
                    for i in s.get("item_list", []))
                self._sales_tree.insert("", "end", values=(
                    s["sales_uid"], s["sale_date"],
                    items_str, f"{s['total_price']:.2f}",
                    s["sale_status"].capitalize()))
        except APIError:
            pass

    def clear(self):
        for v in self._info_labels.values():
            v.config(text="—")
        self._sub_tree.delete(*self._sub_tree.get_children())
        self._att_tree.delete(*self._att_tree.get_children())
        self._sales_tree.delete(*self._sales_tree.get_children())
        self._locker_lbl.config(text="No locker assigned.")


class _EnrollDialog(tk.Toplevel):
    """
    Phase 1: fill details + subscription -> Enroll.
    Phase 2: confirmation + optional fingerprint enrollment inline.
    """
    def __init__(self, parent, subs: list[dict]):
        super().__init__(parent)
        self.title("Enroll New Client")
        self.configure(bg="white")
        self.resizable(False, False)
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
                 fg="#185FA5").grid(row=0, column=0, columnspan=2,
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
        btn_row.grid(row=6, column=0, columnspan=2,
                     pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Enroll",
                  command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#185FA5", fg="white").pack(side="right")
        self._entries["_name"].focus_set()

    def _save(self):
        name = self._entries["_name"].get().strip()
        sub  = self._sub_var.get()
        if not name or not sub:
            self._status.config(text="Client name and subscription are required.")
            return
        payload = {
            "client_name":    name,
            "contact_number": self._entries["_contact"].get().strip() or None,
            "address":        self._entries["_address"].get().strip() or None,
            "subscription_name": sub,
        }
        try:
            from fapp.api_client import api
            resp = api.create_client(payload)
            if resp.get("warning"):
                from tkinter import messagebox
                messagebox.showwarning("Note", resp["warning"])
            self.result = payload   # signal success to parent
        except Exception as e:
            self._status.config(text=str(e), fg="red")
            return
        self._phase1.destroy()
        self._build_phase2(name)

    def _build_phase2(self, name: str):
        self._phase2 = tk.Frame(self, bg="white", padx=24, pady=20)
        self._phase2.pack(fill="both", expand=True)

        tk.Label(self._phase2, text="Client Enrolled",
                 font=("", 13, "bold"),
                 bg="white", fg="#0F6E56").pack(anchor="w")
        tk.Label(self._phase2, text=name,
                 font=("", 11), bg="white", fg="#333").pack(anchor="w",
                                                             pady=(2, 16))
        tk.Frame(self._phase2, bg="#e0e0e0", height=1).pack(
            fill="x", pady=(0, 16))

        tk.Label(self._phase2, text="Enroll fingerprint?",
                 font=("", 10, "bold"), bg="white").pack(anchor="w")
        tk.Label(self._phase2,
                 text="Scan 3 times to register this client.\nYou can skip and do this later from the client list.",
                 font=("", 9), fg="#666",
                 bg="white", justify="left").pack(anchor="w", pady=(4, 14))

        self._fp_status = tk.Label(self._phase2, text="",
                                   bg="white", font=("", 9),
                                   fg="#185FA5", wraplength=280)
        self._fp_status.pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(self._phase2, bg="white")
        btn_row.pack(anchor="w")

        self._fp_btn = tk.Button(
            btn_row, text="Scan Fingerprint",
            command=lambda: self._start_fp(name),
            relief="flat", padx=12, pady=6,
            bg="#5B5AEF", fg="white")
        self._fp_btn.pack(side="left", padx=(0, 8))

        self._done_btn = tk.Button(
            btn_row, text="Done",
            command=self.destroy,
            relief="flat", padx=12, pady=6,
            bg="#f0f0f0")
        self._done_btn.pack(side="left")

    def _start_fp(self, name: str):
        self._fp_btn.config(state="disabled", text="Scanning...")
        self._fp_status.config(text="Place finger on scanner 3 times...",
                               fg="#185FA5")
        import threading
        threading.Thread(target=self._fp_worker,
                         args=(name,), daemon=True).start()

    def _fp_worker(self, name: str):
        try:
            from fapp.api_client import api
            api.enroll_fingerprint(name)
            self.after(0, self._fp_done_ok)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._fp_done_err(msg))

    def _fp_done_ok(self):
        self._fp_status.config(text="Fingerprint enrolled.", fg="#0F6E56")
        self._fp_btn.pack_forget()
        self._done_btn.config(bg="#185FA5", fg="white", text="Done")

    def _fp_done_err(self, msg: str):
        self._fp_status.config(text=f"Failed: {msg}", fg="red")
        self._fp_btn.config(state="normal", text="Try Again")


class _EditDialog(tk.Toplevel):
    def __init__(self, parent, client: dict):
        super().__init__(parent)
        self.title(f"Edit — {client['client_name']}")
        self.configure(bg="white")
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._client_name = client["client_name"]

        frame = tk.Frame(self, bg="white", padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=f"Edit: {client['client_name']}",
                 font=("", 11, "bold"), bg="white",
                 fg="#185FA5").grid(row=0, column=0, columnspan=2,
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

        # Fingerprint section
        tk.Frame(frame, bg="#e0e0e0", height=1).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(12, 8))

        fp_label = "Fingerprint: Enrolled" if client.get(
            "fingerprint_enrolled") else "Fingerprint: Not enrolled"
        fp_color = "#0F6E56" if client.get("fingerprint_enrolled") else "#888"
        tk.Label(frame, text=fp_label, bg="white",
                 fg=fp_color, font=("", 9)).grid(
            row=4, column=0, columnspan=2, sticky="w")

        self._fp_status = tk.Label(frame, text="", bg="white",
                                   fg="#185FA5", font=("", 9), wraplength=260)
        self._fp_status.grid(row=5, column=0, columnspan=2,
                             sticky="w", pady=(2, 0))

        self._fp_btn = tk.Button(frame,
                                 text="Re-scan Fingerprint",
                                 command=self._start_fp,
                                 relief="flat", padx=10, pady=4,
                                 bg="#5B5AEF", fg="white")
        self._fp_btn.grid(row=6, column=0, columnspan=2,
                          sticky="w", pady=(6, 0))

        btn_row = tk.Frame(frame, bg="white")
        btn_row.grid(row=7, column=0, columnspan=2,
                     pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Save", command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#185FA5", fg="white").pack(side="right")
        self.wait_window()

    def _start_fp(self):
        self._fp_btn.config(state="disabled", text="Scanning...")
        self._fp_status.config(text="Place finger 3 times...", fg="#185FA5")
        import threading
        threading.Thread(target=self._fp_worker, daemon=True).start()

    def _fp_worker(self):
        try:
            from fapp.api_client import api
            api.enroll_fingerprint(self._client_name)
            self.after(0, lambda: self._fp_status.config(
                text="Fingerprint updated.", fg="#0F6E56"))
            self.after(0, lambda: self._fp_btn.config(
                state="normal", text="Re-scan Fingerprint"))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._fp_status.config(
                text=f"Failed: {msg}", fg="red"))
            self.after(0, lambda: self._fp_btn.config(
                state="normal", text="Try Again"))

    def _save(self):
        self.result = {
            "contact_number": self._entries["contact_number"].get().strip() or None,
            "address":        self._entries["address"].get().strip() or None,
        }
        self.destroy()
