import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from app.api_client import api, APIError


class AdminAttendanceView(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.configure(bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Attendance Logs", font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh, relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-Out", command=self._time_out, bg="#f0a030", relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-In", command=self._time_in, bg="#30a060", fg="white", relief="flat", padx=10).pack(side="right", padx=4)

        flt = tk.Frame(self, bg="white")
        flt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        tk.Label(flt, text="Client:", bg="white").pack(side="left")
        self._att_var = tk.StringVar()
        self._att_cb = ttk.Combobox(flt, textvariable=self._att_var, width=22, state="readonly")
        self._att_cb.pack(side="left", padx=4)
        tk.Label(flt, text="  Filter date:", bg="white").pack(side="left")
        self._date_var = tk.StringVar(value=date.today().isoformat())
        tk.Entry(flt, textvariable=self._date_var, width=12).pack(side="left", padx=4)
        tk.Button(flt, text="Filter", command=self._filter, relief="flat", padx=8).pack(side="left", padx=4)
        tk.Button(flt, text="Show All", command=self.refresh, relief="flat", padx=8).pack(side="left", padx=2)

        cols = ("uid", "date", "client", "time_in", "time_out")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, txt, w in [("uid","UID",60),("date","Date",100),("client","Client",180),("time_in","Time In",90),("time_out","Time Out",90)]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew", padx=(16,0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0,8))
        self._tree.tag_configure("date_group", background="#E6F1FB")

        self._status = tk.Label(self, text="", fg="gray", bg="white", anchor="w")
        self._status.grid(row=3, column=0, sticky="ew", padx=16, pady=6)
        self.refresh()

    def refresh(self):
        self._load_clients()
        try:
            logs = api.list_attendance()
            self._populate(logs)
        except APIError as e:
            self._status.config(text=str(e))

    def _load_clients(self):
        try:
            clients = api.list_clients()
            names = [c["client_name"] for c in clients]
            self._att_cb["values"] = names
            if names and not self._att_var.get():
                self._att_var.set(names[0])
        except APIError:
            pass

    def _filter(self):
        d = self._date_var.get().strip()
        try:
            logs = api.get_attendance_by_date(d)
            self._populate(logs)
            self._status.config(text=f"{len(logs)} record(s) for {d}")
        except APIError as e:
            self._status.config(text=str(e))

    def _populate(self, logs):
        self._tree.delete(*self._tree.get_children())
        by_date = {}
        for log in logs:
            by_date.setdefault(log["log_date"], []).append(log)
        for d in sorted(by_date.keys(), reverse=True):
            diid = f"date_{d}"
            self._tree.insert("", "end", iid=diid, values=("", d, "", "", ""), tags=("date_group",))
            for log in sorted(by_date[d], key=lambda l: l["client_name"]):
                self._tree.insert(diid, "end", values=(log["log_uid"], log["log_date"], log["client_name"], log["time_in"], log.get("time_out") or "—"))
            self._tree.item(diid, open=True)
        self._status.config(text=f"{len(logs)} record(s)")

    def _time_in(self):
        name = self._att_var.get()
        if not name: return
        try:
            log = api.time_in(name)
            messagebox.showinfo("Time-In", f"{name} timed in at {log['time_in']}")
            self.refresh()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def _time_out(self):
        name = self._att_var.get()
        if not name: return
        try:
            log = api.time_out(name)
            messagebox.showinfo("Time-Out", f"{name} timed out at {log['time_out']}")
            self.refresh()
        except APIError as e:
            messagebox.showerror("Error", str(e))
