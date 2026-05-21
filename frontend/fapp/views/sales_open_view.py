"""Sales role — open sales for active (timed-in) clients only."""
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class SalesOpenView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._queue = display_queue
        self._selected_uid: int | None = None
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Open Sales",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Close Sale", command=self._close_sale,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="New Sale", command=self._open_sale,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        split = tk.Frame(self, bg="white")
        split.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        split.columnconfigure(0, weight=2)
        split.columnconfigure(1, weight=3)
        split.rowconfigure(0, weight=1)

        left = tk.LabelFrame(split, text="Open sales", bg="white")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        cols = ("uid", "client", "total")
        self._sale_tree = ttk.Treeview(left, columns=cols,
                                       show="headings", selectmode="browse")
        for col, txt, w in [("uid", "UID", 60),
                             ("client", "Client", 140),
                             ("total", "Total ₱", 80)]:
            self._sale_tree.heading(col, text=txt)
            self._sale_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(left, orient="vertical",
                           command=self._sale_tree.yview)
        self._sale_tree.configure(yscrollcommand=sb.set)
        self._sale_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._sale_tree.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.LabelFrame(split, text="Items in selected sale",
                              bg="white")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        add_bar = tk.Frame(right, bg="white")
        add_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        tk.Label(add_bar, text="Item:", bg="white").pack(side="left")
        self._item_var = tk.StringVar()
        self._item_cb = ttk.Combobox(add_bar, textvariable=self._item_var,
                                     width=18, state="readonly")
        self._item_cb.pack(side="left", padx=4)
        tk.Label(add_bar, text="Qty:", bg="white").pack(side="left",
                                                        padx=(8, 2))
        self._qty_var = tk.StringVar(value="1")
        tk.Entry(add_bar, textvariable=self._qty_var,
                 width=5).pack(side="left")
        tk.Button(add_bar, text="Add", command=self._add_item,
                  bg="#0F6E56", fg="white",
                  relief="flat", padx=8).pack(side="left", padx=6)
        tk.Button(add_bar, text="Remove", command=self._remove_item,
                  relief="flat", padx=8).pack(side="left")

        icols = ("item", "qty", "subtotal")
        self._item_tree = ttk.Treeview(right, columns=icols,
                                       show="headings", selectmode="browse")
        for col, txt, w in [("item", "Item", 160),
                             ("qty", "Qty", 60),
                             ("subtotal", "Subtotal ₱", 90)]:
            self._item_tree.heading(col, text=txt)
            self._item_tree.column(col, width=w, anchor="center")
        isb = ttk.Scrollbar(right, orient="vertical",
                            command=self._item_tree.yview)
        self._item_tree.configure(yscrollcommand=isb.set)
        self._item_tree.grid(row=1, column=0, sticky="nsew",
                             padx=(8, 0), pady=(0, 4))
        isb.grid(row=1, column=1, sticky="ns")

        self._total_lbl = tk.Label(right, text="Total: ₱0.00",
                                   font=("", 11, "bold"),
                                   bg="white", anchor="e")
        self._total_lbl.grid(row=2, column=0, sticky="e",
                             padx=12, pady=6)

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=2, column=0, sticky="ew",
                          padx=16, pady=4)

        self.refresh()

    def refresh(self):
        self._load_catalogue()
        self._load_open_sales()

    def _load_catalogue(self):
        try:
            items = api.list_items()
            names = [i["item_name"]
                     for i in items if i.get("available_stock", 0) > 0]
            self._item_cb["values"] = names
            if names:
                self._item_cb.current(0)
        except APIError:
            pass

    def _load_open_sales(self):
        self._sale_tree.delete(*self._sale_tree.get_children())
        try:
            active = {c["client_name"] for c in api.list_active_clients()}
            sales = api.list_open_sales()
            shown = 0
            for s in sales:
                if s["client_name"] in active:
                    self._sale_tree.insert("", "end",
                                          iid=str(s["sales_uid"]),
                                          values=(s["sales_uid"],
                                                  s["client_name"],
                                                  f"{s['total_price']:.2f}"))
                    shown += 1
            self._status.config(
                text=f"{shown} open sale(s) for active clients")
        except APIError as e:
            self._status.config(text=str(e))

    def _on_select(self, _=None):
        sel = self._sale_tree.selection()
        if not sel:
            return
        self._selected_uid = int(sel[0])
        self._load_cart()

    def _load_cart(self):
        self._item_tree.delete(*self._item_tree.get_children())
        if self._selected_uid is None:
            return
        try:
            for s in api.list_open_sales():
                if s["sales_uid"] == self._selected_uid:
                    for si in s.get("item_list", []):
                        self._item_tree.insert(
                            "", "end",
                            values=(si["item_name"], si["item_qty"],
                                    f"{si['item_total_price']:.2f}"))
                    self._total_lbl.config(
                        text=f"Total: ₱{s['total_price']:.2f}")
                    break
        except APIError as e:
            self._status.config(text=str(e))

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
        dlg = _PickClient(self, [c["client_name"] for c in active])
        if dlg.result:
            try:
                sale = api.open_sale(dlg.result)
                self._status.config(
                    text=f"Opened sale #{sale['sales_uid']} "
                         f"for {dlg.result}")
                self.refresh()
                self._sale_tree.selection_set(str(sale["sales_uid"]))
                self._selected_uid = sale["sales_uid"]
                self._load_cart()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _add_item(self):
        if self._selected_uid is None:
            messagebox.showwarning("No sale",
                                   "Select or open a sale first.")
            return
        name = self._item_var.get()
        if not name:
            return
        try:
            qty = int(self._qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Quantity must be a positive integer.")
            return
        try:
            sale = api.add_item_to_sale(self._selected_uid, name, qty)
            self._status.config(text=f"Added {qty}x {name}")
            if self._sale_tree.exists(str(self._selected_uid)):
                self._sale_tree.item(
                    str(self._selected_uid),
                    values=(sale["sales_uid"], sale["client_name"],
                            f"{sale['total_price']:.2f}"))
            self._load_cart()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def _remove_item(self):
        if self._selected_uid is None:
            return
        sel = self._item_tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select an item to remove.")
            return
        item_name = self._item_tree.item(sel[0])["values"][0]
        try:
            sale = api.remove_item_from_sale(self._selected_uid, item_name)
            self._status.config(text=f"Removed {item_name}")
            if self._sale_tree.exists(str(self._selected_uid)):
                self._sale_tree.item(
                    str(self._selected_uid),
                    values=(sale["sales_uid"], sale["client_name"],
                            f"{sale['total_price']:.2f}"))
            self._load_cart()
        except APIError as e:
            messagebox.showerror("Error", str(e))

    def _close_sale(self):
        if self._selected_uid is None:
            messagebox.showwarning("No sale", "Select a sale to close.")
            return
        if not messagebox.askyesno(
                "Confirm",
                f"Close sale #{self._selected_uid}? "
                "Stock will be deducted."):
            return
        try:
            api.close_sale(self._selected_uid)
            self._status.config(
                text=f"Sale #{self._selected_uid} closed.")
            self._selected_uid = None
            self._item_tree.delete(*self._item_tree.get_children())
            self._total_lbl.config(text="Total: ₱0.00")
            self.refresh()
        except APIError as e:
            messagebox.showerror("Error", str(e))


class _PickClient(tk.Toplevel):
    def __init__(self, parent, names):
        super().__init__(parent)
        self.title("Select Active Client")
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        tk.Label(self, text="Client (currently timed in):").grid(
            row=0, column=0, padx=14, pady=10)
        self._var = tk.StringVar()
        cb = ttk.Combobox(self, textvariable=self._var,
                          values=names, state="readonly", width=24)
        cb.grid(row=1, column=0, padx=14, pady=4)
        if names:
            cb.current(0)
        btn = tk.Frame(self)
        btn.grid(row=2, column=0, pady=12)
        tk.Button(btn, text="Open Sale", command=self._ok,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _ok(self):
        self.result = self._var.get()
        self.destroy()
