import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class LockerView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Locker Management",
                 font=("", 14, "bold"),
                 bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Assign Locker",
                  command=self._assign_locker,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Availability summary
        summary = tk.Frame(self, bg="#E6F1FB",
                           relief="groove", bd=1)
        summary.grid(row=1, column=0, sticky="ew",
                     padx=16, pady=(0, 8))
        self._avail_lbl = tk.Label(
            summary, text="", bg="#E6F1FB",
            font=("", 10), pady=8)
        self._avail_lbl.pack()

        # Active rentals table
        cols = ("client", "locker", "days_left")
        self._tree = ttk.Treeview(
            self, columns=cols,
            show="headings", selectmode="browse")
        for col, txt, w in [
            ("client", "Client",         200),
            ("locker", "Locker #",        90),
            ("days_left", "Days Remaining", 120),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")
        self._tree.tag_configure("low", foreground="#BA7517")

        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=2, column=0, sticky="nsew",
                        padx=(16, 0), pady=4)
        sb.grid(row=2, column=1, sticky="ns",
                pady=4, padx=(0, 8))

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=3, column=0, sticky="ew",
                          padx=16, pady=6)
        self.refresh()

    def refresh(self):
        try:
            avail = api.get_locker_availability()
            self._avail_lbl.config(
                text=(f"Total: {avail['total']}   |   "
                      f"Rented: {avail['rented']}   |   "
                      f"Available: {avail['available']}   |   "
                      f"Price: ₱{avail['price']:.2f} / "
                      f"{avail['rental_days']} days"))

            self._tree.delete(*self._tree.get_children())
            count = 0
            for c in api.list_clients():
                if c.get("locker_number"):
                    days = c["client_locker_days_remaining"]
                    tag  = "low" if days <= 3 else ""
                    self._tree.insert(
                        "", "end", tags=(tag,),
                        values=(c["client_name"],
                                c["locker_number"],
                                days))
                    count += 1
            self._status.config(
                text=f"{count} active locker rental(s)")
        except APIError as e:
            self._status.config(text=str(e))

    def _assign_locker(self):
        try:
            avail       = api.get_locker_availability()
            all_clients = [c["client_name"]
                           for c in api.list_clients()]
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return

        dlg = _AssignDialog(self,
                            total=avail["total"],
                            all_clients=all_clients)
        if dlg.result:
            try:
                result = api.assign_locker(
                    dlg.result["client_name"],
                    dlg.result["locker_number"])
                messagebox.showinfo(
                    "Locker Assigned",
                    f"Locker #{result['locker_number']} assigned to "
                    f"{result['client_name']}\n"
                    f"Days added: {result['days_added']}  |  "
                    f"Expires: {result['expires_at']}")
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))


class _AssignDialog(tk.Toplevel):
    def __init__(self, parent, total: int, all_clients: list[str]):
        super().__init__(parent)
        self.title("Assign Locker")
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        tk.Label(self, text="Client:").grid(
            row=0, column=0, sticky="w", padx=14, pady=8)
        self._client_var = tk.StringVar()
        cb = ttk.Combobox(
            self, textvariable=self._client_var,
            values=all_clients, state="readonly", width=26)
        cb.grid(row=0, column=1, padx=14, pady=8)
        if all_clients:
            cb.current(0)

        tk.Label(self,
                 text=f"Locker # (1–{total}):").grid(
            row=1, column=0, sticky="w", padx=14)
        self._num_var = tk.StringVar()
        tk.Entry(self, textvariable=self._num_var,
                 width=10).grid(row=1, column=1,
                                sticky="w", padx=14, pady=8)

        btn = tk.Frame(self)
        btn.grid(row=2, column=0, columnspan=2, pady=12)
        tk.Button(btn, text="Assign",
                  command=self._save,
                  bg="#185FA5", fg="white",
                  relief="flat", width=12).pack(
            side="left", padx=6)
        tk.Button(btn, text="Cancel",
                  command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _save(self):
        client = self._client_var.get()
        if not client:
            messagebox.showerror("Required",
                                 "Please select a client.")
            return
        try:
            num = int(self._num_var.get())
            if num < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Locker number must be a "
                                 "positive integer.")
            return
        self.result = {
            "client_name":   client,
            "locker_number": num,
        }
        self.destroy()
