import tkinter as tk
from tkinter import ttk, messagebox

from app.api_client import api, APIError


class ClientsView(tk.Frame):
    """Admin — full client list, edit/delete admin only."""

    def __init__(self, master):
        super().__init__(master)
        self.configure(bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Client List", font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh, relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white", relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit, relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Enroll New", command=self._enroll,
                  bg="#185FA5", fg="white", relief="flat", padx=10).pack(side="right", padx=4)

        cols = ("name", "duration", "status", "budget", "enrolled")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, txt, w in [
            ("name", "Client Name", 160), ("duration", "Duration", 110),
            ("status", "Status", 70), ("budget", "Budget", 90), ("enrolled", "Last Enrolled", 130),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")

        self._tree.tag_configure("in", foreground="#0F6E56")
        sb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=1, column=0, sticky="nsew", padx=(16, 0), pady=4)
        sb.grid(row=1, column=1, sticky="ns", pady=4, padx=(0, 8))

        self._status = tk.Label(self, text="", fg="gray", bg="white", anchor="w")
        self._status.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        self.refresh()

    def refresh(self):
        try:
            clients = api.list_clients()
            self._tree.delete(*self._tree.get_children())
            for c in clients:
                enrolled = (c.get("last_enrolled_at") or "")[:10]
                tag = "in" if c["client_status"] else ""
                self._tree.insert("", "end", values=(
                    c["client_name"], c["client_duration"],
                    "In" if c["client_status"] else "Out",
                    f"{c['client_budget']:.2f}", enrolled,
                ), tags=(tag,))
            self._status.config(text=f"{len(clients)} client(s)")
        except APIError as e:
            self._status.config(text=str(e))

    def _selected_name(self) -> str | None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Please select a client first.")
            return None
        return self._tree.item(sel[0])["values"][0]

    def _enroll(self):
        dlg = _EnrollDialog(self)
        if dlg.result:
            try:
                api.create_client(**dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _edit(self):
        name = self._selected_name()
        if not name:
            return
        try:
            client = api.get_client(name)
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return
        dlg = _ClientEditDialog(self, client)
        if dlg.result:
            try:
                api.update_client(name, **dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        if messagebox.askyesno("Confirm", f"Delete client '{name}'?"):
            try:
                api.delete_client(name)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _ClientEditDialog(tk.Toplevel):
    def __init__(self, parent, data: dict):
        super().__init__(parent)
        self.title("Edit Client")
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        tk.Label(self, text=f"Editing: {data['client_name']}", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, padx=14, pady=10)

        tk.Label(self, text="Duration:").grid(row=1, column=0, sticky="w", padx=14, pady=6)
        self._dur = tk.Entry(self, width=26)
        self._dur.insert(0, data.get("client_duration", ""))
        self._dur.grid(row=1, column=1, padx=14, pady=6)

        tk.Label(self, text="Budget:").grid(row=2, column=0, sticky="w", padx=14)
        self._budget = tk.Entry(self, width=26)
        self._budget.insert(0, str(data.get("client_budget", 0.0)))
        self._budget.grid(row=2, column=1, padx=14, pady=6)

        tk.Button(self, text="Save", command=self._save, width=12).grid(
            row=3, column=0, pady=12, padx=14)
        tk.Button(self, text="Cancel", command=self.destroy, width=10).grid(
            row=3, column=1, pady=12, padx=14)
        self.wait_window()

    def _save(self):
        try:
            budget = float(self._budget.get())
        except ValueError:
            messagebox.showerror("Invalid", "Budget must be a number.")
            return
        self.result = {"client_duration": self._dur.get().strip(), "client_budget": budget}
        self.destroy()


class _EnrollDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Enroll New Client")
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        tk.Label(self, text="Client name:").grid(row=0, column=0, sticky="w", padx=14, pady=6)
        self._name = tk.Entry(self, width=26)
        self._name.grid(row=0, column=1, padx=14, pady=6)

        tk.Label(self, text="Duration:").grid(row=1, column=0, sticky="w", padx=14)
        self._dur = tk.Entry(self, width=26)
        self._dur.grid(row=1, column=1, padx=14, pady=6)

        tk.Label(self, text="Budget:").grid(row=2, column=0, sticky="w", padx=14)
        self._budget = tk.Entry(self, width=26)
        self._budget.insert(0, "0.0")
        self._budget.grid(row=2, column=1, padx=14, pady=6)

        tk.Button(self, text="Enroll", command=self._save, width=12).grid(
            row=3, column=0, pady=12, padx=14)
        tk.Button(self, text="Cancel", command=self.destroy, width=10).grid(
            row=3, column=1, pady=12, padx=14)
        self.wait_window()

    def _save(self):
        name = self._name.get().strip()
        dur = self._dur.get().strip()
        if not name or not dur:
            messagebox.showerror("Required", "Name and duration are required.")
            return
        try:
            budget = float(self._budget.get() or "0")
        except ValueError:
            messagebox.showerror("Invalid", "Budget must be a number.")
            return
        self.result = {"name": name, "duration": dur, "budget": budget}
        self.destroy()