import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from calendar import month_name

from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import _CalPicker


def _pick_month_year(parent, year_var: tk.StringVar,
                     month_var: tk.StringVar):
    """Popup to pick year+month."""
    dlg = tk.Toplevel(parent)
    dlg.title("Pick Month")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg, text="Year:").grid(row=0, column=0,
                                     padx=10, pady=8, sticky="w")
    yv = tk.StringVar(value=year_var.get())
    tk.Entry(dlg, textvariable=yv, width=6).grid(row=0, column=1, padx=6)

    tk.Label(dlg, text="Month:").grid(row=1, column=0,
                                      padx=10, pady=4, sticky="w")
    mv = tk.StringVar(value=month_var.get())
    months = [f"{i} — {month_name[i]}" for i in range(1, 13)]
    cb = ttk.Combobox(dlg, textvariable=mv, values=months,
                      state="readonly", width=16)
    # pre-select current month
    try:
        cb.current(int(month_var.get()) - 1)
    except Exception:
        cb.current(0)
    cb.grid(row=1, column=1, padx=6, pady=4)

    err = tk.Label(dlg, text="", fg="red")
    err.grid(row=2, column=0, columnspan=2)

    def _ok():
        try:
            y = int(yv.get())
            m_raw = mv.get().split("—")[0].strip()
            m = int(m_raw)
            if not (1 <= m <= 12):
                raise ValueError
        except ValueError:
            err.config(text="Invalid year or month.")
            return
        year_var.set(str(y))
        month_var.set(str(m))
        dlg.destroy()

    btn = tk.Frame(dlg)
    btn.grid(row=3, column=0, columnspan=2, pady=10)
    tk.Button(btn, text="OK", command=_ok,
              width=8).pack(side="left", padx=6)
    tk.Button(btn, text="Cancel", command=dlg.destroy,
              width=8).pack(side="left", padx=6)
    dlg.wait_window()


class ReportsView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
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

        nb.add(_DailyReportTab(nb),   text="  Daily Report  ")
        nb.add(_MonthlyReportTab(nb), text="  Monthly Report  ")

    def refresh(self):
        pass


# ── Shared populate logic ──────────────────────────────────────

