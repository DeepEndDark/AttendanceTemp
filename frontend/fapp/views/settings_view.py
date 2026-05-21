import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


class SettingsView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)

        tk.Label(self, text="System Settings",
                 font=("", 14, "bold"),
                 bg="white").grid(row=0, column=0,
                                  sticky="w", padx=20, pady=(16, 12))

        # Locker settings
        locker_frame = tk.LabelFrame(self, text="Locker Settings",
                                     bg="white", padx=16, pady=12)
        locker_frame.grid(row=1, column=0, sticky="ew",
                          padx=20, pady=(0, 12))
        locker_frame.columnconfigure(1, weight=1)

        fields = [
            ("Total Lockers:", "_total", "total_lockers"),
            ("Rental Price (₱):", "_price", "locker_price"),
            ("Rental Duration (days):", "_days", "locker_rental_days"),
        ]
        self._locker_entries = {}
        for i, (lbl, key, _) in enumerate(fields):
            tk.Label(locker_frame, text=lbl,
                     bg="white").grid(row=i, column=0,
                                      sticky="w", pady=6)
            e = tk.Entry(locker_frame, width=20)
            e.grid(row=i, column=1, sticky="w",
                   padx=(12, 0), pady=6)
            self._locker_entries[key] = e

        tk.Button(locker_frame, text="Save Locker Settings",
                  command=self._save_locker,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=12,
                  pady=6).grid(row=len(fields), column=0,
                               columnspan=2, sticky="w",
                               pady=(12, 0))

        # Trainer deduction method
        trainer_frame = tk.LabelFrame(self, text="Trainer Deduction",
                                      bg="white", padx=16, pady=12)
        trainer_frame.grid(row=2, column=0, sticky="ew",
                           padx=20, pady=(0, 12))

        tk.Label(trainer_frame,
                 text="How trainer days are deducted:",
                 bg="white").grid(row=0, column=0,
                                  sticky="w", pady=4)

        self._trainer_method = tk.StringVar(value="fifo")
        for val, txt in [
            ("fifo", "FIFO — automatically from oldest active subscription"),
            ("manual", "Manual — staff presses Deduct button explicitly"),
        ]:
            tk.Radiobutton(trainer_frame, text=txt,
                           variable=self._trainer_method,
                           value=val, bg="white").grid(
                sticky="w", padx=8, pady=2)

        tk.Button(trainer_frame, text="Save Trainer Setting",
                  command=self._save_trainer,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=12,
                  pady=6).grid(sticky="w", pady=(10, 0))

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=3, column=0, sticky="ew",
                          padx=20, pady=8)

        self._load()

    def _load(self):
        try:
            s = api.get_locker_settings()
            self._locker_entries["_total"].delete(0, "end")
            self._locker_entries["_total"].insert(
                0, str(s.get("total_lockers", 0)))
            self._locker_entries["_price"].delete(0, "end")
            self._locker_entries["_price"].insert(
                0, str(s.get("locker_price", 0.0)))
            self._locker_entries["_days"].delete(0, "end")
            self._locker_entries["_days"].insert(
                0, str(s.get("locker_rental_days", 30)))
            self._trainer_method.set(
                s.get("trainer_deduction_method", "fifo"))
        except APIError as e:
            self._status.config(text=str(e))

    def _save_locker(self):
        try:
            total = int(self._locker_entries["_total"].get())
            price = float(self._locker_entries["_price"].get())
            days = int(self._locker_entries["_days"].get())
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Total and days must be integers; "
                                 "price must be a number.")
            return
        try:
            api.update_locker_settings({
                "total_lockers": total,
                "locker_price": price,
                "locker_rental_days": days,
            })
            self._status.config(text="Locker settings saved.",
                                fg="#0F6E56")
        except APIError as e:
            self._status.config(text=str(e), fg="red")

    def _save_trainer(self):
        try:
            api.update_locker_settings({
                "trainer_deduction_method": self._trainer_method.get()
            })
            self._status.config(text="Trainer setting saved.",
                                fg="#0F6E56")
        except APIError as e:
            self._status.config(text=str(e), fg="red")

    def refresh(self):
        self._load()
