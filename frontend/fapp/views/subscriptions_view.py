import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from fapp.api_client import api, APIError
from fapp.views.admin_attendance_view import set_window_icon


class SubscriptionsView(tk.Frame):
    def __init__(self, master, display_queue=None, **kwargs):
        super().__init__(master, bg="white")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Subscription Plans",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Delete", command=self._delete,
                  bg="#e04040", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Rename", command=self._rename,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Edit", command=self._edit,
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Add Plan", command=self._add,
                  bg="#E8500A", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        cols = ("name", "days", "price", "trainer",
                "trainer_days", "hardcap")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="browse")
        for col, txt, w in [
            ("name", "Plan Name", 180), ("days", "Duration (days)", 110),
            ("price", "Price ₱", 90), ("trainer", "Trainer", 70),
            ("trainer_days", "Trainer Days", 100),
            ("hardcap", "Hardcap (days)", 110),
        ]:
            self._tree.heading(col, text=txt)
            self._tree.column(col, width=w, anchor="center")

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
            subs = api.list_subscriptions()
            self._tree.delete(*self._tree.get_children())
            for s in subs:
                self._tree.insert("", "end", values=(
                    s["subscription_name"], s["duration_days"],
                    f"{s['price']:.2f}",
                    "Yes" if s["has_trainer"] else "No",
                    s["trainer_duration_days"] if s["has_trainer"] else "—",
                    s["trainer_hardcap_days"] if s["has_trainer"] else "—",
                ))
            self._status.config(text=f"{len(subs)} plan(s)")
        except APIError as e:
            self._status.config(text=str(e))

    def _selected_name(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select a plan first.")
            return None
        return self._tree.item(sel[0])["values"][0]

    def _add(self):
        dlg = _SubDialog(self, "Add Plan")
        if dlg.result:
            try:
                api.create_subscription(dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _rename(self):
        name = self._selected_name()
        if not name:
            return
        new_name = simpledialog.askstring(
            "Rename Plan", f"Rename '{name}' to:", parent=self)
        if not new_name or new_name.strip() == name:
            return
        import threading
        new_name = new_name.strip()
        def _worker():
            try:
                api.rename_subscription(name, new_name)
                self.after(0, self.refresh)
            except APIError as e:
                msg = str(e)
                self.after(0, lambda msg=msg: messagebox.showerror(
                    "Error", msg))
        threading.Thread(target=_worker, daemon=True).start()

    def _edit(self):
        name = self._selected_name()
        if not name:
            return
        row = self._tree.item(self._tree.selection()[0])["values"]
        existing = {
            "subscription_name": row[0],
            "duration_days": row[1],
            "price": row[2],
            "has_trainer": row[3] == "Yes",
            "trainer_duration_days": row[4] if row[4] != "—" else 0,
            "trainer_hardcap_days": row[5] if row[5] != "—" else 0,
        }
        dlg = _SubDialog(self, "Edit Plan", data=existing)
        if dlg.result:
            try:
                api.update_subscription(name, dlg.result)
                self.refresh()
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        if not messagebox.askyesno("Confirm", f"Delete plan '{name}'?"):
            return
        try:
            api.delete_subscription(name)
            self.refresh()
        except APIError as e:
            if e.status_code == 409:
                # Backend refused because clients still hold this plan —
                # surface its exact count and let the admin force it.
                if messagebox.askyesno("Plan in use",
                                       f"{e}\n\nDelete anyway?"):
                    try:
                        api.delete_subscription(name, force=True)
                        self.refresh()
                    except APIError as e2:
                        messagebox.showerror("Error", str(e2))
            else:
                messagebox.showerror("Error", str(e))


class _SubDialog(tk.Toplevel):
    def __init__(self, parent, title, data=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result = None
        is_edit = data is not None

        row = 0
        tk.Label(self, text="Plan Name:").grid(
            row=row, column=0, sticky="w", padx=14, pady=6)
        self._name = tk.Entry(self, width=26)
        self._name.grid(row=row, column=1, padx=14, pady=6)
        if is_edit:
            self._name.insert(0, data["subscription_name"])
            self._name.config(state="disabled")
        row += 1

        for lbl, attr in [("Duration (days):", "_days"),
                           ("Price:", "_price")]:
            tk.Label(self, text=lbl).grid(row=row, column=0,
                                          sticky="w", padx=14, pady=6)
            e = tk.Entry(self, width=26)
            e.grid(row=row, column=1, padx=14, pady=6)
            setattr(self, attr, e)
            if is_edit:
                e.insert(0, str(data.get(
                    "duration_days" if attr == "_days" else "price", "")))
            row += 1

        tk.Label(self, text="Has Trainer:").grid(
            row=row, column=0, sticky="w", padx=14, pady=6)
        self._trainer_var = tk.BooleanVar(
            value=data["has_trainer"] if is_edit else False)
        tk.Checkbutton(self, variable=self._trainer_var,
                       command=self._toggle_trainer).grid(
            row=row, column=1, sticky="w", padx=14)
        row += 1

        self._trainer_frame = tk.Frame(self)
        self._trainer_frame.grid(row=row, column=0, columnspan=2)
        tk.Label(self._trainer_frame,
                 text="Trainer Days:").grid(row=0, column=0,
                                            sticky="w", padx=14, pady=4)
        self._tdays = tk.Entry(self._trainer_frame, width=20)
        self._tdays.grid(row=0, column=1, padx=14, pady=4)
        tk.Label(self._trainer_frame,
                 text="Hardcap (days):").grid(row=1, column=0,
                                              sticky="w", padx=14, pady=4)
        self._hardcap = tk.Entry(self._trainer_frame, width=20)
        self._hardcap.grid(row=1, column=1, padx=14, pady=4)
        if is_edit and data["has_trainer"]:
            self._tdays.insert(0, str(data.get("trainer_duration_days", 0)))
            self._hardcap.insert(0, str(data.get("trainer_hardcap_days", 0)))
        row += 1

        self._toggle_trainer()

        btn = tk.Frame(self)
        btn.grid(row=row, column=0, columnspan=2, pady=12)
        tk.Button(btn, text="Save", command=self._save,
                  width=12).pack(side="left", padx=6)
        tk.Button(btn, text="Cancel", command=self.destroy,
                  width=10).pack(side="left", padx=6)
        self.wait_window()

    def _toggle_trainer(self):
        state = "normal" if self._trainer_var.get() else "disabled"
        for w in self._trainer_frame.winfo_children():
            try:
                w.config(state=state)
            except tk.TclError:
                pass

    def _save(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showerror("Required", "Plan name is required.")
            return
        try:
            days = int(self._days.get())
            price = float(self._price.get())
        except ValueError:
            messagebox.showerror("Invalid",
                                 "Duration must be integer, price a number.")
            return
        has_trainer = self._trainer_var.get()
        t_days = 0
        hardcap = 0
        if has_trainer:
            try:
                t_days = int(self._tdays.get())
                hardcap = int(self._hardcap.get())
            except ValueError:
                messagebox.showerror("Invalid",
                                     "Trainer days and hardcap must be integers.")
                return
        self.result = {
            "subscription_name": name,
            "duration_days": days,
            "price": price,
            "has_trainer": has_trainer,
            "trainer_duration_days": t_days,
            "trainer_hardcap_days": hardcap,
        }
        self.destroy()