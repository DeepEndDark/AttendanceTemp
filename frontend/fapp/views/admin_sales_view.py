import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class AdminSalesView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._selected_uid: int | None = None
        self._all_sales: list[dict] = []
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Sales Logs",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Close Sale", command=self._close_sale,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="New Sale", command=self._open_sale,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Filters
        flt = tk.Frame(self, bg="white")
        flt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        tk.Label(flt, text="Client:", bg="white").pack(side="left")
        self._client_var = tk.StringVar()
        tk.Entry(flt, textvariable=self._client_var,
                 width=14).pack(side="left", padx=4)

        tk.Label(flt, text="Item:", bg="white").pack(side="left", padx=(6, 2))
        self._item_var = tk.StringVar()
        tk.Entry(flt, textvariable=self._item_var,
                 width=14).pack(side="left", padx=4)

        tk.Label(flt, text="Date:", bg="white").pack(side="left", padx=(6, 2))
        self._date_exact = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_exact,
                 width=11).pack(side="left")

        tk.Label(flt, text="From:", bg="white").pack(side="left", padx=(4, 2))
        self._date_from = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_from,
                 width=11).pack(side="left")

        tk.Label(flt, text="To:", bg="white").pack(side="left", padx=(4, 2))
        self._date_to = tk.StringVar()
        tk.Entry(flt, textvariable=self._date_to,
                 width=11).pack(side="left")

        self._status_var = tk.StringVar(value="all")
        for val, txt in [("all", "All"), ("open", "Open"),
                         ("closed", "Closed")]:
            tk.Radiobutton(flt, text=txt, variable=self._status_var,
                           value=val, bg="white",
                           command=self._apply_filter).pack(
                side="left", padx=2)

        tk.Button(flt, text="Filter", command=self._filter,
                  relief="flat", padx=8).pack(side="left", padx=6)
        tk.Button(flt, text="Clear", command=self.refresh,
                  relief="flat", padx=6).pack(side="left")

        # Split
        split = tk.Frame(self, bg="white")
        split.grid(row=2, column=0, sticky="nsew",
                   padx=16, pady=(0, 12))
        split.columnconfigure(0, weight=3)
        split.columnconfigure(1, weight=2)
        split.rowconfigure(0, weight=1)

        left = tk.LabelFrame(split, text="Sales", bg="white")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        cols = ("uid", "date", "client", "status", "total")
        self._tree = ttk.Treeview(left, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("uid", "UID", 60), ("date", "Date", 90),
            ("client", "Client", 140), ("status", "Status", 70),
            ("total", "Total ₱", 80),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(left, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._tree.tag_configure("open", foreground="#185FA5")
        self._tree.tag_configure("date_group", background="#F1EFE8")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.LabelFrame(split, text="Items", bg="white")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Add/remove item bar for open sales
        add_bar = tk.Frame(right, bg="white")
        add_bar.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        tk.Label(add_bar, text="Item:", bg="white").pack(side="left")
        self._add_item_var = tk.StringVar()
        self._add_item_cb = ttk.Combobox(
            add_bar, textvariable=self._add_item_var,
            width=14, state="readonly")
        self._add_item_cb.pack(side="left", padx=4)
        tk.Label(add_bar, text="Qty:", bg="white").pack(side="left")
        self._qty_var = tk.StringVar(value="1")
        tk.Entry(add_bar, textvariable=self._qty_var,
                 width=4).pack(side="left", padx=2)
        tk.Button(add_bar, text="Add", command=self._add_item,
                  bg="#0F6E56", fg="white",
                  relief="flat", padx=6).pack(side="left", padx=4)
        tk.Button(add_bar, text="Remove", command=self._remove_item,
                  relief="flat", padx=6).pack(side="left")

        icols = ("item", "qty", "subtotal")
        self._item_tree = ttk.Treeview(right, columns=icols,
                                       show="headings")
        for col, txt, w in [("item", "Item", 150),
                             ("qty", "Qty", 50),
                             ("subtotal", "Subtotal ₱", 90)]:
            self._item_tree.heading(col, text=txt)
            self._item_tree.column(col, width=w, anchor="center")
        isb = ttk.Scrollbar(right, orient="vertical",
                            command=self._item_tree.yview)
        self._item_tree.configure(yscrollcommand=isb.set)
        self._item_tree.grid(row=1, column=0, sticky="nsew",
                             padx=(6, 0), pady=4)
        isb.grid(row=1, column=1, sticky="ns")

        self._total_lbl = tk.Label(right, text="Total: ₱0.00",
                                   font=("", 10, "bold"),
                                   bg="white", anchor="e")
        self._total_lbl.grid(row=2, column=0, sticky="e",
                             padx=10, pady=6)

        self._status_lbl = tk.Label(self, text="", fg="gray",
                                    bg="white", anchor="w")
        self._status_lbl.grid(row=3, column=0, sticky="ew",
                               padx=16, pady=4)
        self.refresh()

    def refresh(self):
        self._client_var.set("")
        self._item_var.set("")
        self._date_exact.set("")
        self._date_from.set("")
        self._date_to.set("")
        self._status_var.set("all")
        self._load_catalogue()
        try:
            self._all_sales = api.list_all_sales()
            self._apply_filter()
        except APIError as e:
            self._status_lbl.config(text=str(e))

    def _load_catalogue(self):
        try:
            items = api.list_items()
            self._add_item_cb["values"] = [
                i["item_name"] for i in items
                if i.get("available_stock", 0) > 0]
        except APIError:
            pass

    def _filter(self):
        try:
            self._all_sales = api.list_all_sales(
                client_name=self._client_var.get().strip() or None,
                item_name=self._item_var.get().strip() or None,
                date_exact=self._date_exact.get().strip() or None,
                date_from=self._date_from.get().strip() or None,
                date_to=self._date_to.get().strip() or None,
                sale_status=self._status_var.get()
                if self._status_var.get() != "all" else None,
            )
            self._apply_filter()
        except APIError as e:
            self._status_lbl.config(text=str(e))

    def _apply_filter(self):
        self._tree.delete(*self._tree.get_children())
        by_date: dict[str, list] = {}
        for s in self._all_sales:
            by_date.setdefault(s["sale_date"], []).append(s)
        for d in sorted(by_date.keys(), reverse=True):
            diid = f"d_{d}"
            self._tree.insert("", "end", iid=diid,
                              values=("", d, "", "", ""),
                              tags=("date_group",))
            for s in sorted(by_date[d], key=lambda x: x["client_name"]):
                tag = "open" if s["sale_status"] == "open" else ""
                self._tree.insert(diid, "end",
                                  iid=str(s["sales_uid"]),
                                  values=(s["sales_uid"], s["sale_date"],
                                          s["client_name"],
                                          s["sale_status"].capitalize(),
                                          f"{s['total_price']:.2f}"),
                                  tags=(tag,))
            self._tree.item(diid, open=True)
        self._status_lbl.config(text=f"{len(self._all_sales)} sale(s)")

    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        try:
            uid = int(sel[0])
        except ValueError:
            return
        self._selected_uid = uid
        sale = next((s for s in self._all_sales
                     if s["sales_uid"] == uid), None)
        if not sale:
            return
        self._item_tree.delete(*self._item_tree.get_children())
        for si in sale.get("item_list", []):
            self._item_tree.insert("", "end", values=(
                si["item_name"], si["item_qty"],
                f"{si['item_total_price']:.2f}"))
        self._total_lbl.config(
            text=f"Total: ₱{sale['total_price']:.2f}")

    def _open_sale(self):
        try:
            active = api.list_active_clients()
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return
        if not active:
            messagebox.showwarning("No active clients",
                                   "No clients are currently timed in.")
            return
        from fapp.views.sales_open_view import _PickClient
        dlg = _PickClient(self, [c["client_name"] for c in active])
        if dlg.result:
            try:
                sale = api.open_sale(dlg.result)
                self._status_lbl.config(
                    text=f"Opened sale #{sale['sales_uid']} for {dlg.result}")
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _add_item(self):
        if self._selected_uid is None:
            messagebox.showwarning("No sale",
                                   "Select an open sale first.")
            return
        name = self._add_item_var.get()
        if not name:
            return
        try:
            qty = int(self._qty_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Quantity must be an integer.")
            return
        try:
            api.add_item_to_sale(self._selected_uid, name, qty)
            self._all_sales = api.list_all_sales()
            self._apply_filter()
            if self._tree.exists(str(self._selected_uid)):
                self._tree.selection_set(str(self._selected_uid))
                self._on_select()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def _remove_item(self):
        if self._selected_uid is None:
            return
        sel = self._item_tree.selection()
        if not sel:
            return
        item_name = self._item_tree.item(sel[0])["values"][0]
        try:
            api.remove_item_from_sale(self._selected_uid, item_name)
            self._all_sales = api.list_all_sales()
            self._apply_filter()
            if self._tree.exists(str(self._selected_uid)):
                self._tree.selection_set(str(self._selected_uid))
                self._on_select()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def _close_sale(self):
        if self._selected_uid is None:
            messagebox.showwarning("Select", "Select an open sale.")
            return
        if not messagebox.askyesno("Confirm",
                                   f"Close sale #{self._selected_uid}?"):
            return
        try:
            api.close_sale(self._selected_uid)
            self._selected_uid = None
            self.refresh()
        except APIError as e:
            messagebox.showerror("Error", str(e))
