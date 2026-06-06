"""Sales role — open sales for active (timed-in) clients only."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from fapp.api_client import api, APIError


class SalesOpenView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._queue = display_queue
        self._selected_uid: int | None = None
        self._all_sales: list[dict] = []
        self._sale_map: dict[int, dict] = {}
        self._loading = False
        self._detail_loading_uid: int | None = None
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

        # ── Left: open sales list ─────────────────────────────
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

        # ── Right: cart ───────────────────────────────────────
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

    # ---------------------------------------------------------
    # Async helpers
    # ---------------------------------------------------------

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        if text is not None:
            self._status.config(text=text)

    def _run_worker(self, target, name: str):
        threading.Thread(target=target, daemon=True, name=name).start()

    def _show_error(self, message: str):
        self._set_loading(False, message)

    # ---------------------------------------------------------
    # Refresh — headers only, background
    # ---------------------------------------------------------

    def refresh(self):
        if self._loading:
            return

        self._selected_uid = None
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")
        self._set_loading(True, "Loading sales...")

        self._run_worker(self._refresh_worker, "open-sales-refresh")

    def _refresh_worker(self):
        try:
            items = api.list_items()
            active = {c["client_name"] for c in api.list_active_clients()}
            sales = api.list_open_sales()   # headers only — item_list is []

            self.after(0, lambda: self._refresh_complete(items, active, sales, None))

        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _refresh_complete(
        self,
        items: list[dict],
        active: set[str],
        sales: list[dict],
        preserve_uid: int | None,
    ):
        self._item_cb["values"] = [
            i["item_name"] for i in items if i.get("available_stock", 0) > 0
        ]

        # Only open sales whose client is currently timed in
        visible = [s for s in sales if s.get("client_name") in active]

        self._all_sales = visible
        self._sale_map = {
            int(s["sales_uid"]): s
            for s in visible
            if s.get("sales_uid") is not None
        }

        self._sale_tree.delete(*self._sale_tree.get_children())
        for s in visible:
            self._sale_tree.insert(
                "", "end",
                iid=str(s["sales_uid"]),
                values=(s["sales_uid"], s["client_name"],
                        f"{s['total_price']:.2f}"),
            )

        self._status.config(text=f"{len(visible)} open sale(s) for active clients")

        if preserve_uid is not None and self._sale_tree.exists(str(preserve_uid)):
            self._sale_tree.selection_set(str(preserve_uid))
            self._sale_tree.focus(str(preserve_uid))
            self._sale_tree.see(str(preserve_uid))
            self._selected_uid = preserve_uid
            self._on_select()

        self._set_loading(False)

    # ---------------------------------------------------------
    # Selection — show total immediately, load items in background
    # ---------------------------------------------------------

    def _on_select(self, _=None):
        sel = self._sale_tree.selection()
        if not sel:
            return
        try:
            uid = int(sel[0])
        except ValueError:
            return

        self._selected_uid = uid
        sale = self._sale_map.get(uid)
        if not sale:
            return

        # Show cached total immediately — cart loads behind the scenes
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text=f"Total: ₱{sale.get('total_price', 0):.2f}")
        self._status.config(text=f"Loading items for sale #{uid}...")

        self._detail_loading_uid = uid
        self._run_worker(
            lambda: self._load_detail_worker(uid),
            "open-sales-load-detail",
        )

    def _load_detail_worker(self, uid: int):
        try:
            sale = api.get_sale(uid)
            self.after(0, lambda sale=sale, uid=uid: self._detail_loaded(uid, sale))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _detail_loaded(self, uid: int, sale: dict):
        # Discard if user already clicked a different sale
        if self._selected_uid != uid:
            return

        self._detail_loading_uid = None
        self._sale_map[uid] = sale

        self._item_tree.delete(*self._item_tree.get_children())
        for si in sale.get("item_list", []):
            self._item_tree.insert(
                "", "end",
                values=(si.get("item_name", ""),
                        si.get("item_qty", 0),
                        f"{si.get('item_total_price', 0):.2f}"),
            )
        self._total_lbl.config(text=f"Total: ₱{sale.get('total_price', 0):.2f}")
        self._status.config(text=f"Sale #{uid} loaded.")

    # ---------------------------------------------------------
    # Open new sale
    # ---------------------------------------------------------

    def _open_sale(self):
        if self._loading:
            return
        self._set_loading(True, "Loading active clients...")
        self._run_worker(self._open_sale_worker, "open-sales-load-clients")

    def _open_sale_worker(self):
        try:
            active = api.list_active_clients()
            self.after(0, lambda: self._open_sale_dialog(active))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _open_sale_dialog(self, active: list[dict]):
        self._set_loading(False)
        if not active:
            messagebox.showwarning("No active clients",
                                   "No clients are currently timed in.")
            return
        dlg = _PickClient(self, [c["client_name"] for c in active])
        if not dlg.result:
            return

        client_name = dlg.result
        self._set_loading(True, f"Opening sale for {client_name}...")
        self._run_worker(
            lambda: self._create_sale_worker(client_name),
            "open-sales-create",
        )

    def _create_sale_worker(self, client_name: str):
        try:
            sale = api.open_sale(client_name)
            self.after(0, lambda: self._sale_created(sale, client_name))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _sale_created(self, sale: dict, client_name: str):
        uid = sale.get("sales_uid")
        self._status.config(text=f"Opened sale #{uid} for {client_name}")
        self._set_loading(False)
        self._refresh_preserve(uid)

    # ---------------------------------------------------------
    # Add item
    # ---------------------------------------------------------

    def _add_item(self):
        if self._loading:
            return
        if self._selected_uid is None:
            messagebox.showwarning("No sale", "Select or open a sale first.")
            return
        if self._detail_loading_uid == self._selected_uid:
            messagebox.showinfo("Please Wait",
                                "Sale items are still loading. Try again in a moment.")
            return
        sale = self._sale_map.get(self._selected_uid)
        if sale and sale.get("sale_status") != "open":
            messagebox.showwarning("Closed Sale",
                                   "You can only add items to an open sale.")
            return
        name = self._item_var.get().strip()
        if not name:
            return
        try:
            qty = int(self._qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid", "Quantity must be a positive integer.")
            return

        uid = self._selected_uid
        self._set_loading(True, "Adding item...")
        self._run_worker(
            lambda: self._add_item_worker(uid, name, qty),
            "open-sales-add-item",
        )

    def _add_item_worker(self, uid: int, item_name: str, qty: int):
        try:
            api.add_item_to_sale(uid, item_name, qty)
            self.after(0, lambda: self._after_mutation(uid, "Item added."))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    # ---------------------------------------------------------
    # Remove item
    # ---------------------------------------------------------

    def _remove_item(self):
        if self._loading:
            return
        if self._selected_uid is None:
            return
        if self._detail_loading_uid == self._selected_uid:
            messagebox.showinfo("Please Wait",
                                "Sale items are still loading. Try again in a moment.")
            return
        sale = self._sale_map.get(self._selected_uid)
        if sale and sale.get("sale_status") != "open":
            messagebox.showwarning("Closed Sale",
                                   "You can only remove items from an open sale.")
            return
        sel = self._item_tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select an item to remove.")
            return
        item_name = self._item_tree.item(sel[0])["values"][0]
        uid = self._selected_uid
        self._set_loading(True, "Removing item...")
        self._run_worker(
            lambda: self._remove_item_worker(uid, item_name),
            "open-sales-remove-item",
        )

    def _remove_item_worker(self, uid: int, item_name: str):
        try:
            api.remove_item_from_sale(uid, item_name)
            self.after(0, lambda: self._after_mutation(uid, "Item removed."))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    # ---------------------------------------------------------
    # Close sale
    # ---------------------------------------------------------

    def _close_sale(self):
        if self._loading:
            return
        if self._selected_uid is None:
            messagebox.showwarning("No sale", "Select a sale to close.")
            return
        sale = self._sale_map.get(self._selected_uid)
        if sale and sale.get("sale_status") != "open":
            messagebox.showinfo("Already Closed", "This sale is already closed.")
            return
        uid = self._selected_uid
        if not messagebox.askyesno("Confirm",
                                   f"Close sale #{uid}? Stock will be deducted."):
            return

        self._set_loading(True, "Closing sale...")
        self._run_worker(
            lambda: self._close_sale_worker(uid),
            "open-sales-close",
        )

    def _close_sale_worker(self, uid: int):
        try:
            api.close_sale(uid)
            self.after(0, lambda: self._after_close(uid))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _after_close(self, uid: int):
        self._selected_uid = None
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")
        self._status.config(text=f"Sale #{uid} closed.")
        self._set_loading(False)
        self._refresh_preserve(None)

    # ---------------------------------------------------------
    # Shared post-mutation: reload detail for current sale
    # ---------------------------------------------------------

    def _after_mutation(self, uid: int, status: str):
        self._status.config(text=status)
        self._set_loading(False)
        self._refresh_preserve(uid)

    # ---------------------------------------------------------
    # Refresh preserving selection
    # ---------------------------------------------------------

    def _refresh_preserve(self, uid: int | None):
        if self._loading:
            return
        self._set_loading(True, "Refreshing sales...")
        self._run_worker(
            lambda: self._refresh_preserve_worker(uid),
            "open-sales-refresh-preserve",
        )

    def _refresh_preserve_worker(self, uid: int | None):
        try:
            items = api.list_items()
            active = {c["client_name"] for c in api.list_active_clients()}
            sales = api.list_open_sales()
            self.after(0, lambda: self._refresh_complete(items, active, sales, uid))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))


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