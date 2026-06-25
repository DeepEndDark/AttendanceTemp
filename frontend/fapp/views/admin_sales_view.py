import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import _CalPicker, _make_date_entry


class AdminSalesView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
        super().__init__(master, bg="white")

        self._selected_uid: int | None = None
        self._all_sales: list[dict] = []
        self._all_clients: list[dict] = []
        self._sale_map: dict[int, dict] = {}
        self._loading = False
        self._detail_loading_uid: int | None = None

        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)

        tk.Label(
            bar,
            text="Sales Logs",
            font=("", 14, "bold"),
            bg="white"
        ).pack(side="left")

        tk.Button(
            bar,
            text="Refresh",
            command=self.refresh,
            relief="flat",
            padx=10
        ).pack(side="right", padx=4)

        tk.Button(
            bar,
            text="Close Sale",
            command=self._close_sale,
            bg="#e04040",
            fg="white",
            relief="flat",
            padx=10
        ).pack(side="right", padx=4)

        self._delete_sale_btn = tk.Button(
            bar,
            text="Delete Sale",
            command=self._delete_sale,
            bg="#8B1E1E",
            fg="white",
            relief="flat",
            padx=10
        )

        if api.is_admin:
            self._delete_sale_btn.pack(side="right", padx=4)

        tk.Button(
            bar,
            text="New Sale",
            command=self._open_sale,
            bg="#E8500A",
            fg="white",
            relief="flat",
            padx=10
        ).pack(side="right", padx=4)

        # Filters
        flt = tk.Frame(self, bg="white")
        flt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        tk.Label(flt, text="Client:", bg="white").pack(side="left")
        self._client_var = tk.StringVar()
        tk.Entry(
            flt,
            textvariable=self._client_var,
            width=14
        ).pack(side="left", padx=4)

        tk.Label(
            flt,
            text="Item:",
            bg="white"
        ).pack(side="left", padx=(6, 2))

        self._item_var = tk.StringVar()
        tk.Entry(
            flt,
            textvariable=self._item_var,
            width=14
        ).pack(side="left", padx=4)

        self._date_exact = tk.StringVar()
        self._date_from  = tk.StringVar()
        self._date_to    = tk.StringVar()

        _make_date_entry(flt, self._date_exact, "Date:").pack(
            side="left", padx=(6, 2))
        _make_date_entry(flt, self._date_from, "From:").pack(
            side="left", padx=(4, 2))
        _make_date_entry(flt, self._date_to, "To:").pack(
            side="left", padx=(4, 2))

        self._status_var = tk.StringVar(value="all")

        for val, txt in [
            ("all", "All"),
            ("open", "Open"),
            ("closed", "Closed"),
        ]:
            tk.Radiobutton(
                flt,
                text=txt,
                variable=self._status_var,
                value=val,
                bg="white",
                command=self._apply_filter
            ).pack(side="left", padx=2)

        tk.Button(
            flt,
            text="Filter",
            command=self._filter,
            relief="flat",
            padx=8
        ).pack(side="left", padx=6)

        tk.Button(
            flt,
            text="Clear",
            command=self.refresh,
            relief="flat",
            padx=6
        ).pack(side="left")

        tk.Label(flt, text="Plan:", bg="white").pack(side="left", padx=(10, 0))
        self._plan_filter_var = tk.StringVar(value="All Plans")
        self._plan_filter_cb = ttk.Combobox(
            flt, textvariable=self._plan_filter_var,
            values=["All Plans"], state="readonly", width=16)
        self._plan_filter_cb.pack(side="left", padx=4)
        self._plan_filter_cb.bind("<<ComboboxSelected>>",
                                  lambda _e: self._apply_filter())

        # Split
        split = tk.Frame(self, bg="white")
        split.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=16,
            pady=(0, 12)
        )

        split.columnconfigure(0, weight=3)
        split.columnconfigure(1, weight=2)
        split.rowconfigure(0, weight=1)

        left = tk.LabelFrame(split, text="Sales", bg="white")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        cols = ("chk", "uid", "date", "client", "status", "total")

        self._tree = ttk.Treeview(
            left,
            columns=cols,
            show="headings",
            selectmode="extended"
        )

        for col, txt, w in [
            ("chk",    "☐",        28),
            ("uid",    "UID",       60),
            ("date",   "Date",      90),
            ("client", "Client",   140),
            ("status", "Status",    70),
            ("total",  "Total ₱",   80),
        ]:
            self._tree.heading(col, text=txt,
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, anchor="center")
        self._tree.column("uid", width=0, minwidth=0, stretch=False)
        self._tree.heading("uid", text="")
        self._tree.column("chk", width=28, minwidth=28, stretch=False)
        self._tree.heading("chk", text="☐", command=self._toggle_all)

        self._checked: set[str] = set()
        self._sort_col: str | None = None
        self._sort_asc: bool = True

        sb = ttk.Scrollbar(
            left,
            orient="vertical",
            command=self._tree.yview
        )

        self._tree.configure(yscrollcommand=sb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("open", foreground="#E8500A")
        self._tree.tag_configure("date_group", background="#F1EFE8")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<ButtonRelease-1>", self._on_click)

        right = tk.LabelFrame(split, text="Items", bg="white")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Add/remove item bar
        add_bar = tk.Frame(right, bg="white")
        add_bar.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        tk.Label(add_bar, text="Item:", bg="white").pack(side="left")

        self._add_item_var = tk.StringVar()

        self._add_item_cb = ttk.Combobox(
            add_bar,
            textvariable=self._add_item_var,
            width=14,
            state="readonly"
        )

        self._add_item_cb.pack(side="left", padx=4)

        tk.Label(add_bar, text="Qty:", bg="white").pack(side="left")

        self._qty_var = tk.StringVar(value="1")

        tk.Entry(
            add_bar,
            textvariable=self._qty_var,
            width=4
        ).pack(side="left", padx=2)

        tk.Button(
            add_bar,
            text="Add",
            command=self._add_item,
            bg="#0F6E56",
            fg="white",
            relief="flat",
            padx=6
        ).pack(side="left", padx=4)

        tk.Button(
            add_bar,
            text="Remove",
            command=self._remove_item,
            relief="flat",
            padx=6
        ).pack(side="left")

        icols = ("item", "qty", "subtotal")

        self._item_tree = ttk.Treeview(
            right,
            columns=icols,
            show="headings"
        )

        for col, txt, w in [
            ("item", "Item", 150),
            ("qty", "Qty", 50),
            ("subtotal", "Subtotal ₱", 90),
        ]:
            self._item_tree.heading(col, text=txt)
            self._item_tree.column(col, width=w, anchor="center")

        isb = ttk.Scrollbar(
            right,
            orient="vertical",
            command=self._item_tree.yview
        )

        self._item_tree.configure(yscrollcommand=isb.set)

        self._item_tree.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(6, 0),
            pady=4
        )

        isb.grid(row=1, column=1, sticky="ns")

        self._total_lbl = tk.Label(
            right,
            text="Total: ₱0.00",
            font=("", 10, "bold"),
            bg="white",
            anchor="e"
        )

        self._total_lbl.grid(
            row=2,
            column=0,
            sticky="e",
            padx=10,
            pady=6
        )

        self._status_lbl = tk.Label(
            self,
            text="",
            fg="gray",
            bg="white",
            anchor="w"
        )

        self._status_lbl.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=16,
            pady=4
        )

        self.refresh()

    # ---------------------------------------------------------
    # Async loading helpers
    # ---------------------------------------------------------

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        if text is not None:
            self._status_lbl.config(text=text)

    def _run_worker(self, target, name: str):
        threading.Thread(
            target=target,
            daemon=True,
            name=name
        ).start()

    def _show_error(self, message: str):
        self._set_loading(False, message)

    # ---------------------------------------------------------
    # Refresh / filter
    # ---------------------------------------------------------

    def refresh(self):
        if self._loading:
            return

        self._selected_uid = None

        self._client_var.set("")
        self._item_var.set("")
        self._date_exact.set(date.today().isoformat())
        self._date_from.set("")
        self._date_to.set("")
        self._status_var.set("all")
        self._sort_col = None
        self._sort_asc = True
        for c, lbl in {"date": "Date", "client": "Client",
                       "status": "Status", "total": "Total ₱"}.items():
            self._tree.heading(c, text=lbl)

        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")

        self._set_loading(True, "Loading sales...")

        self._run_worker(
            self._refresh_worker,
            "sales-refresh"
        )

    def _refresh_worker(self):
        try:
            items = api.list_items()
            sales = api.list_all_sales(date_exact=date.today().isoformat())
            try:
                clients_list = api.list_clients()
                subs = api.list_subscriptions()
            except Exception:
                clients_list, subs = [], []

            self.after(
                0,
                lambda: self._refresh_complete(items, sales, None,
                                               clients_list, subs)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _refresh_complete(
        self,
        items: list[dict],
        sales: list[dict],
        preserve_uid: int | None = None,
        clients_list: list[dict] | None = None,
        subs: list[dict] | None = None,
    ):
        self._add_item_cb["values"] = [
            i["item_name"]
            for i in items
            if i.get("available_stock", 0) > 0
        ]

        self._all_sales = sales

        if clients_list is not None:
            self._all_clients = clients_list
        if subs is not None:
            plan_names = sorted({s["subscription_name"] for s in subs})
            self._plan_filter_cb["values"] = ["All Plans"] + plan_names
            self._plan_filter_var.set("All Plans")

        self._sale_map = {
            int(s["sales_uid"]): s
            for s in sales
            if s.get("sales_uid") is not None
        }

        self._apply_filter()

        if preserve_uid is not None and self._tree.exists(str(preserve_uid)):
            self._tree.selection_set(str(preserve_uid))
            self._tree.focus(str(preserve_uid))
            self._tree.see(str(preserve_uid))
            self._selected_uid = preserve_uid
            self._on_select()

        self._set_loading(False)

    def _filter(self):
        if self._loading:
            return

        params = {
            "client_name": self._client_var.get().strip() or None,
            "item_name": self._item_var.get().strip() or None,
            "date_exact": self._date_exact.get().strip() or None,
            "date_from": self._date_from.get().strip() or None,
            "date_to": self._date_to.get().strip() or None,
            "sale_status": (
                self._status_var.get()
                if self._status_var.get() != "all"
                else None
            ),
        }

        self._set_loading(True, "Filtering sales...")

        self._run_worker(
            lambda: self._filter_worker(params),
            "sales-filter"
        )

    def _filter_worker(self, params: dict):
        try:
            sales = api.list_all_sales(**params)

            self.after(
                0,
                lambda: self._filter_complete(sales)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _filter_complete(self, sales: list[dict]):
        self._selected_uid = None

        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")

        self._all_sales = sales

        self._sale_map = {
            int(s["sales_uid"]): s
            for s in sales
            if s.get("sales_uid") is not None
        }

        # Reset sort arrows so they match the new filter result
        self._sort_col = None
        self._sort_asc = True
        for c, lbl in {"date": "Date", "client": "Client",
                       "status": "Status", "total": "Total ₱"}.items():
            self._tree.heading(c, text=lbl)

        self._apply_filter()
        self._set_loading(False)

    def _sort(self, col: str):
        if col in ("chk", "uid"):
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        # Update heading indicators
        labels = {"date": "Date", "client": "Client",
                  "status": "Status", "total": "Total ₱"}
        for c, lbl in labels.items():
            arrow = (" ▲" if self._sort_asc else " ▼") if c == col else ""
            self._tree.heading(c, text=lbl + arrow)

        self._apply_filter()

    def _apply_filter(self):
        self._tree.delete(*self._tree.get_children())
        self._checked.clear()
        self._tree.heading("chk", text="☐")

        visible_sales = self._all_sales

        status_filter = self._status_var.get()
        if status_filter != "all":
            visible_sales = [
                s for s in visible_sales
                if s.get("sale_status") == status_filter
            ]

        plan_filter = self._plan_filter_var.get()
        if plan_filter and plan_filter != "All Plans":
            matching_names = {
                c["client_name"] for c in self._all_clients
                if plan_filter in (c.get("active_subscription_names") or [])
            }
            visible_sales = [
                s for s in visible_sales
                if s.get("client_name") in matching_names
            ]

        by_date: dict[str, list] = {}
        for s in visible_sales:
            by_date.setdefault(s.get("sale_date", ""), []).append(s)

        for d in sorted(by_date.keys(), reverse=True):
            diid = f"d_{d}"
            self._tree.insert("", "end", iid=diid,
                              values=("☐", "", d, "", "", ""),
                              tags=("date_group",))

            group = by_date[d]

            field_map = {"date": "sale_date", "client": "client_name",
                         "status": "sale_status", "total": "total_price"}
            if self._sort_col and self._sort_col in field_map:
                field = field_map[self._sort_col]
                group = sorted(group,
                               key=lambda s: s.get(field, "") or "",
                               reverse=not self._sort_asc)
            else:
                # Default: open first by uid desc, then closed by uid desc
                open_s   = sorted([s for s in group if s.get("sale_status") == "open"],
                                  key=lambda s: s.get("sales_uid", 0), reverse=True)
                closed_s = sorted([s for s in group if s.get("sale_status") != "open"],
                                  key=lambda s: s.get("sales_uid", 0), reverse=True)
                group = open_s + closed_s

            for s in group:
                uid = str(s["sales_uid"])
                tag = "open" if s.get("sale_status") == "open" else ""
                self._tree.insert(
                    diid, "end", iid=uid,
                    values=(
                        "☐",
                        s.get("sales_uid"),
                        s.get("sale_date", ""),
                        s.get("client_name", ""),
                        str(s.get("sale_status", "")).capitalize(),
                        f"{s.get('total_price', 0):.2f}",
                    ),
                    tags=(tag,),
                )

            self._tree.item(diid, open=True)

        self._status_lbl.config(text=f"{len(visible_sales)} sale(s)")

    # ---------------------------------------------------------
    # Checkbox logic
    # ---------------------------------------------------------

    def _on_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        col    = self._tree.identify_column(event.x)
        iid    = self._tree.identify_row(event.y)
        if not iid or region != "cell":
            return
        if col == "#1":
            if iid.startswith("d_"):
                self._toggle_date_group(iid)
            else:
                self._toggle_row(iid)

    def _toggle_row(self, iid: str):
        if iid in self._checked:
            self._checked.discard(iid)
            self._tree.set(iid, "chk", "☐")
        else:
            self._checked.add(iid)
            self._tree.set(iid, "chk", "☑")
        self._sync_header()

    def _toggle_date_group(self, diid: str):
        children = self._tree.get_children(diid)
        all_checked = all(c in self._checked for c in children)
        if all_checked:
            for c in children:
                self._checked.discard(c)
                self._tree.set(c, "chk", "☐")
            self._tree.set(diid, "chk", "☐")
        else:
            for c in children:
                self._checked.add(c)
                self._tree.set(c, "chk", "☑")
            self._tree.set(diid, "chk", "☑")
        self._sync_header()

    def _toggle_all(self):
        all_rows = [
            c for iid in self._tree.get_children("")
            for c in self._tree.get_children(iid)
        ]
        if all_rows and all(r in self._checked for r in all_rows):
            self._checked.clear()
            for iid in self._tree.get_children(""):
                self._tree.set(iid, "chk", "☐")
                for c in self._tree.get_children(iid):
                    self._tree.set(c, "chk", "☐")
            self._tree.heading("chk", text="☐")
        else:
            for iid in self._tree.get_children(""):
                self._tree.set(iid, "chk", "☑")
                for c in self._tree.get_children(iid):
                    self._checked.add(c)
                    self._tree.set(c, "chk", "☑")
            self._tree.heading("chk", text="☑")

    def _sync_header(self):
        all_rows = [
            c for iid in self._tree.get_children("")
            for c in self._tree.get_children(iid)
        ]
        if not all_rows:
            return
        if all(r in self._checked for r in all_rows):
            self._tree.heading("chk", text="☑")
        elif any(r in self._checked for r in all_rows):
            self._tree.heading("chk", text="—")
        else:
            self._tree.heading("chk", text="☐")

    def _selected_uids(self) -> list[int]:
        source = self._checked or {
            iid for iid in self._tree.selection()
            if not iid.startswith("d_")
        }
        uids = []
        for iid in source:
            try:
                uids.append(int(iid))
            except ValueError:
                pass
        return uids

    # ---------------------------------------------------------
    # Selection
    # ---------------------------------------------------------

    def _on_select(self, _=None):
        sel = self._tree.selection()

        if not sel:
            return

        # With multiselect, load detail for the most recently focused item
        try:
            uid = int(sel[-1])
        except ValueError:
            return

        self._selected_uid = uid

        sale = self._sale_map.get(uid)

        if not sale:
            return

        # Show header total immediately, then load line items lazily.
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(
            text=f"Total: ₱{sale.get('total_price', 0):.2f}"
        )
        self._status_lbl.config(text=f"Loading items for sale #{uid}...")

        self._detail_loading_uid = uid
        self._run_worker(
            lambda: self._load_sale_detail_worker(uid),
            "sales-load-detail"
        )

    def _load_sale_detail_worker(self, uid: int):
        try:
            sale = api.get_sale(uid)

            self.after(
                0,
                lambda sale=sale, uid=uid: self._sale_detail_loaded(uid, sale)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _sale_detail_loaded(self, uid: int, sale: dict):
        # Ignore stale detail responses if user clicked another sale.
        if self._selected_uid != uid:
            return

        self._detail_loading_uid = None
        self._sale_map[uid] = sale

        self._item_tree.delete(*self._item_tree.get_children())

        for si in sale.get("item_list", []):
            self._item_tree.insert(
                "",
                "end",
                values=(
                    si.get("item_name", ""),
                    si.get("item_qty", 0),
                    f"{si.get('item_total_price', 0):.2f}",
                )
            )

        self._total_lbl.config(
            text=f"Total: ₱{sale.get('total_price', 0):.2f}"
        )
        self._status_lbl.config(text=f"Sale #{uid} loaded.")

    # ---------------------------------------------------------
    # Open sale
    # ---------------------------------------------------------

    def _open_sale(self):
        if self._loading:
            return

        self._set_loading(True, "Loading active clients...")

        self._run_worker(
            self._open_sale_worker,
            "sales-open-load-clients"
        )

    def _open_sale_worker(self):
        try:
            active = api.list_active_clients()

            self.after(
                0,
                lambda: self._open_sale_dialog(active)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _open_sale_dialog(self, active: list[dict]):
        self._set_loading(False)

        if not active:
            messagebox.showwarning(
                "No active clients",
                "No clients are currently timed in."
            )
            return

        from fapp.views.sales_open_view import _PickClient

        dlg = _PickClient(
            self,
            [c["client_name"] for c in active]
        )

        if not dlg.result:
            return

        client_name = dlg.result

        self._set_loading(True, f"Opening sale for {client_name}...")

        self._run_worker(
            lambda: self._create_sale_worker(client_name),
            "sales-open-create"
        )

    def _create_sale_worker(self, client_name: str):
        try:
            sale = api.open_sale(client_name)

            self.after(
                0,
                lambda: self._sale_created(sale, client_name)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _sale_created(self, sale: dict, client_name: str):
        uid = sale.get("sales_uid")

        self._status_lbl.config(
            text=f"Opened sale #{uid} for {client_name}"
        )

        self._set_loading(False)

        self._refresh_preserve(uid)

    # ---------------------------------------------------------
    # Add / remove items
    # ---------------------------------------------------------

    def _add_item(self):
        if self._loading:
            return

        if self._selected_uid is None:
            messagebox.showwarning(
                "No sale",
                "Select an open sale first."
            )
            return

        if self._detail_loading_uid == self._selected_uid:
            messagebox.showinfo(
                "Please Wait",
                "Sale items are still loading. Please try again in a moment."
            )
            return

        sale = self._sale_map.get(self._selected_uid)

        if sale and sale.get("sale_status") != "open":
            messagebox.showwarning(
                "Closed Sale",
                "You can only add items to an open sale."
            )
            return

        item_name = self._add_item_var.get().strip()

        if not item_name:
            return

        try:
            qty = int(self._qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid",
                "Quantity must be a positive integer."
            )
            return

        uid = self._selected_uid

        self._set_loading(True, "Adding item...")

        self._run_worker(
            lambda: self._add_item_worker(uid, item_name, qty),
            "sales-add-item"
        )

    def _add_item_worker(self, uid: int, item_name: str, qty: int):
        try:
            api.add_item_to_sale(uid, item_name, qty)

            self.after(
                0,
                lambda: self._after_sale_mutation(uid, "Item added.")
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _remove_item(self):
        if self._loading:
            return

        if self._selected_uid is None:
            return

        if self._detail_loading_uid == self._selected_uid:
            messagebox.showinfo(
                "Please Wait",
                "Sale items are still loading. Please try again in a moment."
            )
            return

        sale = self._sale_map.get(self._selected_uid)

        if sale and sale.get("sale_status") != "open":
            messagebox.showwarning(
                "Closed Sale",
                "You can only remove items from an open sale."
            )
            return

        sel = self._item_tree.selection()

        if not sel:
            return

        item_name = self._item_tree.item(sel[0])["values"][0]
        uid = self._selected_uid

        self._set_loading(True, "Removing item...")

        self._run_worker(
            lambda: self._remove_item_worker(uid, item_name),
            "sales-remove-item"
        )

    def _remove_item_worker(self, uid: int, item_name: str):
        try:
            api.remove_item_from_sale(uid, item_name)

            self.after(
                0,
                lambda: self._after_sale_mutation(uid, "Item removed.")
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _after_sale_mutation(self, uid: int, status: str):
        self._status_lbl.config(text=status)
        self._set_loading(False)
        self._refresh_preserve(uid)

    # ---------------------------------------------------------
    # Close sale
    # ---------------------------------------------------------

    def _close_sale(self):
        if self._loading:
            return

        if self._selected_uid is None:
            messagebox.showwarning(
                "Select",
                "Select an open sale."
            )
            return

        sale = self._sale_map.get(self._selected_uid)

        if sale and sale.get("sale_status") != "open":
            messagebox.showinfo(
                "Already Closed",
                "This sale is already closed."
            )
            return

        uid = self._selected_uid

        if not messagebox.askyesno(
            "Confirm",
            f"Close sale #{uid}?"
        ):
            return

        self._set_loading(True, "Closing sale...")

        self._run_worker(
            lambda: self._close_sale_worker(uid),
            "sales-close-sale"
        )

    def _close_sale_worker(self, uid: int):
        try:
            api.close_sale(uid)

            self.after(
                0,
                lambda: self._after_close_sale(uid)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

    def _after_close_sale(self, uid: int):
        self._selected_uid = None
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")
        self._status_lbl.config(
            text=f"Sale #{uid} closed or deleted if empty."
        )
        self._set_loading(False)
        self._refresh_preserve(None)

    # ---------------------------------------------------------
    # Delete sale - admin only
    # ---------------------------------------------------------

    def _delete_sale(self):
        if self._loading:
            return

        if not api.is_admin:
            messagebox.showerror("Admin Only", "Only admins can delete sales logs.")
            return

        uids = self._selected_uids()
        if not uids:
            messagebox.showwarning("Select", "Select one or more sales to delete.")
            return

        noun = f"{len(uids)} sale(s)" if len(uids) > 1 else f"sale #{uids[0]}"
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete {noun}?\n\n"
            "This permanently removes the sale log(s).\n"
            "Reserved stock for open sales will be released.",
        ):
            return

        self._set_loading(True, f"Deleting {len(uids)} sale(s)...")
        self._run_worker(
            lambda: self._delete_sale_worker_multi(uids),
            "sales-delete-multi",
        )

    def _delete_sale_worker_multi(self, uids: list[int]):
        errors = []
        for uid in uids:
            try:
                api.delete_sale(uid)
            except Exception as e:
                errors.append(f"#{uid}: {e}")
        msg = f"Deleted {len(uids) - len(errors)} sale(s)."
        if errors:
            msg += "  Errors: " + "; ".join(errors)
        self.after(0, lambda: self._after_delete_multi(msg))

    def _after_delete_multi(self, msg: str):
        self._selected_uid = None
        self._item_tree.delete(*self._item_tree.get_children())
        self._total_lbl.config(text="Total: ₱0.00")
        self._status_lbl.config(text=msg)
        self._set_loading(False)
        self._refresh_preserve(None)

    # ---------------------------------------------------------
    # Refresh while preserving selection
    # ---------------------------------------------------------

    def _refresh_preserve(self, uid: int | None):
        if self._loading:
            return

        self._set_loading(True, "Refreshing sales...")

        self._run_worker(
            lambda: self._refresh_preserve_worker(uid),
            "sales-refresh-preserve"
        )

    def _refresh_preserve_worker(self, uid: int | None):
        try:
            # Items rarely change — use cache to avoid extra read on every mutation
            items = api.list_items()
            exact = self._date_exact.get().strip() or None
            dfrom = self._date_from.get().strip() or None
            dto   = self._date_to.get().strip() or None
            sales = api.list_all_sales(date_exact=exact,
                                       date_from=dfrom,
                                       date_to=dto)
            self.after(
                0,
                lambda: self._refresh_complete(items, sales, uid)
            )

        except APIError as e:
            msg = str(e)
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )

        except Exception as e:
            msg = f"Error: {e}"
            self.after(
                0,
                lambda msg=msg: self._show_error(msg)
            )