def _populate_tree(tree: ttk.Treeview, report: dict):
    """
    Populates a report tree with three sections mirroring the PDF:
      1. Items Sold summary
      2. Subscription Plans Sold summary
      3. Per-client breakdown (client name once as group header)
    """
    tree.delete(*tree.get_children())
    purchases = report.get("purchases", [])
    grand     = report.get("total_revenue", 0.0)

    # ── Aggregate summaries ──────────────────────────────────
    item_totals: dict[str, dict] = {}
    sub_totals:  dict[str, dict] = {}

    for p in purchases:
        for line in p.get("lines", []):
            name = line["name"]
            qty  = line.get("qty", 0)
            cost = line.get("cost", 0.0)
            if line.get("is_subscription"):
                d = sub_totals.setdefault(name, {"qty": 0, "rev": 0.0})
            else:
                d = item_totals.setdefault(name, {"qty": 0, "rev": 0.0})
            d["qty"] += qty
            d["rev"] += cost

    # ── Section 1: Items Sold ────────────────────────────────
    if item_totals:
        sec = tree.insert("", "end",
                          values=("ITEMS SOLD", "", "", "", ""),
                          tags=("section",))
        for name in sorted(item_totals):
            d = item_totals[name]
            tree.insert(sec, "end",
                        values=("", name, d["qty"],
                                f"{d['rev']:.2f}", "Item"),
                        tags=("item_row",))
        tree.insert(sec, "end",
                    values=("", "TOTAL",
                            sum(d["qty"] for d in item_totals.values()),
                            f"{sum(d['rev'] for d in item_totals.values()):.2f}",
                            ""),
                    tags=("subtotal",))
        tree.item(sec, open=True)

    # ── Section 2: Subscriptions Sold ───────────────────────
    if sub_totals:
        sec = tree.insert("", "end",
                          values=("SUBSCRIPTION PLANS SOLD", "", "", "", ""),
                          tags=("section",))
        for name in sorted(sub_totals):
            d = sub_totals[name]
            tree.insert(sec, "end",
                        values=("", name, d["qty"],
                                f"{d['rev']:.2f}", "Subscription"),
                        tags=("item_row",))
        tree.insert(sec, "end",
                    values=("", "TOTAL",
                            sum(d["qty"] for d in sub_totals.values()),
                            f"{sum(d['rev'] for d in sub_totals.values()):.2f}",
                            ""),
                    tags=("subtotal",))
        tree.item(sec, open=True)

    # ── Section 3: Per-client breakdown ─────────────────────
    if purchases:
        sec = tree.insert("", "end",
                          values=("SALES BREAKDOWN BY CLIENT",
                                  "", "", "", ""),
                          tags=("section",))
        for p in sorted(purchases, key=lambda x: x["client_name"]):
            client_row = tree.insert(
                sec, "end",
                values=(p["client_name"], "", "", "", ""),
                tags=("client_hdr",))
            for line in p.get("lines", []):
                kind = ("Subscription" if line.get("is_subscription")
                        else "Locker" if line.get("is_locker")
                        else "Item")
                tree.insert(client_row, "end",
                            values=("", line["name"],
                                    line["qty"],
                                    f"{line['cost']:.2f}", kind),
                            tags=("item_row",))
            tree.insert(client_row, "end",
                        values=("", "CLIENT TOTAL", "",
                                f"{p['client_total']:.2f}", ""),
                        tags=("subtotal",))
            tree.item(client_row, open=True)
        tree.item(sec, open=True)

    # ── Grand total ──────────────────────────────────────────
    tree.insert("", "end",
                values=("", "GRAND TOTAL", "", f"{grand:.2f}", ""),
                tags=("grand",))


def _configure_tags(tree: ttk.Treeview):
    tree.tag_configure("section",    background="#185FA5",
                       foreground="white", font=("", 10, "bold"))
    tree.tag_configure("client_hdr", background="#dce8f5",
                       font=("", 9, "bold"))
    tree.tag_configure("item_row",   background="white")
    tree.tag_configure("subtotal",   background="#E1F5EE",
                       font=("", 9, "bold"))
    tree.tag_configure("grand",      background="#0C447C",
                       foreground="white", font=("", 10, "bold"))


def _make_tree(parent) -> ttk.Treeview:
    cols = ("group", "item", "qty", "cost", "type")
    tree = ttk.Treeview(parent, columns=cols,
                        show="headings", selectmode="none")
    for col, txt, w in [
        ("group", "Group / Client", 170),
        ("item",  "Item / Plan",    180),
        ("qty",   "Qty",             50),
        ("cost",  "Cost ₱",          90),
        ("type",  "Type",            90),
    ]:
        tree.heading(col, text=txt)
        tree.column(col, width=w, anchor="center")
    _configure_tags(tree)
    return tree


# ── Daily tab ─────────────────────────────────────────────────

