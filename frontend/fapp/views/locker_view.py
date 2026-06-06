"""
Locker management view.
Shows a graphical grid of all lockers — green=available, blue=rented, amber=expiring.
Admin: assign, unassign. Sales: assign only.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from fapp.api_client import api, APIError


COLS = 8   # lockers per row in the grid


class LockerView(tk.Frame):
    def __init__(self, master, display_queue=None):
        super().__init__(master, bg="white")
        self._is_admin = False
        self._locker_data: dict[int, dict] = {}
        self._locker_buttons: dict[int, tk.Button] = {}
        self._total = 0
        self._loading = False
        self._build()

    # ---------------------------------------------------------
    # Build
    # ---------------------------------------------------------

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

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
        tk.Button(bar, text="Assign Locker",
                  command=self._assign_locker,
                  bg="#185FA5", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        summary = tk.Frame(self, bg="#E6F1FB", relief="groove", bd=1)
        summary.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._avail_lbl = tk.Label(summary, text="", bg="#E6F1FB",
                                   font=("", 10), pady=8)
        self._avail_lbl.pack(side="left", padx=16)

        leg = tk.Frame(summary, bg="#E6F1FB")
        leg.pack(side="right", padx=16)
        for color, label in [("#2ECC71", "Available"),
                              ("#185FA5", "Rented"),
                              ("#BA7517", "Expiring ≤3 days")]:
            tk.Frame(leg, bg=color, width=14, height=14).pack(
                side="left", padx=(8, 2))
            tk.Label(leg, text=label, bg="#E6F1FB",
                     font=("", 9)).pack(side="left", padx=(0, 8))

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
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ---------------------------------------------------------
    # Async helpers
    # ---------------------------------------------------------

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        if text is not None:
            self._status.config(text=text, fg="gray")

    def _run_worker(self, target, name: str):
        threading.Thread(target=target, daemon=True, name=name).start()

    def _show_error(self, msg: str):
        self._set_loading(False, msg)

    # ---------------------------------------------------------
    # Refresh
    # ---------------------------------------------------------

    def refresh(self):
        if self._loading:
            return
        self._set_loading(True, "Loading lockers...")
        self._run_worker(self._refresh_worker, "locker-refresh")

    def _refresh_worker(self):
        try:
            avail   = api.get_locker_availability()
            clients = api.list_clients()
            self.after(0, lambda: self._refresh_complete(avail, clients))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _refresh_complete(self, avail: dict, clients: list):
        self._is_admin = api.is_admin
        self._total    = avail["total"]

        self._locker_data = {
            c["locker_number"]: c
            for c in clients if c.get("locker_number")
        }

        self._avail_lbl.config(
            text=(f"Total: {avail['total']}   |   "
                  f"Rented: {avail['rented']}   |   "
                  f"Available: {avail['available']}   |   "
                  f"₱{avail['price']:.2f} / {avail['rental_days']} days"))

        if self._is_admin:
            self._unassign_btn.pack(side="right", padx=4)
        else:
            self._unassign_btn.pack_forget()

        self._selected_locker = None
        self._rebuild_grid()
        self._set_loading(False, f"{avail['rented']} locker(s) rented")

    # ---------------------------------------------------------
    # Grid
    # ---------------------------------------------------------

    def _style_locker_button(self, num: int):
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
            c   = self._locker_data.get(num)

            if c is None:
                bg, fg = "#2ECC71", "white"
                label = f"#{num}\nFree"
            else:
                days = c["client_locker_days_remaining"]
                bg   = "#BA7517" if days <= 3 else "#185FA5"
                fg   = "white"
                name_short = c["client_name"][:10] + "…" \
                    if len(c["client_name"]) > 10 else c["client_name"]
                label = f"#{num}\n{name_short}\n{days}d"

            btn = tk.Button(
                self._grid_frame,
                text=label, bg=bg, fg=fg,
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

    # ---------------------------------------------------------
    # Assign locker
    # ---------------------------------------------------------

    def _assign_locker(self):
        if self._loading:
            return
        if self._selected_locker and self._selected_locker in self._locker_data:
            c = self._locker_data[self._selected_locker]
            messagebox.showwarning(
                "Locker Occupied",
                f"Locker #{self._selected_locker} is already assigned to "
                f"'{c['client_name']}' ({c['client_locker_days_remaining']} days remaining).\n\n"
                "Unassign it first before reassigning.")
            return

        preselect = (self._selected_locker
                     if self._selected_locker and
                     self._selected_locker not in self._locker_data
                     else None)

        self._set_loading(True, "Loading clients...")
        self._run_worker(
            lambda: self._assign_load_worker(preselect),
            "locker-assign-load")

    def _assign_load_worker(self, preselect: int | None):
        try:
            avail   = api.get_locker_availability()
            clients = [c["client_name"] for c in api.list_clients()]
            self.after(0, lambda: self._assign_dialog(avail, clients, preselect))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _assign_dialog(self, avail: dict, clients: list, preselect: int | None):
        self._set_loading(False)
        dlg = _AssignDialog(self, total=avail["total"],
                            all_clients=clients,
                            preselect_locker=preselect)
        if not dlg.result:
            return
        client_name   = dlg.result["client_name"]
        locker_number = dlg.result["locker_number"]
        self._set_loading(True, f"Assigning locker #{locker_number}...")
        self._run_worker(
            lambda: self._assign_worker(client_name, locker_number),
            "locker-assign")

    def _assign_worker(self, client_name: str, locker_number: int):
        try:
            result = api.assign_locker(client_name, locker_number)
            self.after(0, lambda: self._assign_complete(result))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _assign_complete(self, result: dict):
        self._set_loading(False)
        messagebox.showinfo(
            "Locker Assigned",
            f"Locker #{result['locker_number']} assigned to "
            f"{result['client_name']}\n"
            f"Days: {result['days_added']}  |  "
            f"Expires: {result['expires_at']}")
        self._refresh_tile_async(result["locker_number"])

    # ---------------------------------------------------------
    # Refresh single tile
    # ---------------------------------------------------------

    def _refresh_tile_async(self, num: int):
        self._run_worker(
            lambda: self._tile_worker(num),
            "locker-tile-refresh")

    def _tile_worker(self, num: int):
        try:
            clients = api.list_clients()
            avail   = api.get_locker_availability()
            self.after(0, lambda: self._tile_complete(num, clients, avail))
        except APIError:
            pass
        except Exception:
            pass

    def _tile_complete(self, num: int, clients: list, avail: dict):
        self._locker_data = {
            c["locker_number"]: c
            for c in clients if c.get("locker_number")
        }
        c = self._locker_data.get(num)
        if c is None:
            bg, fg, label = "#2ECC71", "white", f"#{num}\nFree"
        else:
            days       = c["client_locker_days_remaining"]
            bg         = "#BA7517" if days <= 3 else "#185FA5"
            fg         = "white"
            name_short = c["client_name"][:10] + "…" \
                if len(c["client_name"]) > 10 else c["client_name"]
            label = f"#{num}\n{name_short}\n{days}d"

        btn = self._locker_buttons.get(num)
        if btn:
            btn.config(text=label, bg=bg, fg=fg)
            self._style_locker_button(num)

        self._avail_lbl.config(
            text=(f"Total: {avail['total']}   |   "
                  f"Rented: {avail['rented']}   |   "
                  f"Available: {avail['available']}   |   "
                  f"₱{avail['price']:.2f} / {avail['rental_days']} days"))
        self._status.config(
            text=f"{avail['rented']} locker(s) rented", fg="gray")

    # ---------------------------------------------------------
    # Unassign (admin only)
    # ---------------------------------------------------------

    def _unassign_locker(self):
        if self._loading:
            return
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
        num = self._selected_locker
        self._set_loading(True, f"Unassigning locker #{num}...")
        self._run_worker(lambda: self._unassign_worker(num), "locker-unassign")

    def _unassign_worker(self, num: int):
        try:
            api.unassign_locker(num)
            self.after(0, lambda: self._unassign_complete(num))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _unassign_complete(self, num: int):
        self._selected_locker = None
        self._set_loading(False, f"Locker #{num} unassigned.")
        self._refresh_tile_async(num)


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