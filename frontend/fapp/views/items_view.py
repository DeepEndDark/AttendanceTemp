import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import set_window_icon

UNCATEGORIZED = "(Uncategorized)"


def group_items_by_category(items: list[dict],
                            only_available: bool = False) -> dict[str, list[dict]]:
    """
    Groups items by category into an ordered dict — real categories
    first (alphabetically), Uncategorized always last regardless of
    where "(Uncategorized)" would normally sort as a string. Each
    group's items are sorted by name.

    only_available=True excludes items with zero available stock —
    used wherever the list is for *selling* (nothing to add to a cart
    if there's none left), but not for the Item Catalogue management
    view itself, where an out-of-stock item still needs to be visible
    and editable.

    Shared by ItemsView, ItemPickerDialog, and the persistent item-
    picker box on both sales screens, so all four places group/sort
    identically rather than drifting out of sync with each other.
    """
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        if only_available and it.get("available_stock", 0) <= 0:
            continue
        by_cat.setdefault(it.get("category") or UNCATEGORIZED, []).append(it)

    ordered: dict[str, list[dict]] = {}
    for cat_name in sorted(by_cat.keys(), key=lambda c: (c == UNCATEGORIZED, c)):
        ordered[cat_name] = sorted(by_cat[cat_name], key=lambda it: it["item_name"])
    return ordered


