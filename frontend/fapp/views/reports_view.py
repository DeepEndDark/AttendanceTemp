import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, timedelta
from fapp.api_client import api, APIError


class ReportsView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        tk.Label(self, text="Reports", font=("", 14, "bold"),
                 bg="white").grid(row=0, column=0, sticky="w",
                                  padx=16, pady=(14, 8))

        nb = ttk.Notebook(self)
        nb.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        daily_tab = _DailyReportTab(nb)
        monthly_tab = _MonthlyReportTab(nb)

        nb.add(daily_tab,   text="  Daily Report  ")
        nb.add(monthly_tab, text="  Monthly Report  ")

    def refresh(self):
        pass


class _DailyReportTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctrl = tk.Frame(self, bg="white")
        ctrl.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        tk.Label(ctrl, text="Date (YYYY-MM-DD):",
                 bg="white").pack(side="left")
        self._date_var = tk.StringVar(
            value=(date.today() - timedelta(days=1)).isoformat())
        tk.Entry(ctrl, textvariable=self._date_var,
                 width=14).pack(side="left", padx=6)
        tk.Button(ctrl, text="Load", command=self._load,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(ctrl, text="Export PDF",
                  command=self._export_pdf,
                  relief="flat", padx=10).pack(side="left", padx=4)

        self._summary_lbl = tk.Label(
            self, text="No report loaded.", fg="gray",
            bg="white", font=("", 10), anchor="w")
        self._summary_lbl.grid(row=1, column=0, sticky="ew",
                                padx=12, pady=(0, 4))

        self._tree = ttk.Treeview(
            self,
            columns=("client", "item", "qty", "cost", "sub"),
            show="headings", selectmode="none")
        for col, txt, w in [
            ("client", "Client", 160), ("item", "Item / Plan", 180),
            ("qty", "Qty", 50), ("cost", "Cost ₱", 90),
            ("sub", "Type", 80),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("subtotal",
                                 background="#E1F5EE",
                                 font=("", 9, "bold"))
        self._tree.tag_configure("grand",
                                 background="#185FA5",
                                 foreground="white",
                                 font=("", 10, "bold"))

        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(12, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._report: dict | None = None

    def _load(self):
        d = self._date_var.get().strip()
        try:
            self._report = api.get_daily_report(d)
            self._populate(self._report)
        except APIError as e:
            self._summary_lbl.config(text=str(e), fg="red")

    def _populate(self, report: dict):
        self._tree.delete(*self._tree.get_children())
        grand = report.get("total_revenue", 0.0)
        purchases = report.get("purchases", [])

        for p in purchases:
            for line in p.get("lines", []):
                type_lbl = ("Subscription" if line.get("is_subscription")
                            else "Locker" if line.get("is_locker")
                            else "Item")
                self._tree.insert("", "end", values=(
                    p["client_name"], line["name"],
                    line["qty"], f"{line['cost']:.2f}", type_lbl))
            self._tree.insert("", "end", tags=("subtotal",), values=(
                p["client_name"], "CLIENT TOTAL",
                "", f"{p['client_total']:.2f}", ""))

        self._tree.insert("", "end", tags=("grand",), values=(
            "", "GRAND TOTAL", "", f"{grand:.2f}", ""))

        self._summary_lbl.config(
            text=f"Date: {report['report_date']}  |  "
                 f"{len(purchases)} client(s)  |  "
                 f"Total Revenue: ₱{grand:.2f}",
            fg="#185FA5")

    def _export_pdf(self):
        d = self._date_var.get().strip()
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"daily_{d}.pdf",
            title="Save Daily Report")
        if not path:
            return
        try:
            pdf = api.get_daily_pdf(d)
            with open(path, "wb") as f:
                f.write(pdf)
            messagebox.showinfo("Exported", f"Saved to:\n{path}")
        except APIError as e:
            messagebox.showerror("Error", str(e))


class _MonthlyReportTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctrl = tk.Frame(self, bg="white")
        ctrl.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        tk.Label(ctrl, text="Year:", bg="white").pack(side="left")
        self._year_var = tk.StringVar(value=str(date.today().year))
        tk.Entry(ctrl, textvariable=self._year_var,
                 width=6).pack(side="left", padx=4)

        tk.Label(ctrl, text="Month (1-12):",
                 bg="white").pack(side="left", padx=(8, 2))
        self._month_var = tk.StringVar(value=str(date.today().month))
        tk.Entry(ctrl, textvariable=self._month_var,
                 width=4).pack(side="left", padx=4)

        tk.Button(ctrl, text="Load", command=self._load,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(ctrl, text="Export PDF",
                  command=self._export_pdf,
                  relief="flat", padx=10).pack(side="left", padx=4)

        self._summary_lbl = tk.Label(
            self, text="No report loaded.", fg="gray",
            bg="white", font=("", 10), anchor="w")
        self._summary_lbl.grid(row=1, column=0, sticky="ew",
                                padx=12, pady=(0, 4))

        self._tree = ttk.Treeview(
            self,
            columns=("client", "item", "qty", "cost", "type"),
            show="headings", selectmode="none")
        for col, txt, w in [
            ("client", "Client", 160), ("item", "Item / Plan", 180),
            ("qty", "Qty", 50), ("cost", "Cost ₱", 90),
            ("type", "Type", 80),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("subtotal",
                                 background="#E1F5EE",
                                 font=("", 9, "bold"))
        self._tree.tag_configure("grand",
                                 background="#185FA5",
                                 foreground="white",
                                 font=("", 10, "bold"))

        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(12, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._report: dict | None = None

    def _load(self):
        try:
            y = int(self._year_var.get())
            m = int(self._month_var.get())
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Year and month must be integers.")
            return
        try:
            self._report = api.get_monthly_report(y, m)
            self._populate(self._report)
        except APIError as e:
            self._summary_lbl.config(text=str(e), fg="red")

    def _populate(self, report: dict):
        self._tree.delete(*self._tree.get_children())
        grand = report.get("total_revenue", 0.0)
        purchases = report.get("purchases", [])

        for p in purchases:
            for line in p.get("lines", []):
                type_lbl = ("Subscription" if line.get("is_subscription")
                            else "Locker" if line.get("is_locker")
                            else "Item")
                self._tree.insert("", "end", values=(
                    p["client_name"], line["name"],
                    line["qty"], f"{line['cost']:.2f}", type_lbl))
            self._tree.insert("", "end", tags=("subtotal",), values=(
                p["client_name"], "CLIENT TOTAL",
                "", f"{p['client_total']:.2f}", ""))

        self._tree.insert("", "end", tags=("grand",), values=(
            "", "GRAND TOTAL", "", f"{grand:.2f}", ""))

        from calendar import month_name
        self._summary_lbl.config(
            text=f"{month_name[report['month']]} {report['year']}  |  "
                 f"{len(purchases)} client(s)  |  "
                 f"Total Revenue: ₱{grand:.2f}",
            fg="#185FA5")

    def _export_pdf(self):
        try:
            y = int(self._year_var.get())
            m = int(self._month_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Enter valid year and month.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"monthly_{y}_{m:02d}.pdf",
            title="Save Monthly Report")
        if not path:
            return
        try:
            pdf = api.get_monthly_pdf(y, m)
            with open(path, "wb") as f:
                f.write(pdf)
            messagebox.showinfo("Exported", f"Saved to:\n{path}")
        except APIError as e:
            messagebox.showerror("Error", str(e))
