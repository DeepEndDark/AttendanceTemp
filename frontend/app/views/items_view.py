import tkinter as tk
from tkinter import ttk, messagebox

from app.api_client import api, APIError


class ItemsView(tk.Frame):
    """Admin — full item catalogue with add/edit/delete and stock visibility."""

    def __init__(self, master):
        super().__init__(master)
        self.configure(bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Item Catalogue", font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh, relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white", relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit, relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Add Item", command=self._add,
                  bg="#185FA5", fg="white", relief="flat", padx=10).pack(side="right", padx=4)

        cols = ("name", "price", "stock", "reserved", "available")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, txt, w in [
            ("name", "Item Name", 200),
            ("price", "Price", 90),
            ("stock", "Total Stock", 100),
            ("reserved", "Reserved", 90),
            ("available", "Available", 90),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")

        sb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=1, column=0, sticky="nsew", padx=(16, 0), pady=4)
        sb.grid(row=1, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._status = tk.Label(self, text="", fg="gray", bg="white", anchor="w")
        self._status.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        self.refresh()

    def refresh(self):
        try:
            items = api.list_items()
            self._tree.delete(*self._tree.get_children())
            for it in items:
                avail = it.get("available_stock", it["stock"] - it.get("reserved_stock", 0))
                tag = "low" if avail <= 2 else ""
                self._tree.insert("", "end", values=(
                    it["item_name"],
                    f"{it['price']:.2f}",
                    it["stock"],
                    it.get("reserved_stock", 0),
                    avail,
                ), tags=(tag,))
            self._tree.tag_configure("low", foreground="#A32D2D")
            self._status.config(text=f"{len(items)} item(s)")
        except APIError as e:
            self._status.config(text=str(e))

    def _selected_name(self) -> str | None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Please select an item first.")
            return None
        return self._tree.item(sel[0])["values"][0]

    def _add(self):
        dlg = _ItemDialog(self, "Add Item")
        if dlg.result:
            try:
                api.create_item(**dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _edit(self):
        name = self._selected_name()
        if not name:
            return
        row = self._tree.item(self._tree.selection()[0])["values"]
        dlg = _ItemDialog(self, "Edit Item",
                          data={"item_name": name, "price": row[1], "stock": row[2]})
        if dlg.result:
            try:
                api.update_item(name, price=dlg.result.get("price"),
                                stock=dlg.result.get("stock"))
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        if messagebox.askyesno("Confirm", f"Delete item '{name}'?"):
            try:
                api.delete_item(name)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _ItemDialog(tk.Toplevel):
    def __init__(self, parent, title: str, data: dict | None = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        is_edit = data is not None

        fields = [("Item Name:", "_name"), ("Price:", "_price"), ("Stock:", "_stock")]
        self._entries = {}
        for i, (lbl, key) in enumerate(fields):
            tk.Label(self, text=lbl).grid(row=i, column=0, sticky="w", padx=14, pady=6)
            e = tk.Entry(self, width=26)
            e.grid(row=i, column=1, padx=14, pady=6)
            self._entries[key] = e

        if data:
            self._entries["_name"].insert(0, data.get("item_name", ""))
            self._entries["_name"].config(state="disabled")
            self._entries["_price"].insert(0, str(data.get("price", "")))
            self._entries["_stock"].insert(0, str(data.get("stock", "")))

        tk.Button(self, text="Save", command=self._save, width=12).grid(
            row=3, column=0, pady=12, padx=14)
        tk.Button(self, text="Cancel", command=self.destroy, width=10).grid(
            row=3, column=1, pady=12, padx=14)
        self.wait_window()

    def _save(self):
        try:
            price = float(self._entries["_price"].get())
            stock = int(self._entries["_stock"].get())
        except ValueError:
            messagebox.showerror("Invalid", "Price must be a number; stock must be an integer.")
            return
        name = self._entries["_name"].get().strip()
        if not name:
            messagebox.showerror("Required", "Item name is required.")
            return
        self.result = {"name": name, "price": price, "stock": stock}
        self.destroy()