class _DailyReportTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="white")
        self._loading = False
        self._report: dict | None = None
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctrl = tk.Frame(self, bg="white")
        ctrl.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        tk.Label(ctrl, text="Date:", bg="white").pack(side="left")
        self._date_var = tk.StringVar(value=date.today().isoformat())
        ent = tk.Entry(ctrl, textvariable=self._date_var,
                       width=11, state="readonly")
        ent.pack(side="left", padx=4)
        tk.Button(ctrl, text="📅",
                  command=self._pick_date,
                  relief="flat", padx=2).pack(side="left")
        tk.Button(ctrl, text="Today",
                  command=lambda: self._date_var.set(
                      date.today().isoformat()),
                  relief="flat", padx=8).pack(side="left", padx=4)
        tk.Button(ctrl, text="Yesterday",
                  command=lambda: self._date_var.set(
                      (date.today().replace(day=date.today().day - 1)
                       if date.today().day > 1
                       else date.today()).isoformat()),
                  relief="flat", padx=8).pack(side="left", padx=2)
        self._load_btn = tk.Button(ctrl, text="Load",
                                   command=self._load,
                                   bg="#185FA5", fg="white",
                                   relief="flat", padx=10)
        self._load_btn.pack(side="left", padx=6)
        self._pdf_btn = tk.Button(ctrl, text="Export PDF",
                                  command=self._export_pdf,
                                  relief="flat", padx=10)
        self._pdf_btn.pack(side="left", padx=2)

        self._summary_lbl = tk.Label(
            self, text="No report loaded.", fg="gray",
            bg="white", font=("", 10), anchor="w")
        self._summary_lbl.grid(row=1, column=0, sticky="ew",
                                padx=12, pady=(0, 4))

        self._tree = _make_tree(self)
        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(12, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0, 8))

    def _pick_date(self):
        try:
            init = date.fromisoformat(self._date_var.get())
        except ValueError:
            init = date.today()
        dlg = _CalPicker(self.winfo_toplevel(), init)
        if dlg.result:
            self._date_var.set(dlg.result.isoformat())

    # ── Async load ────────────────────────────────────────────

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        state = "disabled" if value else "normal"
        self._load_btn.config(state=state,
                              text="Loading..." if value else "Load")
        self._pdf_btn.config(state=state)
        if text:
            self._summary_lbl.config(text=text, fg="gray")

    def _load(self):
        if self._loading:
            return
        d = self._date_var.get().strip()
        self._set_loading(True, f"Loading report for {d}...")
        threading.Thread(target=self._load_worker,
                         args=(d,), daemon=True).start()

    def _load_worker(self, d: str):
        try:
            report = api.get_daily_report(d)
            self.after(0, lambda: self._load_complete(report))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._load_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._load_error(msg))

    def _load_complete(self, report: dict):
        self._report = report
        _populate_tree(self._tree, report)
        grand     = report.get("total_revenue", 0.0)
        purchases = report.get("purchases", [])
        self._summary_lbl.config(
            text=(f"Date: {report['report_date']}  |  "
                  f"{len(purchases)} client(s)  |  "
                  f"Total Revenue: ₱{grand:.2f}"),
            fg="#185FA5")
        self._set_loading(False)

    def _load_error(self, msg: str):
        self._summary_lbl.config(text=msg, fg="red")
        self._set_loading(False)

    # ── Async export ──────────────────────────────────────────

    def _export_pdf(self):
        if self._loading:
            return
        d = self._date_var.get().strip()
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"daily_{d}.pdf",
            title="Save Daily Report")
        if not path:
            return
        self._set_loading(True, "Generating PDF...")
        threading.Thread(target=self._pdf_worker,
                         args=(d, path), daemon=True).start()

    def _pdf_worker(self, d: str, path: str):
        try:
            pdf = api.get_daily_pdf(d)
            with open(path, "wb") as f:
                f.write(pdf)
            self.after(0, lambda: messagebox.showinfo(
                "Exported", f"Saved to:\n{path}"))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: messagebox.showerror(
                "Error", msg))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda msg=msg: messagebox.showerror(
                "Error", msg))
        self.after(0, lambda: self._set_loading(False))


# ── Monthly tab ───────────────────────────────────────────────

