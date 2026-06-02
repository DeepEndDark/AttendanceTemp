"""
Locker management view.
Shows a graphical grid of all lockers — green=available, blue=rented, amber=expiring.
Admin: assign, unassign. Sales: assign only.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


COLS = 8   # lockers per row in the grid


class LockerView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._is_admin = False
        self._locker_data: dict[int, dict] = {}   # locker_num -> client data
        self._locker_buttons: dict[int, tk.Button] = {}
        self._total = 0
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Toolbar
        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Locker Management",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)
        self._unassign_btn = tk.Button(
            bar, text="Unassign Selected",
            command=self._unassign_locker,
            bg="#e04040", fg="white",
            relief="flat", padx=10)
        # Shown only for admin — packed in refresh()
        tk.Button(bar, text="Assign Locker",
                  command=self._assign_locker,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # Availability summary
        summary = tk.Frame(self, bg="#E6F1FB", relief="groove", bd=1)
        summary.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._avail_lbl = tk.Label(summary, text="", bg="#E6F1FB",
                                   font=("", 10), pady=8)
        self._avail_lbl.pack(side="left", padx=16)

        # Legend
        leg = tk.Frame(summary, bg="#E6F1FB")
        leg.pack(side="right", padx=16)
        for color, label in [("#2ECC71", "Available"),
                              ("#185FA5", "Rented"),
                              ("#BA7517", "Expiring ≤3 days")]:
            dot = tk.Frame(leg, bg=color, width=14, height=14)
            dot.pack(side="left", padx=(8, 2))
            tk.Label(leg, text=label, bg="#E6F1FB",
                     font=("", 9)).pack(side="left", padx=(0, 8))

        # Locker grid canvas with scrollbar
        grid_container = tk.Frame(self, bg="white")
        grid_container.grid(row=2, column=0, sticky="nsew",
                            padx=16, pady=4)
        grid_container.columnconfigure(0, weight=1)
        grid_container.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(grid_container, bg="white",
                                 highlightthickness=0)
        vsb = ttk.Scrollbar(grid_container, orient="vertical",
                            command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._grid_frame = tk.Frame(self._canvas, bg="white")
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._grid_frame, anchor="nw")

        self._grid_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._status = tk.Label(self, text="", fg="gray",
                                bg="white", anchor="w")
        self._status.grid(row=3, column=0, sticky="ew",
                          padx=16, pady=6)

        self._selected_locker: int | None = None
        self.refresh()

    def _on_frame_configure(self, _=None):
        self._canvas.configure(
            scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(
            self._canvas_window, width=event.width)

    def refresh(self):
        try:
            self._is_admin = api.is_admin
            avail = api.get_locker_availability()
            self._total = avail["total"]
            clients = api.list_clients()
        except APIError as e:
            self._status.config(text=str(e))
            return

        # Build locker->client map
        self._locker_data = {}
        for c in clients:
            n = c.get("locker_number")
            if n:
                self._locker_data[n] = c

        self._avail_lbl.config(
            text=(f"Total: {avail['total']}   |   "
                  f"Rented: {avail['rented']}   |   "
                  f"Available: {avail['available']}   |   "
                  f"₱{avail['price']:.2f} / {avail['rental_days']} days"))

        # Show/hide unassign button
        if self._is_admin:
            self._unassign_btn.pack(side="right", padx=4)
        else:
            self._unassign_btn.pack_forget()

        self._selected_locker = None
        self._rebuild_grid()
        self._status.config(
            text=f"{avail['rented']} locker(s) rented")

    def _style_locker_button(self, num: int):
        """
        Apply visual selected-state styling to one locker button only.
        Does not rebuild the grid.
        """
        btn = self._locker_buttons.get(num)
        if btn is None:
            return

        selected = (num == self._selected_locker)

        btn.config(
            relief="sunken" if selected else "raised",
            bd=3,
            font=("", 8, "bold" if selected else "normal"),
            highlightthickness=2,
            highlightbackground="#FFD54F" if selected else "white",
            highlightcolor="#FFD54F" if selected else "white",
            activebackground=btn.cget("bg"),
        )

    def _rebuild_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()

        self._locker_buttons.clear()

        for i in range(self._total):
            num = i + 1
            row = i // COLS
            col = i % COLS

            c = self._locker_data.get(num)
            if c is None:
                bg, fg = "#2ECC71", "white"
                label = f"#{num}\nFree"
            else:
                days = c["client_locker_days_remaining"]
                if days <= 3:
                    bg, fg = "#BA7517", "white"
                else:
                    bg, fg = "#185FA5", "white"
                name = c["client_name"]
                name_short = name[:10] + "…" if len(name) > 10 else name
                label = f"#{num}\n{name_short}\n{days}d"

            btn = tk.Button(
                self._grid_frame,
                text=label,
                bg=bg, fg=fg,
                width=9, height=3,
                command=lambda n=num: self._on_locker_click(n))
            self._locker_buttons[num] = btn
            self._style_locker_button(num)
            btn.grid(row=row, column=col, padx=7, pady=7)

    def _on_locker_click(self, num: int):
        previous = self._selected_locker
        self._selected_locker = num

        if previous is not None and previous != num:
            self._style_locker_button(previous)
        self._style_locker_button(num)

        c = self._locker_data.get(num)
        if c:
            self._status.config(
                text=f"Selected: Locker #{num} — {c['client_name']} "
                     f"({c['client_locker_days_remaining']} days remaining)",
                fg="#185FA5")
        else:
            self._status.config(
                text=f"Selected: Locker #{num} — Available",
                fg="#2ECC71")

    def _assign_locker(self):
        # Hard block if selected locker is already rented
        if self._selected_locker and self._selected_locker in self._locker_data:
            c = self._locker_data[self._selected_locker]
            messagebox.showwarning(
                "Locker Occupied",
                f"Locker #{self._selected_locker} is already assigned to "
                f"'{c['client_name']}' ({c['client_locker_days_remaining']} days remaining).\n\n"
                "Unassign it first before reassigning.")
            return

        try:
            avail = api.get_locker_availability()
            all_clients = [c["client_name"] for c in api.list_clients()]
        except APIError as e:
            messagebox.showerror("Error", str(e))
            return

        # Pre-fill locker number if a free one is selected
        preselect = None
        if self._selected_locker and self._selected_locker not in self._locker_data:
            preselect = self._selected_locker

        dlg = _AssignDialog(self, total=avail["total"],
                            all_clients=all_clients,
                            preselect_locker=preselect)
        if dlg.result:
            try:
                result = api.assign_locker(
                    dlg.result["client_name"],
                    dlg.result["locker_number"])
                messagebox.showinfo(
                    "Locker Assigned",
                    f"Locker #{result['locker_number']} assigned to "
                    f"{result['client_name']}\n"
                    f"Days: {result['days_added']}  |  "
                    f"Expires: {result['expires_at']}")
                self._refresh_tile(dlg.result["locker_number"])
            except APIError as e:
                messagebox.showerror("Error", str(e))

    def _refresh_tile(self, num: int):
        """Refresh a single locker tile without reloading the whole grid."""
        try:
            clients = api.list_clients()
        except APIError:
            return
        # Update local data
        self._locker_data = {
            c["locker_number"]: c
            for c in clients if c.get("locker_number")
        }
        # Find and update just the affected button
        row = (num - 1) // COLS
        col = (num - 1) % COLS
        c = self._locker_data.get(num)
        if c is None:
            bg, fg, label = "#2ECC71", "white", f"#{num}\nFree"
        else:
            days = c["client_locker_days_remaining"]
            bg = "#BA7517" if days <= 3 else "#185FA5"
            fg = "white"
            name_short = c["client_name"][:10] + "…" \
                if len(c["client_name"]) > 10 else c["client_name"]
            label = f"#{num}\n{name_short}\n{days}d"
        btn = self._locker_buttons.get(num)
        if btn is not None:
            btn.config(text=label, bg=bg, fg=fg)
            self._style_locker_button(num)
        else:
            # Fallback only if the button registry is unexpectedly missing.
            for widget in self._grid_frame.grid_slaves(row=row, column=col):
                widget.config(text=label, bg=bg, fg=fg)
        # Update availability summary count
        rented = len(self._locker_data)
        avail = self._total - rented
        try:
            avail_data = api.get_locker_availability()
            self._avail_lbl.config(
                text=(f"Total: {avail_data['total']}   |   "
                      f"Rented: {avail_data['rented']}   |   "
                      f"Available: {avail_data['available']}   |   "
                      f"₱{avail_data['price']:.2f} / {avail_data['rental_days']} days"))
        except Exception:
            pass

    def _unassign_locker(self):
        if not self._selected_locker:
            messagebox.showwarning("Select", "Click a rented locker first.")
            return
        c = self._locker_data.get(self._selected_locker)
        if not c:
            messagebox.showinfo("Free", "That locker is already free.")
            return
        if not messagebox.askyesno(
                "Confirm Unassign",
                f"Unassign Locker #{self._selected_locker} from "
                f"'{c['client_name']}'?\n\n"
                "WARNING: Remaining days will be lost and no refund "
                "will be recorded."):
            return
        try:
            api.unassign_locker(self._selected_locker)
            num = self._selected_locker
            self._selected_locker = None
            self._style_locker_button(num)
            self._status.config(text=f"Locker #{num} unassigned.", fg="gray")
            self._refresh_tile(num)
        except APIError as e:
            messagebox.showerror("Error", str(e))


class _AssignDialog(tk.Toplevel):
    def __init__(self, parent, total: int, all_clients: list,
                 preselect_locker: int | None = None):
        super().__init__(parent)
        self.title("Assign Locker")
        self.configure(bg="white")
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        frame = tk.Frame(self, bg="white", padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Assign Locker",
                 font=("", 11, "bold"), bg="white",
                 fg="#185FA5").grid(row=0, column=0, columnspan=2,
                                    sticky="w", pady=(0, 12))

        tk.Label(frame, text="Client:", bg="white",
                 font=("", 9)).grid(row=1, column=0, sticky="w", pady=6)
        self._client_var = tk.StringVar()
        cb = ttk.Combobox(frame, textvariable=self._client_var,
                          values=all_clients, state="readonly", width=26)
        cb.grid(row=1, column=1, padx=(10, 0), pady=6)
        if all_clients:
            cb.current(0)

        tk.Label(frame, text=f"Locker # (1–{total}):",
                 bg="white", font=("", 9)).grid(
            row=2, column=0, sticky="w", pady=6)
        self._num_var = tk.StringVar(
            value=str(preselect_locker) if preselect_locker else "")
        tk.Entry(frame, textvariable=self._num_var,
                 width=10, relief="solid", bd=1).grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=6)

        self._err = tk.Label(frame, text="", fg="red",
                             bg="white", font=("", 9))
        self._err.grid(row=3, column=0, columnspan=2,
                       sticky="w", pady=(2, 0))

        btn_row = tk.Frame(frame, bg="white")
        btn_row.grid(row=4, column=0, columnspan=2,
                     pady=(14, 0), sticky="e")
        tk.Button(btn_row, text="Cancel", command=self.destroy,
                  relief="flat", padx=12, pady=6,
                  bg="#f0f0f0").pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Assign",
                  command=self._save,
                  relief="flat", padx=12, pady=6,
                  bg="#185FA5", fg="white").pack(side="right")
        self.wait_window()

    def _save(self):
        client = self._client_var.get()
        if not client:
            self._err.config(text="Select a client.")
            return
        try:
            num = int(self._num_var.get())
            if num < 1:
                raise ValueError
        except ValueError:
            self._err.config(text="Locker number must be a positive integer.")
            return
        self.result = {"client_name": client, "locker_number": num}
        self.destroy()