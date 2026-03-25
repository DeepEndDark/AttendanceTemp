import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, timedelta

from app.api_client import api, APIError


class ReportsView(tk.Frame):
    """Admin — view daily sales reports and export as PDF."""

    def __init__(self, master):
        super().__init__(master)
        self.configure(bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Daily Reports", font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Export PDF", command=self._export_pdf,
                  bg="#185FA5", fg="white", relief="flat", padx=12).pack(side="right", padx=4)
        tk.Button(bar, text="Load Report", command=self._load_report,
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Date selector
        sel = tk.Frame(self, bg="white")
        sel.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        tk.Label(sel, text="Report date:", bg="white").pack(side="left")
        self._date_var = tk.StringVar(value=(date.today() - timedelta(days=1)).isoformat())
        tk.Entry(sel, textvariable=self._date_var, width=14).pack(side="left", padx=6)
        tk.Label(sel, text="  Available dates:", bg="white").pack(side="left")
        self._dates_cb = ttk.Combobox(sel, width=14, state="readonly")
        self._dates_cb.pack(side="left", padx=4)
        self._dates_cb.bind("<<ComboboxSelected>>",
                            lambda _: self._date_var.set(self._dates_cb.get()))

        # Summary
        self._summary_lbl = tk.Label(
            self, text="No report loaded.", fg="gray", bg="white", anchor="w", font=("", 10))
        self._summary_lbl.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 4))

        # Report table
        cols = ("item", "qty", "stock_lost", "revenue")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="none")
        for col, txt, w in [
            ("item", "Item Name", 220), ("qty", "Qty Sold", 90),
            ("stock_lost", "Stock Deducted", 120), ("revenue", "Revenue", 100)
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("total_row", background="#E1F5EE", font=("", 10, "bold"))

        sb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=3, column=0, sticky="nsew", padx=(16, 0), pady=4)
        sb.grid(row=3, column=1, sticky="ns", pady=4, padx=(0, 8))
        self.rowconfigure(3, weight=1)

        self._status = tk.Label(self, text="", fg="gray", bg="white", anchor="w")
        self._status.grid(row=4, column=0, sticky="ew", padx=16, pady=6)

        self._load_dates()

    def _load_dates(self):
        try:
            dates = api.list_report_dates()
            self._dates_cb["values"] = dates
            if dates:
                self._dates_cb.current(0)
                self._date_var.set(dates[0])
        except APIError:
            pass

    def _load_report(self):
        d = self._date_var.get().strip()
        try:
            report = api.get_report(d)
            self._populate(report)
            self._load_dates()
        except APIError as e:
            self._status.config(text=str(e))

    def _populate(self, report: dict):
        self._tree.delete(*self._tree.get_children())
        items = sorted(report.get("items", []), key=lambda i: i["item_name"])
        for it in items:
            self._tree.insert("", "end", values=(
                it["item_name"],
                it["total_qty_sold"],
                it["total_qty_sold"],
                f"{it['total_value']:.2f}",
            ))
        # Total row
        self._tree.insert("", "end", values=(
            "", "", "TOTAL", f"{report['total_revenue']:.2f}"
        ), tags=("total_row",))

        self._summary_lbl.config(
            text=f"Report for {report['report_date']}  |  "
                 f"{len(items)} item(s) sold  |  "
                 f"Total revenue: {report['total_revenue']:.2f}  |  "
                 f"Generated: {report['generated_at']}",
            fg="#185FA5",
        )
        self._status.config(text="Report loaded.")

    def _export_pdf(self):
        d = self._date_var.get().strip()
        if not d:
            messagebox.showwarning("No date", "Enter a report date first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"report_{d}.pdf",
            title="Save Report PDF",
        )
        if not path:
            return
        try:
            pdf_bytes = api.get_report_pdf(d)
            with open(path, "wb") as f:
                f.write(pdf_bytes)
            messagebox.showinfo("Exported", f"PDF saved to:\n{path}")
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def refresh(self):
        self._load_dates()