class _MonthlyReportTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="white")
        self._loading = False
        self._report: dict | None = None
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctrl = tk.Frame(self, bg="white")
        ctrl.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        self._year_var  = tk.StringVar(value=str(date.today().year))
        self._month_var = tk.StringVar(value=str(date.today().month))

        self._period_lbl = tk.Label(
            ctrl,
            text=self._period_text(),
            bg="white", font=("", 10, "bold"), fg="#185FA5")
        self._period_lbl.pack(side="left")

        tk.Button(ctrl, text="📅 Pick Month",
                  command=self._pick_month,
                  relief="flat", padx=8).pack(side="left", padx=6)
        tk.Button(ctrl, text="This Month",
                  command=self._this_month,
                  relief="flat", padx=8).pack(side="left", padx=2)

        self._load_btn = tk.Button(ctrl, text="Load",
                                   command=self._load,
                                   bg="#185FA5", fg="white",
                                   relief="flat", padx=10)
        self._load_btn.pack(side="left", padx=6)
        self._pdf_btn = tk.Button(ctrl, text="Export PDF",
                                  command=self._export_pdf,
                                  relief="flat", padx=10)
        self._pdf_btn.pack(side="left", padx=2)

        self._summary_lbl = tk.Label(
            self, text="No report loaded.", fg="gray",
            bg="white", font=("", 10), anchor="w")
        self._summary_lbl.grid(row=1, column=0, sticky="ew",
                                padx=12, pady=(0, 4))

        self._tree = _make_tree(self)
        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(12, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns", pady=4, padx=(0, 8))

    def _period_text(self):
        try:
            m = int(self._month_var.get())
            y = int(self._year_var.get())
            return f"{month_name[m]} {y}"
        except Exception:
            return "—"

    def _this_month(self):
        self._year_var.set(str(date.today().year))
        self._month_var.set(str(date.today().month))
        self._period_lbl.config(text=self._period_text())

    def _pick_month(self):
        _pick_month_year(self.winfo_toplevel(),
                         self._year_var, self._month_var)
        self._period_lbl.config(text=self._period_text())

    # ── Async load ────────────────────────────────────────────

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        state = "disabled" if value else "normal"
        self._load_btn.config(state=state,
                              text="Loading..." if value else "Load")
        self._pdf_btn.config(state=state)
        if text:
            self._summary_lbl.config(text=text, fg="gray")

    def _load(self):
        if self._loading:
            return
        try:
            y = int(self._year_var.get())
            m = int(self._month_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Select a valid month first.")
            return
        self._set_loading(True,
                          f"Loading report for {month_name[m]} {y}...")
        threading.Thread(target=self._load_worker,
                         args=(y, m), daemon=True).start()

    def _load_worker(self, y: int, m: int):
        try:
            report = api.get_monthly_report(y, m)
            self.after(0, lambda: self._load_complete(report))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._load_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._load_error(msg))

    def _load_complete(self, report: dict):
        self._report = report
        _populate_tree(self._tree, report)
        grand     = report.get("total_revenue", 0.0)
        purchases = report.get("purchases", [])
        m = report.get("month", int(self._month_var.get()))
        y = report.get("year",  int(self._year_var.get()))
        self._summary_lbl.config(
            text=(f"{month_name[m]} {y}  |  "
                  f"{len(purchases)} client(s)  |  "
                  f"Total Revenue: ₱{grand:.2f}"),
            fg="#185FA5")
        self._set_loading(False)

    def _load_error(self, msg: str):
        self._summary_lbl.config(text=msg, fg="red")
        self._set_loading(False)

    # ── Async export ──────────────────────────────────────────

    def _export_pdf(self):
        if self._loading:
            return
        try:
            y = int(self._year_var.get())
            m = int(self._month_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Select a valid month first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"monthly_{y}_{m:02d}.pdf",
            title="Save Monthly Report")
        if not path:
            return
        self._set_loading(True, "Generating PDF...")
        threading.Thread(target=self._pdf_worker,
                         args=(y, m, path), daemon=True).start()

    def _pdf_worker(self, y: int, m: int, path: str):
        try:
            pdf = api.get_monthly_pdf(y, m)
            with open(path, "wb") as f:
                f.write(pdf)
            self.after(0, lambda: messagebox.showinfo(
                "Exported", f"Saved to:\n{path}"))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: messagebox.showerror(
                "Error", msg))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda msg=msg: messagebox.showerror(
                "Error", msg))
        self.after(0, lambda: self._set_loading(False))