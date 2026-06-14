import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class AccountsView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Account Management",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Add Account", command=self._add,
                  bg="#E8500A", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        cols = ("name", "role")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        self._tree.heading("name", text="Account Name")
        self._tree.heading("role", text="Role")
        self._tree.column("name", width=220, anchor="center")
        self._tree.column("role", width=120, anchor="center")
        self._tree.tag_configure("admin", foreground="#E8500A")

        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=1, column=0, sticky="nsew",
                        padx=(16, 0), pady=4)
        sb.grid(row=1, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=2, column=0, sticky="ew",
                          padx=16, pady=6)
        self.refresh()

    def refresh(self):
        try:
            accounts = api.list_accounts()
            self._tree.delete(*self._tree.get_children())
            for a in accounts:
                tag = "admin" if a["account_type"] == "admin" else ""
                self._tree.insert("", "end", tags=(tag,),
                                  values=(a["account_name"],
                                          a["account_type"]))
            self._status.config(text=f"{len(accounts)} account(s)")
        except APIError as e:
            self._status.config(text=str(e))

    def _selected_name(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Select",
                                   "Please select an account first.")
            return None
        return self._tree.item(sel[0])["values"][0]

    def _add(self):
        dlg = _AccountDialog(self, "Add Account")
        if dlg.result:
            try:
                api.create_account(**dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _edit(self):
        name = self._selected_name()
        if not name:
            return
        dlg = _AccountDialog(self, "Edit Account", edit_mode=True)
        if dlg.result:
            try:
                api.update_account(name, **dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        if messagebox.askyesno("Confirm",
                               f"Delete account '{name}'?"):
            try:
                api.delete_account(name)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _AccountDialog(tk.Toplevel):
    def __init__(self, parent, title, edit_mode=False):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        row = 0

        if not edit_mode:
            tk.Label(self, text="Account Name:").grid(
                row=row, column=0, sticky="w", padx=14, pady=6)
            self._name = tk.Entry(self, width=26)
            self._name.grid(row=row, column=1, padx=14, pady=6)
            row += 1
        else:
            self._name = None

        tk.Label(self, text="Role:").grid(
            row=row, column=0, sticky="w", padx=14)
        self._role = tk.StringVar(value="sales")
        ttk.Combobox(self, textvariable=self._role,
                     values=["admin", "sales"],
                     state="readonly", width=23).grid(
            row=row, column=1, padx=14, pady=6)
        row += 1

        tk.Label(self, text="Password:").grid(
            row=row, column=0, sticky="w", padx=14)
        self._pw = tk.Entry(self, show="*", width=26)
        self._pw.grid(row=row, column=1, padx=14, pady=6)
        row += 1

        if edit_mode:
            tk.Label(self, text="(leave blank to keep current)",
                     fg="gray", font=("", 8)).grid(
                row=row, column=1, sticky="w", padx=14)
            row += 1

        btn = tk.Frame(self)
        btn.grid(row=row, column=0, columnspan=2, pady=12)
        tk.Button(btn, text="Save", command=self._save,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _save(self):
        role = self._role.get()
        pw = self._pw.get().strip()
        if self._name is not None:
            name = self._name.get().strip()
            if not name or not pw:
                messagebox.showerror("Required",
                                     "Name and password are required.")
                return
            self.result = {"name": name, "role": role, "password": pw}
        else:
            self.result = {"role": role}
            if pw:
                self.result["password"] = pw
        self.destroy()