import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date
from fapp.api_client import api, APIError


class AdminAttendanceView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._queue = display_queue
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Attendance Logs",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-Out", command=self._time_out,
                  bg="#f0a030", relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-In", command=self._time_in,
                  bg="#30a060", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Filter row
        flt = tk.Frame(self, bg="white")
        flt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        tk.Label(flt, text="Client:", bg="white").pack(side="left")
        self._client_var = tk.StringVar()
        self._client_cb = ttk.Combobox(flt, textvariable=self._client_var,
                                       width=18, state="readonly")
        self._client_cb.pack(side="left", padx=4)

        tk.Label(flt, text="Date:", bg="white").pack(side="left", padx=(8, 2))
        self._date_exact = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_exact,
                 width=11).pack(side="left")

        tk.Label(flt, text="From:", bg="white").pack(side="left", padx=(8, 2))
        self._date_from = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_from,
                 width=11).pack(side="left")

        tk.Label(flt, text="To:", bg="white").pack(side="left", padx=(4, 2))
        self._date_to = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_to,
                 width=11).pack(side="left")

        tk.Button(flt, text="Filter", command=self._filter,
                  relief="flat", padx=8).pack(side="left", padx=6)
        tk.Button(flt, text="Clear", command=self.refresh,
                  relief="flat", padx=8).pack(side="left")

        cols = ("uid", "date", "client", "time_in", "time_out")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("uid", "UID", 60), ("date", "Date", 100),
            ("client", "Client", 180),
            ("time_in", "Time In", 90), ("time_out", "Time Out", 90),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("date_group", background="#E6F1FB")

        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(16, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=3, column=0, sticky="ew",
                          padx=16, pady=6)
        self.refresh()

    def refresh(self):
        self._load_clients()
        self._date_exact.set("")
        self._date_from.set("")
        self._date_to.set("")
        try:
            logs = api.list_attendance()
            self._populate(logs)
        except APIError as e:
            self._status.config(text=str(e))

    def _load_clients(self):
        try:
            names = [c["client_name"] for c in api.list_clients()]
            self._client_cb["values"] = [""] + names
            self._client_cb.set("")
        except APIError:
            pass

    def _filter(self):
        client = self._client_var.get() or None
        exact = self._date_exact.get().strip() or None
        dfrom = self._date_from.get().strip() or None
        dto = self._date_to.get().strip() or None
        try:
            logs = api.list_attendance(client_name=client,
                                       date_exact=exact,
                                       date_from=dfrom, date_to=dto)
            self._populate(logs)
            self._status.config(text=f"{len(logs)} record(s) — filtered")
        except APIError as e:
            self._status.config(text=str(e))

    def _populate(self, logs: list):
        self._tree.delete(*self._tree.get_children())
        by_date: dict[str, list] = {}
        for log in logs:
            by_date.setdefault(log["log_date"], []).append(log)
        for d in sorted(by_date.keys(), reverse=True):
            diid = f"d_{d}"
            self._tree.insert("", "end", iid=diid,
                              values=("", d, "", "", ""),
                              tags=("date_group",))
            for log in sorted(by_date[d], key=lambda l: l["client_name"]):
                self._tree.insert(diid, "end", values=(
                    log["log_uid"], log["log_date"],
                    log["client_name"], log["time_in"],
                    log.get("time_out") or "—"))
            self._tree.item(diid, open=True)
        self._status.config(text=f"{len(logs)} record(s)")

    def _time_in(self):
        name = self._client_var.get()
        if not name:
            messagebox.showwarning("Select", "Select a client first.")
            return
        if self._queue:
            self._queue.put({"type": "clear"})
        try:
            log = api.time_in(name)
            messagebox.showinfo("Time-In",
                                f"{name} timed in at {log['time_in']}")
            if self._queue:
                evt = "expiry_warn" if log.get("expiry_warning") else "time_in"
                sub = (f"Timed in at {log['time_in']}  |  "
                       f"{log.get('days_remaining', 0)} day(s) left"
                       if evt == "expiry_warn"
                       else f"Timed in at {log['time_in']}")
                self._queue.put({"type": evt,
                                 "title": f"Welcome back, {name}",
                                 "subtitle": sub})
            self.refresh()
        except APIError as e:
            if self._queue and e.status_code == 403:
                self._queue.put({"type": "expired",
                                 "title": "Subscription Expired",
                                 "subtitle": "Please see staff to renew."})
            messagebox.showerror("Error", str(e))

    def _time_out(self):
        name = self._client_var.get()
        if not name:
            messagebox.showwarning("Select", "Select a client first.")
            return
        try:
            log = api.time_out(name)
            messagebox.showinfo("Time-Out",
                                f"{name} timed out at {log['time_out']}")
            if self._queue:
                self._queue.put({"type": "time_out",
                                 "title": f"Goodbye, {name}",
                                 "subtitle": f"Timed out at {log['time_out']}"})
            self.refresh()
        except APIError as e:
            messagebox.showerror("Error", str(e))