class ItemsView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
        super().__init__(master, bg="white")
        self._all_items: list[dict] = []
        self._item_by_name: dict[str, dict] = {}
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Item Catalogue",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        if api.is_admin:
            tk.Button(bar, text="Delete", command=self._delete,
                      bg="#e04040", fg="white",
                      relief="flat", padx=10).pack(side="right", padx=4)
            tk.Button(bar, text="Rename", command=self._rename,
                      relief="flat", padx=10).pack(side="right", padx=4)
            tk.Button(bar, text="Move to Category", command=self._move_category,
                      relief="flat", padx=10).pack(side="right", padx=4)
            tk.Button(bar, text="Edit", command=self._edit,
                      relief="flat", padx=10).pack(side="right", padx=4)
            tk.Button(bar, text="Add Item", command=self._add,
                      bg="#185FA5", fg="white",
                      relief="flat", padx=10).pack(side="right", padx=4)

        filt = tk.Frame(self, bg="white")
        filt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))
        tk.Label(filt, text="Category:", bg="white").pack(side="left")
        self._cat_filter_var = tk.StringVar(value="All Categories")
        self._cat_filter_cb = ttk.Combobox(
            filt, textvariable=self._cat_filter_var,
            values=["All Categories"], state="readonly", width=24)
        self._cat_filter_cb.pack(side="left", padx=6)
        self._cat_filter_cb.bind("<<ComboboxSelected>>",
                                 lambda _e: self._apply_category_filter())

        # Category is expressed as a group row header (like the date
        # grouping used elsewhere in the app), not a column — so the
        # "category" column that used to sit here has been removed.
        cols = ("name", "price", "stock", "reserved", "available")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("name", "Item Name", 220), ("price", "Price ₱", 90),
            ("stock", "Total Stock", 100), ("reserved", "Reserved", 90),
            ("available", "Available", 90),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("low", foreground="#A32D2D")
        self._tree.tag_configure("cat_group", background="#FFF0E8")

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
        try:
            self._all_items = api.list_items()
            self._item_by_name = {it["item_name"]: it for it in self._all_items}
            categories = api.list_item_categories()
            current = self._cat_filter_var.get()
            values = ["All Categories"] + categories + [UNCATEGORIZED]
            self._cat_filter_cb["values"] = values
            if current not in values:
                self._cat_filter_var.set("All Categories")
            self._apply_category_filter()
        except APIError as e:
            self._status.config(text=str(e))

    def _apply_category_filter(self):
        cat = self._cat_filter_var.get()
        if cat == "All Categories":
            visible = self._all_items
        elif cat == UNCATEGORIZED:
            visible = [it for it in self._all_items if not it.get("category")]
        else:
            visible = [it for it in self._all_items
                      if it.get("category") == cat]

        self._tree.delete(*self._tree.get_children())

        by_cat = group_items_by_category(visible)
        for cat_name, group_items in by_cat.items():
            catiid = f"cat_{cat_name}"
            self._tree.insert("", "end", iid=catiid,
                              values=(f"{cat_name}  ({len(group_items)})",
                                      "", "", "", ""),
                              tags=("cat_group",))
            for it in group_items:
                avail = it.get("available_stock",
                               it["stock"] - it.get("reserved_stock", 0))
                tag = "low" if avail <= 2 else ""
                # Item name is unique, so it doubles as the row iid —
                # this makes looking an item back up (for edit/delete/
                # move) trivial without parsing displayed row values.
                self._tree.insert(catiid, "end", iid=it["item_name"],
                                  tags=(tag,), values=(
                                      it["item_name"], f"{it['price']:.2f}",
                                      it["stock"], it.get("reserved_stock", 0),
                                      avail))
            self._tree.item(catiid, open=True)

        self._status.config(
            text=f"{len(visible)} of {len(self._all_items)} item(s)")

    def _selected_name(self):
        sel = self._tree.selection()
        if not sel or sel[0].startswith("cat_"):
            messagebox.showwarning("Select", "Select an item first.")
            return None
        return sel[0]

    def _add(self):
        if not api.is_admin:
            return
        try:
            categories = api.list_item_categories()
        except APIError:
            categories = []
        dlg = _ItemDialog(self, "Add Item", categories=categories)
        if dlg.result:
            try:
                api.create_item(**dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _rename(self):
        if not api.is_admin:
            return
        name = self._selected_name()
        if not name:
            return
        from tkinter import simpledialog
        new_name = simpledialog.askstring(
            "Rename Item", f"Rename '{name}' to:", parent=self)
        if not new_name or new_name.strip() == name:
            return
        import threading
        new_name = new_name.strip()
        def _worker():
            try:
                api.rename_item(name, new_name)
                self.after(0, self.refresh)
            except APIError as e:
                msg = str(e)
                self.after(0, lambda msg=msg: messagebox.showerror(
                    "Error", msg))
        threading.Thread(target=_worker, daemon=True).start()

    def _edit(self):
        if not api.is_admin:
            return
        name = self._selected_name()
        if not name:
            return
        item = self._item_by_name.get(name, {})
        current_category = item.get("category") or None
        try:
            categories = api.list_item_categories()
        except APIError:
            categories = []
        dlg = _ItemDialog(self, "Edit Item",
                          data={"item_name": name,
                                "price": item.get("price"),
                                "stock": item.get("stock"),
                                "category": current_category},
                          categories=categories)
        if dlg.result:
            try:
                api.update_item(name,
                                price=dlg.result.get("price"),
                                stock=dlg.result.get("stock"))
                new_category = dlg.result.get("category")
                if (new_category or None) != current_category:
                    api.set_item_category(name, new_category)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _move_category(self):
        if not api.is_admin:
            return
        """
        Quick action for reassigning an existing item's category without
        opening the full edit dialog — covers "add existing items to a
        category" and "switch between categories" directly.
        """
        name = self._selected_name()
        if not name:
            return
        current_category = self._item_by_name.get(name, {}).get("category")
        try:
            categories = api.list_item_categories()
        except APIError:
            categories = []
        dlg = _CategoryPickerDialog(self, name, current_category, categories)
        if dlg.result is not None:
            new_category = dlg.result or None
            try:
                api.set_item_category(name, new_category)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        if not api.is_admin:
            return
        name = self._selected_name()
        if not name:
            return
        if messagebox.askyesno("Confirm", f"Delete '{name}'?"):
            try:
                api.delete_item(name)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _ItemDialog(tk.Toplevel):
    def __init__(self, parent, title, data=None, categories=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None
        categories = categories or []

        for i, lbl in enumerate(["Item Name:", "Price:", "Stock:",
                                  "Category:"]):
            tk.Label(self, text=lbl).grid(row=i, column=0,
                                          sticky="w", padx=14, pady=6)
        self._name = tk.Entry(self, width=26)
        self._name.grid(row=0, column=1, padx=14, pady=6)
        self._price = tk.Entry(self, width=26)
        self._price.grid(row=1, column=1, padx=14, pady=6)
        self._stock = tk.Entry(self, width=26)
        self._stock.grid(row=2, column=1, padx=14, pady=6)

        # Editable combobox — pick an existing category, type a new one,
        # or leave blank. Items don't have to belong to a category at all.
        self._category_var = tk.StringVar()
        self._category = ttk.Combobox(
            self, textvariable=self._category_var,
            values=categories, width=24)
        self._category.grid(row=3, column=1, padx=14, pady=6)

        if data:
            self._name.insert(0, data.get("item_name", ""))
            self._name.config(state="disabled")
            self._price.insert(0, str(data.get("price", "")))
            self._stock.insert(0, str(data.get("stock", "")))
            if data.get("category"):
                self._category_var.set(data["category"])

        tk.Label(self, text="(leave blank for no category)",
                 fg="gray", font=("", 8)).grid(
            row=4, column=1, sticky="w", padx=14)

        btn = tk.Frame(self)
        btn.grid(row=5, column=0, columnspan=2, pady=12)
        tk.Button(btn, text="Save", command=self._save,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _save(self):
        try:
            price = float(self._price.get())
            stock = int(self._stock.get())
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Price must be a number; stock an integer.")
            return
        name = self._name.get().strip()
        if not name:
            messagebox.showerror("Required", "Item name is required.")
            return
        category = self._category_var.get().strip() or None
        self.result = {"name": name, "price": price, "stock": stock,
                       "category": category}
        self.destroy()


class _CategoryPickerDialog(tk.Toplevel):
    """
    Lightweight dialog for the "Move to Category" quick action — moving
    an existing item into a category (new or existing), or clearing it
    back to uncategorized, without opening the full edit form.
    """
    def __init__(self, parent, item_name: str,
                current_category: str | None, categories: list[str]):
        super().__init__(parent)
        self.title("Move to Category")
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None

        tk.Label(self, text=f"Item: {item_name}",
                 font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 4))
        tk.Label(self, text="Category:").grid(
            row=1, column=0, sticky="w", padx=14, pady=6)

        self._category_var = tk.StringVar(value=current_category or "")
        self._category = ttk.Combobox(
            self, textvariable=self._category_var,
            values=categories, width=24)
        self._category.grid(row=1, column=1, padx=14, pady=6)

        tk.Label(self, text="(leave blank to remove from any category)",
                 fg="gray", font=("", 8)).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=14)

        btn = tk.Frame(self)
        btn.grid(row=3, column=0, columnspan=2, pady=12)
        tk.Button(btn, text="Save", command=self._save,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _save(self):
        # "" is a valid, meaningful result here (clear the category) —
        # distinct from None, which _move_category treats as "cancelled".
        self.result = self._category_var.get().strip()
        self.destroy()


class ItemPickerDialog(tk.Toplevel):
    """
    Reusable category-grouped item picker for the sales screens — items
    are organized under category header rows (matching the Item
    Catalogue's own grouping, and the date-header pattern already used
    elsewhere in the app for logs/sales) instead of a flat alphabetical
    dropdown, so a large catalogue stays browsable while ringing up a
    sale. Only items with available stock are shown, since those are the
    only ones a sale can actually be added for.

    Usage: dlg = ItemPickerDialog(parent, items); if dlg.result: ... —
    dlg.result is the chosen item_name, or None if cancelled.
    """
    def __init__(self, parent, items: list[dict], title="Pick an Item"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result: str | None = None

        tk.Label(self, text="Double-click an item, or select and click Choose.",
                 fg="gray", font=("", 8)).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        cols = ("name", "price", "available")
        tree = ttk.Treeview(self, columns=cols, show="headings",
                            selectmode="browse", height=14)
        tree.heading("name", text="Item")
        tree.column("name", width=220, anchor="w")
        tree.heading("price", text="Price ₱")
        tree.column("price", width=90, anchor="center")
        tree.heading("available", text="Available")
        tree.column("available", width=90, anchor="center")
        tree.tag_configure("cat_group", background="#FFF0E8")
        tree.grid(row=1, column=0, columnspan=2, padx=12, pady=4,
                 sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._tree = tree

        by_cat = group_items_by_category(items, only_available=True)
        for cat_name, group_items in by_cat.items():
            catiid = f"cat_{cat_name}"
            tree.insert("", "end", iid=catiid,
                       values=(f"{cat_name}  ({len(group_items)})", "", ""),
                       tags=("cat_group",))
            for it in group_items:
                tree.insert(catiid, "end", iid=it["item_name"], values=(
                    it["item_name"], f"{it['price']:.2f}",
                    it.get("available_stock", 0)))
            tree.item(catiid, open=True)

        tree.bind("<Double-Button-1>", lambda _e: self._choose())

        btn = tk.Frame(self)
        btn.grid(row=2, column=0, columnspan=2, pady=10)
        tk.Button(btn, text="Choose", command=self._choose,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _choose(self):
        sel = self._tree.selection()
        if not sel or sel[0].startswith("cat_"):
            return
        self.result = sel[0]
        self.destroy()