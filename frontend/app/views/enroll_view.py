import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from app.api_client import api, APIError


class EnrollView(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.configure(bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        tk.Label(self, text="Client Enrollment", font=("", 14, "bold"), bg="white").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 4))

        # Enroll panel
        pane = tk.LabelFrame(self, text="New Enrollment / Re-enroll", bg="white", padx=14, pady=14)
        pane.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=10)
        pane.columnconfigure(1, weight=1)

        tk.Label(pane, text="Client name:", bg="white").grid(row=0, column=0, sticky="w", pady=6)
        self._name_var = tk.StringVar()
        tk.Entry(pane, textvariable=self._name_var, width=26).grid(row=0, column=1, sticky="ew", padx=(8,0), pady=6)

        tk.Label(pane, text="Duration:", bg="white").grid(row=1, column=0, sticky="w", pady=6)
        self._dur_var = tk.StringVar()
        tk.Entry(pane, textvariable=self._dur_var, width=26).grid(row=1, column=1, sticky="ew", padx=(8,0), pady=6)

        tk.Label(pane, text="Budget:", bg="white").grid(row=2, column=0, sticky="w", pady=6)
        self._budget_var = tk.StringVar(value="0.0")
        tk.Entry(pane, textvariable=self._budget_var, width=26).grid(row=2, column=1, sticky="ew", padx=(8,0), pady=6)

        btn_row = tk.Frame(pane, bg="white")
        btn_row.grid(row=3, column=0, columnspan=2, pady=(12,0))
        tk.Button(btn_row, text="Enroll New", command=self._enroll_new, bg="#185FA5", fg="white", padx=12, pady=6, relief="flat").pack(side="left", padx=4)
        tk.Button(btn_row, text="Re-enroll", command=self._re_enroll, bg="#0F6E56", fg="white", padx=12, pady=6, relief="flat").pack(side="left", padx=4)

        self._enroll_status = tk.Label(pane, text="", fg="#185FA5", bg="white", wraplength=280)
        self._enroll_status.grid(row=4, column=0, columnspan=2, pady=(8,0))

        tk.Label(pane, text="Recent clients:", bg="white", font=("", 9)).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14,2))
        self._recent_tree = ttk.Treeview(pane, columns=("name","duration","enrolled"), show="headings", height=6)
        for col, txt, w in [("name","Client",130),("duration","Duration",100),("enrolled","Enrolled",140)]:
            self._recent_tree.heading(col, text=txt)
            self._recent_tree.column(col, width=w, anchor="center")
        self._recent_tree.grid(row=6, column=0, columnspan=2, sticky="ew", pady=4)
        self._load_recent()

        # Attendance panel
        apane = tk.LabelFrame(self, text="Time-In / Time-Out", bg="white", padx=14, pady=14)
        apane.grid(row=1, column=1, sticky="nsew", padx=(8,20), pady=10)
        apane.columnconfigure(0, weight=1)

        tk.Label(apane, text="Select client:", bg="white").pack(anchor="w")
        self._att_var = tk.StringVar()
        self._att_cb = ttk.Combobox(apane, textvariable=self._att_var, state="readonly", width=26)
        self._att_cb.pack(fill="x", pady=(2,12))

        btn2 = tk.Frame(apane, bg="white")
        btn2.pack(fill="x")
        tk.Button(btn2, text="Time-In", command=self._time_in, bg="#30a060", fg="white", padx=14, pady=8, relief="flat").pack(side="left", padx=4)
        tk.Button(btn2, text="Time-Out", command=self._time_out, bg="#f0a030", padx=14, pady=8, relief="flat").pack(side="left", padx=4)
        tk.Button(btn2, text="Refresh", command=self._load_att_clients, padx=10, pady=8, relief="flat").pack(side="right", padx=4)

        self._att_status = tk.Label(apane, text="", fg="gray", bg="white", wraplength=240)
        self._att_status.pack(pady=(12,0), anchor="w")

        tk.Label(apane, text="Currently timed in:", bg="white", font=("",9)).pack(anchor="w", pady=(16,2))
        self._active_tree = ttk.Treeview(apane, columns=("name","duration"), show="headings", height=8)
        for col, txt, w in [("name","Client",160),("duration","Duration",120)]:
            self._active_tree.heading(col, text=txt)
            self._active_tree.column(col, width=w, anchor="center")
        self._active_tree.pack(fill="both", expand=True, pady=4)

        self._load_att_clients()

    def _enroll_new(self):
        name = self._name_var.get().strip()
        dur = self._dur_var.get().strip()
        if not name or not dur:
            self._enroll_status.config(text="Name and duration are required.", fg="red")
            return
        try:
            budget = float(self._budget_var.get() or "0")
        except ValueError:
            self._enroll_status.config(text="Budget must be a number.", fg="red")
            return
        try:
            c = api.create_client(name, dur, budget)
            enrolled = (c.get("last_enrolled_at") or "")[:10]
            self._enroll_status.config(text=f"Enrolled '{name}' — {dur} | {enrolled}", fg="#0F6E56")
            self._name_var.set(""); self._dur_var.set(""); self._budget_var.set("0.0")
            self._load_recent(); self._load_att_clients()
        except APIError as e:
            self._enroll_status.config(text=str(e), fg="red")

    def _re_enroll(self):
        name = self._name_var.get().strip()
        dur = self._dur_var.get().strip()
        if not name or not dur:
            self._enroll_status.config(text="Name and new duration required.", fg="red")
            return
        try:
            c = api.re_enroll_client(name, dur)
            enrolled = (c.get("last_enrolled_at") or "")[:10]
            self._enroll_status.config(text=f"Re-enrolled '{name}' — {dur} | {enrolled}", fg="#0F6E56")
            self._dur_var.set(""); self._load_recent()
        except APIError as e:
            self._enroll_status.config(text=str(e), fg="red")

    def _load_recent(self):
        self._recent_tree.delete(*self._recent_tree.get_children())
        try:
            clients = sorted(api.list_clients(), key=lambda c: c.get("last_enrolled_at") or "", reverse=True)[:10]
            for c in clients:
                self._recent_tree.insert("", "end", values=(c["client_name"], c["client_duration"], (c.get("last_enrolled_at") or "")[:10]))
        except APIError:
            pass

    def _load_att_clients(self):
        try:
            all_clients = api.list_clients()
            self._att_cb["values"] = [c["client_name"] for c in all_clients]
            if all_clients and not self._att_var.get():
                self._att_var.set(all_clients[0]["client_name"])
            self._active_tree.delete(*self._active_tree.get_children())
            for c in all_clients:
                if c.get("client_status"):
                    self._active_tree.insert("", "end", values=(c["client_name"], c["client_duration"]))
        except APIError as e:
            self._att_status.config(text=str(e))

    def _time_in(self):
        name = self._att_var.get()
        if not name: return
        try:
            log = api.time_in(name)
            self._att_status.config(text=f"Time-In: {name} at {log['time_in']}", fg="#0F6E56")
            self._load_att_clients()
        except APIError as e:
            self._att_status.config(text=str(e), fg="red")

    def _time_out(self):
        name = self._att_var.get()
        if not name: return
        try:
            log = api.time_out(name)
            self._att_status.config(text=f"Time-Out: {name} at {log['time_out']}", fg="#854F0B")
            self._load_att_clients()
        except APIError as e:
            self._att_status.config(text=str(e), fg="red")

    def refresh(self):
        self._load_recent(); self._load_att_clients()
