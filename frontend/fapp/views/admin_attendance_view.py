import csv
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date

from fapp.api_client import api, APIError


def _icon_resource_path(relative_path: str) -> str:
    """Resolve assets/... for both dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    # This file lives at frontend/fapp/views/ — repo root is 3 levels up.
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, relative_path)


def set_window_icon(window):
    """
    Apply the gym's icon to any Tk/Toplevel window. Toplevels usually
    inherit their parent's icon automatically on Windows, but calling
    this explicitly on every dialog avoids relying on that inheritance
    and keeps behavior consistent (e.g. when a dialog is later detached
    or shown before its parent has finished initializing).

    Sets both iconbitmap (.ico) and iconphoto (PNG via PIL) — iconbitmap
    alone is unreliable for the title bar / Alt-Tab thumbnail on Windows
    when called before the window has a fully realized HWND.
    """
    try:
        icon_path = _icon_resource_path("assets/tgym.ico")
        if not os.path.exists(icon_path):
            return

        window.update_idletasks()

        try:
            window.iconbitmap(default=icon_path)
        except Exception as e:
            print(f"Window iconbitmap failed: {e}")

        try:
            from PIL import Image, ImageTk
            img = Image.open(icon_path)
            # Keep a reference on the window itself so it isn't GC'd
            window._icon_photo_ref = ImageTk.PhotoImage(img)
            window.iconphoto(False, window._icon_photo_ref)
        except Exception as e:
            print(f"Window iconphoto fallback failed: {e}")

    except Exception as e:
        print(f"Window icon load failed: {e}")


# ── Minimal inline calendar picker ────────────────────────────

class _CalPicker(tk.Toplevel):
    """Compact month-grid date picker. Sets result on OK."""

    def __init__(self, parent, initial: date | None = None):
        super().__init__(parent)
        self.title("Pick Date")
        self.resizable(False, False)
        set_window_icon(self)
        self.grab_set()
        self.result: date | None = None

        self._sel = initial or date.today()
        self._year  = self._sel.year
        self._month = self._sel.month

        self._build()
        self.wait_window()

    def _build(self):
        nav = tk.Frame(self)
        nav.pack(fill="x", padx=6, pady=4)
        tk.Button(nav, text="◀", command=self._prev, width=2).pack(side="left")
        self._hdr = tk.Label(nav, font=("", 10, "bold"), width=16)
        self._hdr.pack(side="left", expand=True)
        tk.Button(nav, text="▶", command=self._next, width=2).pack(side="right")

        self._grid_frm = tk.Frame(self)
        self._grid_frm.pack(padx=6)

        for i, d in enumerate(("Mo","Tu","We","Th","Fr","Sa","Su")):
            tk.Label(self._grid_frm, text=d, width=4,
                     font=("", 8, "bold")).grid(row=0, column=i)

        self._btns: list[tk.Button] = []
        for r in range(6):
            for c in range(7):
                b = tk.Button(self._grid_frm, width=3,
                              command=lambda r=r, c=c: self._click(r, c))
                b.grid(row=r+1, column=c, padx=1, pady=1)
                self._btns.append(b)

        bot = tk.Frame(self)
        bot.pack(fill="x", padx=6, pady=6)
        tk.Button(bot, text="Today",
                  command=self._today).pack(side="left")
        tk.Button(bot, text="OK",
                  command=self._ok).pack(side="right", padx=4)
        tk.Button(bot, text="Cancel",
                  command=self.destroy).pack(side="right")

        self._render()

    def _render(self):
        import calendar
        self._hdr.config(
            text=date(self._year, self._month, 1).strftime("%B %Y"))
        cal = calendar.monthcalendar(self._year, self._month)
        for i, b in enumerate(self._btns):
            r, c = divmod(i, 7)
            day = cal[r][c] if r < len(cal) else 0
            if day == 0:
                b.config(text="", state="disabled", bg="SystemButtonFace")
            else:
                is_sel = (day == self._sel.day and
                          self._year == self._sel.year and
                          self._month == self._sel.month)
                b.config(text=str(day), state="normal",
                         bg="#E8500A" if is_sel else "SystemButtonFace",
                         fg="white"  if is_sel else "black")
                b._day = day  # type: ignore[attr-defined]

    def _click(self, r, c):
        import calendar
        cal = calendar.monthcalendar(self._year, self._month)
        if r >= len(cal):
            return
        day = cal[r][c]
        if day:
            self._sel = date(self._year, self._month, day)
            self._render()

    def _prev(self):
        if self._month == 1:
            self._year -= 1; self._month = 12
        else:
            self._month -= 1
        self._render()

    def _next(self):
        if self._month == 12:
            self._year += 1; self._month = 1
        else:
            self._month += 1
        self._render()

    def _today(self):
        t = date.today()
        self._year, self._month, self._sel = t.year, t.month, t
        self._render()

    def _ok(self):
        self.result = self._sel
        self.destroy()


def _make_date_entry(parent, var: tk.StringVar, label: str) -> tk.Frame:
    """Label + read-only Entry + calendar button packed left."""
    frm = tk.Frame(parent, bg="white")
    tk.Label(frm, text=label, bg="white").pack(side="left")
    ent = tk.Entry(frm, textvariable=var, width=10, state="readonly")
    ent.pack(side="left", padx=2)
    def _pick():
        try:
            init = date.fromisoformat(var.get())
        except ValueError:
            init = date.today()
        dlg = _CalPicker(parent.winfo_toplevel(), init)
        if dlg.result:
            var.set(dlg.result.isoformat())
    tk.Button(frm, text="📅", command=_pick,
              relief="flat", padx=2).pack(side="left")
    tk.Button(frm, text="✕",
              command=lambda: var.set(""),
              relief="flat", padx=2).pack(side="left")
    return frm


def make_searchable_combobox(
    parent, var: tk.StringVar, all_values: list[str], width: int = 26,
) -> ttk.Combobox:
    """
    An editable Combobox that filters its dropdown list as the user types
    (type-to-search), instead of being locked to a closed/readonly list.

    - Typing narrows `values` to entries containing the typed text
      (case-insensitive substring match) and opens the dropdown.
    - The full list is restored when the field is cleared.
    - Clicking the dropdown arrow with an empty/unmatched field always
      shows the complete list, never an empty box.
    - Returns the live (closure-captured) full list via cb._full_values
      so callers can update it later, e.g. cb._full_values[:] = new_list.
    """
    cb = ttk.Combobox(parent, textvariable=var, state="normal", width=width)
    cb._full_values = list(all_values)
    cb["values"] = cb._full_values

    def _on_keyrelease(event=None):
        # Ignore navigation/selection keys — they shouldn't re-filter
        if event is not None and event.keysym in (
            "Up", "Down", "Left", "Right", "Return", "Tab", "Escape"
        ):
            return
        typed = var.get().strip().lower()
        if not typed:
            cb["values"] = cb._full_values
            return
        matches = [v for v in cb._full_values if typed in v.lower()]
        cb["values"] = matches if matches else cb._full_values
        try:
            cb.event_generate("<Down>") if matches else None
        except Exception:
            pass

    def _on_focus_out(event=None):
        # If what's typed doesn't exactly match any known value, leave it
        # as-is — calling code validates on submit. Just restore the full
        # list so the dropdown isn't stuck showing a filtered subset.
        cb["values"] = cb._full_values

    cb.bind("<KeyRelease>", _on_keyrelease)
    cb.bind("<FocusOut>", _on_focus_out)
    return cb


def update_searchable_combobox_values(cb: ttk.Combobox, values: list[str]):
    """Update the backing full-value list of a make_searchable_combobox()."""
    cb._full_values = list(values)
    cb["values"] = cb._full_values


# ── Main view ──────────────────────────────────────────────────

class AdminAttendanceView(tk.Frame):
    def __init__(self, master, display_queue=None, att_queue=None, **kwargs):
        super().__init__(master, bg="white")
        self._queue     = display_queue
        self._att_queue = att_queue
        self._loading   = False
        self._all_logs: list[dict] = []
        self._all_clients: list[dict] = []
        self._client_plan_map: dict[str, list[str]] = {}
        self._build()
        self._poll_att_queue()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ── Top bar ────────────────────────────────────────────
        bar = tk.Frame(self, bg="white")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        tk.Label(bar, text="Attendance Logs",
                 font=("", 14, "bold"), bg="white").pack(side="left")
        tk.Button(bar, text="Refresh", command=self.refresh,
                  relief="flat", padx=10).pack(side="right", padx=4)

        self._export_btn = tk.Button(bar, text="Export ▾",
                                     command=self._show_export_menu,
                                     relief="flat", padx=10)
        self._export_btn.pack(side="right", padx=4)

        tk.Button(bar, text="Delete Log", command=self._delete_log,
                  bg="#8B1E1E", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-Out", command=self._time_out,
                  bg="#f0a030", relief="flat", padx=10).pack(side="right", padx=4)
        tk.Button(bar, text="Time-In", command=self._time_in,
                  bg="#30a060", fg="white",
                  relief="flat", padx=10).pack(side="right", padx=4)

        # ── Filter row ─────────────────────────────────────────
        flt = tk.Frame(self, bg="white")
        flt.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        tk.Label(flt, text="Client:", bg="white").pack(side="left")
        self._client_var = tk.StringVar()
        self._client_cb = make_searchable_combobox(
            flt, self._client_var, [""], width=18)
        self._client_cb.pack(side="left", padx=4)

        self._date_exact = tk.StringVar()
        self._date_from  = tk.StringVar()
        self._date_to    = tk.StringVar()

        _make_date_entry(flt, self._date_exact, "Date:").pack(
            side="left", padx=(8, 2))
        _make_date_entry(flt, self._date_from, "From:").pack(
            side="left", padx=(8, 2))
        _make_date_entry(flt, self._date_to, "To:").pack(
            side="left", padx=(4, 2))

        tk.Button(flt, text="Filter", command=self._filter,
                  relief="flat", padx=8).pack(side="left", padx=6)
        tk.Button(flt, text="Clear", command=self.refresh,
                  relief="flat", padx=8).pack(side="left")

        tk.Label(flt, text="Plan:", bg="white").pack(side="left", padx=(10, 0))
        self._plan_filter_var = tk.StringVar(value="All Plans")
        self._plan_filter_cb = ttk.Combobox(
            flt, textvariable=self._plan_filter_var,
            values=["All Plans"], state="readonly", width=16)
        self._plan_filter_cb.pack(side="left", padx=4)
        self._plan_filter_cb.bind("<<ComboboxSelected>>",
                                  lambda _e: self._apply_plan_filter())

        # ── Tree (extended multiselect + checkboxes) ───────────
        cols = ("chk", "uid", "date", "client", "time_in", "time_out")
        self._tree = ttk.Treeview(self, columns=cols,
                                  show="headings", selectmode="extended")
        for col, txt, w in [
            ("chk",      "☐",         28),
            ("uid",      "UID",        60),
            ("date",     "Date",      100),
            ("client",   "Client",    180),
            ("time_in",  "Time In",    90),
            ("time_out", "Time Out",   90),
        ]:
            self._tree.heading(col, text=txt,
                               command=lambda c=col: self._sort(c))
            self._tree.column(col, width=w, anchor="center")
        self._tree.column("uid", width=0, minwidth=0, stretch=False)
        self._tree.heading("uid", text="")
        self._tree.column("chk", width=28, minwidth=28, stretch=False)
        self._tree.heading("chk", text="☐", command=self._toggle_all)

        self._checked: set[str] = set()   # iids of checked log rows

        self._tree.tag_configure("date_group", background="#FFF0E8")
        self._tree.tag_configure("still_in",   foreground="#1a8040")

        self._tree.bind("<ButtonRelease-1>", self._on_click)

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

        self._sort_col: str | None = None
        self._sort_asc = True

        self.refresh()

    # ---------------------------------------------------------
    # Async helpers
    # ---------------------------------------------------------

    def _set_loading(self, value: bool, text: str | None = None):
        self._loading = value
        if text is not None:
            self._status.config(text=text)

    def _run_worker(self, target, name: str):
        threading.Thread(target=target, daemon=True, name=name).start()

    def _show_error(self, msg: str):
        self._set_loading(False, msg)

    def _poll_att_queue(self):
        """Poll att_queue for scanner-driven time-in/out events."""
        if self._att_queue:
            try:
                while True:
                    self._att_queue.get_nowait()
                    # Only re-fetch if not already loading
                    if not self._loading:
                        self._filter()
            except Exception:
                pass
        self.after(500, self._poll_att_queue)

    # ---------------------------------------------------------
    # Refresh — today by default
    # ---------------------------------------------------------

    def refresh(self):
        if self._loading:
            return
        today = date.today().isoformat()
        self._date_exact.set(today)
        self._date_from.set("")
        self._date_to.set("")
        self._client_var.set("")
        self._sort_col = None
        self._sort_asc = True
        for c, lbl in {"date": "Date", "client": "Client",
                       "time_in": "Time In", "time_out": "Time Out"}.items():
            self._tree.heading(c, text=lbl)
        self._set_loading(True, "Loading attendance...")
        self._run_worker(self._refresh_worker, "att-refresh")

    def _refresh_worker(self):
        try:
            clients_list = api.list_clients()
            try:
                subs = api.list_subscriptions()
            except Exception:
                subs = []
            today = date.today().isoformat()
            logs  = api.list_attendance(date_exact=today)
            self.after(0, lambda: self._refresh_complete(clients_list, logs, subs))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _refresh_complete(self, clients_list: list[dict], logs: list[dict],
                          subs: list[dict] | None = None):
        names = [c["client_name"] for c in clients_list]
        update_searchable_combobox_values(self._client_cb, [""] + names)
        self._client_cb.set("")
        self._all_clients = clients_list
        # Reconciled against a live collection_group check rather than
        # trusting active_subscription_names on its own — see
        # api.get_reconciled_client_plans for why this matters.
        self._client_plan_map = api.get_reconciled_client_plans(clients_list)

        if subs is not None:
            plan_names = sorted({s["subscription_name"] for s in subs})
            self._plan_filter_cb["values"] = ["All Plans"] + plan_names
            self._plan_filter_var.set("All Plans")

        self._all_logs = logs
        self._apply_plan_filter()
        self._set_loading(False)

    def _get_visible_logs(self) -> list[dict]:
        """
        Returns the logs currently shown on screen — after the date/client
        filter (already applied server-side into self._all_logs) and the
        plan filter (applied client-side). Used by both _populate and export
        so the two never disagree about what "visible" means.
        """
        plan = self._plan_filter_var.get()
        if plan and plan != "All Plans":
            matching_names = {
                c["client_name"] for c in self._all_clients
                if plan in self._client_plan_map.get(c["client_name"], [])
            }
            return [l for l in self._all_logs
                   if l["client_name"] in matching_names]
        return self._all_logs

    def _apply_plan_filter(self):
        """Filter the currently loaded logs to clients on the selected plan."""
        self._populate(self._get_visible_logs())

    def _refresh_client_cb(self):
        """Refresh client dropdown live before time-in/out actions."""
        def _worker():
            try:
                clients_list = api.list_clients()
                names = [c["client_name"] for c in clients_list]
                self.after(0, lambda: update_searchable_combobox_values(
                    self._client_cb, [""] + names))
            except Exception:
                pass
        self._run_worker(_worker, "att-cb-refresh")

    # ---------------------------------------------------------
    # Filter
    # ---------------------------------------------------------

    def _filter(self):
        if self._loading:
            return
        client = self._client_var.get() or None
        exact  = self._date_exact.get().strip() or None
        dfrom  = self._date_from.get().strip() or None
        dto    = self._date_to.get().strip() or None
        self._set_loading(True, "Filtering...")
        self._run_worker(
            lambda: self._filter_worker(client, exact, dfrom, dto),
            "att-filter",
        )

    def _filter_worker(self, client, exact, dfrom, dto):
        try:
            logs = api.list_attendance(client_name=client,
                                       date_exact=exact,
                                       date_from=dfrom,
                                       date_to=dto)
            self.after(0, lambda: self._filter_complete(logs))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = f"Error: {e}"
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _filter_complete(self, logs: list[dict]):
        self._all_logs = logs
        # Reset sort state so arrows match the new data order
        self._sort_col = None
        self._sort_asc = True
        for c, lbl in {"date": "Date", "client": "Client",
                       "time_in": "Time In", "time_out": "Time Out"}.items():
            self._tree.heading(c, text=lbl)
        self._apply_plan_filter()
        self._status.config(text=f"{len(logs)} record(s) — filtered")
        self._set_loading(False)

    # ---------------------------------------------------------
    # Populate — grouped by date, most-recent date first.
    # Default (no sort col): still-timed-in first, then time_in desc.
    # With sort col: sorts within each date group by that field.
    # ---------------------------------------------------------

    def _populate(self, logs: list):
        self._tree.delete(*self._tree.get_children())
        self._checked.clear()
        self._tree.heading("chk", text="☐")

        by_date: dict[str, list] = {}
        for log in logs:
            by_date.setdefault(log["log_date"], []).append(log)

        field_map = {
            "date":     "log_date",
            "client":   "client_name",
            "time_in":  "time_in",
            "time_out": "time_out",
        }

        for d in sorted(by_date.keys(), reverse=True):
            diid = f"d_{d}"
            self._tree.insert("", "end", iid=diid,
                              values=("☐", "", d, "", "", ""),
                              tags=("date_group",))

            group = by_date[d]
            if self._sort_col and self._sort_col in field_map:
                field = field_map[self._sort_col]
                group = sorted(group,
                               key=lambda l, f=field: l.get(f, "") or "",
                               reverse=not self._sort_asc)
            else:
                # Default: most recent activity on top.
                # Activity time = time_out if present, else time_in.
                # Still-timed-in entries use time_in as activity time
                # and sort above closed entries with the same time.
                def _activity_key(l):
                    t_out = l.get("time_out")
                    t_in  = l.get("time_in") or ""
                    activity = t_out if t_out else t_in
                    # Negate string for descending: prefix "~" sorts after all
                    # HH:MM strings so missing times sink to bottom
                    return (
                        activity or "",   # sort descending below
                    )
                group = sorted(group,
                               key=_activity_key,
                               reverse=True)

            for log in group:
                still = log.get("time_out") is None
                tag   = "still_in" if still else ""
                self._tree.insert(diid, "end",
                                  iid=str(log["log_uid"]),
                                  values=(
                                      "☐",
                                      log["log_uid"],
                                      log["log_date"],
                                      log["client_name"],
                                      log["time_in"],
                                      "—" if still else log.get("time_out", "—"),
                                  ),
                                  tags=(tag,))
            self._tree.item(diid, open=True)

        self._status.config(text=f"{len(logs)} record(s)")

    # ---------------------------------------------------------
    # Column sort — updates state, delegates to _populate
    # ---------------------------------------------------------

    def _sort(self, col: str):
        if col == "chk":
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        label_map = {"date": "Date", "client": "Client",
                     "time_in": "Time In", "time_out": "Time Out"}
        for c, lbl in label_map.items():
            arrow = (" ▲" if self._sort_asc else " ▼") if c == col else ""
            self._tree.heading(c, text=lbl + arrow)

        self._apply_plan_filter()

    # ---------------------------------------------------------
    # Checkbox logic
    # ---------------------------------------------------------

    def _on_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        col    = self._tree.identify_column(event.x)
        iid    = self._tree.identify_row(event.y)
        if not iid or region != "cell":
            return
        if col == "#1":   # chk column
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
            child
            for diid in self._tree.get_children("")
            for child in self._tree.get_children(diid)
        ]
        if all_rows and all(r in self._checked for r in all_rows):
            # uncheck all
            self._checked.clear()
            for iid in self._tree.get_children(""):
                self._tree.set(iid, "chk", "☐")
                for c in self._tree.get_children(iid):
                    self._tree.set(c, "chk", "☐")
            self._tree.heading("chk", text="☐")
        else:
            # check all
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

    # ---------------------------------------------------------
    # Selected UIDs — uses checkbox state, falls back to tree selection
    # ---------------------------------------------------------

    def _selected_log_uids(self) -> list[int]:
        # Prefer checked rows; fall back to tree selection if none checked
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
    # Export (CSV / PDF) — scoped to whatever is currently filtered/visible
    # ---------------------------------------------------------

    def _show_export_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Export as CSV…", command=self._export_csv)
        menu.add_command(label="Export as PDF…", command=self._export_pdf)
        x = self._export_btn.winfo_rootx()
        y = self._export_btn.winfo_rooty() + self._export_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _export_csv(self):
        logs = self._get_visible_logs()
        if not logs:
            messagebox.showinfo("Nothing to export", "No attendance logs are currently visible.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"attendance_{date.today().isoformat()}.csv",
            title="Export Attendance Logs as CSV")
        if not path:
            return
        try:
            rows = self._sorted_export_rows(logs)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Client", "Time In", "Time Out",
                                 "Days Remaining", "Expiry Warning"])
                for log in rows:
                    writer.writerow([
                        log.get("log_date", ""),
                        log.get("client_name", ""),
                        log.get("time_in", ""),
                        log.get("time_out") or "",
                        log.get("days_remaining", ""),
                        "Yes" if log.get("expiry_warning") else "",
                    ])
            messagebox.showinfo("Exported", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _export_pdf(self):
        logs = self._get_visible_logs()
        if not logs:
            messagebox.showinfo("Nothing to export", "No attendance logs are currently visible.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"attendance_{date.today().isoformat()}.pdf",
            title="Export Attendance Logs as PDF")
        if not path:
            return
        try:
            rows = self._sorted_export_rows(logs)
            pdf_bytes = self._build_attendance_pdf(rows)
            with open(path, "wb") as f:
                f.write(pdf_bytes)
            messagebox.showinfo("Exported", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _sorted_export_rows(self, logs: list[dict]) -> list[dict]:
        """Most recent date first, then by time_in descending — matches on-screen order."""
        return sorted(
            logs,
            key=lambda l: (l.get("log_date", ""), l.get("time_in", "") or ""),
            reverse=True,
        )

    def _build_attendance_pdf(self, rows: list[dict]) -> bytes:
        """
        Builds a simple tabular PDF of the given attendance rows.
        Kept local to the frontend (rather than round-tripping to the
        backend) since the rows are already filtered exactly as shown
        on screen — date range, client, and plan filter all included.
        """
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        )
        from reportlab.lib.styles import getSampleStyleSheet

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("Attendance Logs", styles["Title"]),
            Paragraph(
                f"Exported {date.today().strftime('%B %d, %Y')} — "
                f"{len(rows)} record(s)",
                styles["Normal"]),
            Spacer(1, 0.5 * cm),
        ]

        table_data = [["Date", "Client", "Time In", "Time Out",
                       "Days Left", "Expiry Warning"]]
        for log in rows:
            table_data.append([
                log.get("log_date", ""),
                log.get("client_name", ""),
                log.get("time_in", ""),
                log.get("time_out") or "—",
                str(log.get("days_remaining", "")),
                "Yes" if log.get("expiry_warning") else "",
            ])

        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8500A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F7F7F7")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)

        doc.build(elements)
        return buf.getvalue()

    # ---------------------------------------------------------
    # Delete log(s)
    # ---------------------------------------------------------

    def _delete_log(self):
        if self._loading:
            return
        uids = self._selected_log_uids()
        if not uids:
            messagebox.showwarning("Select", "Select one or more log entries to delete.")
            return
        noun = f"{len(uids)} log(s)" if len(uids) > 1 else f"log #{uids[0]}"
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Permanently delete {noun}?\n\n"
            "If a client is currently timed-in on a deleted log their status will be reset.",
        ):
            return
        self._set_loading(True, f"Deleting {len(uids)} log(s)...")
        self._run_worker(lambda: self._delete_worker(uids), "att-delete")

    def _delete_worker(self, uids: list[int]):
        errors = []
        for uid in uids:
            try:
                api.delete_attendance(uid)
            except Exception as e:
                errors.append(f"#{uid}: {e}")
        msg = f"Deleted {len(uids) - len(errors)} log(s)."
        if errors:
            msg += "  Errors: " + "; ".join(errors)
        self.after(0, lambda: self._after_delete(msg))

    def _after_delete(self, msg: str):
        self._status.config(text=msg)
        self._set_loading(False)
        # If any filter is active re-run it, otherwise fall back to today
        if (self._client_var.get() or self._date_exact.get()
                or self._date_from.get() or self._date_to.get()):
            self._filter()
        else:
            self.refresh()

    # ---------------------------------------------------------
    # Time-In / Time-Out
    # ---------------------------------------------------------

    def _time_in(self):
        if self._loading:
            return
        name = self._client_var.get()
        if not name:
            messagebox.showwarning("Select", "Select a client first.")
            return
        self._refresh_client_cb()
        if self._queue:
            self._queue.put({"type": "clear"})
        self._set_loading(True, f"Timing in {name}...")
        self._run_worker(lambda: self._time_in_worker(name), "att-time-in")

    def _time_in_worker(self, name: str):
        try:
            log = api.time_in(name)
            self.after(0, lambda: self._after_time_in(name, log))
        except APIError as e:
            err = e
            self.after(0, lambda e=err: self._time_in_error(name, e))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _after_time_in(self, name: str, log: dict):
        self._set_loading(False)
        messagebox.showinfo("Time-In", f"{name} timed in at {log['time_in']}")
        if self._queue:
            evt = "expiry_warn" if log.get("expiry_warning") else "time_in"
            sub = (f"Timed in at {log['time_in']}  |  "
                   f"{log.get('days_remaining', 0)} day(s) left"
                   if evt == "expiry_warn"
                   else f"Timed in at {log['time_in']}")
            self._queue.put({"type": evt,
                             "title": f"Welcome back, {name}",
                             "subtitle": sub})
        self._filter()

    def _time_in_error(self, name: str, e: APIError):
        self._set_loading(False)
        if self._queue and e.status_code == 403:
            self._queue.put({"type": "expired",
                             "title": "Subscription Expired",
                             "subtitle": "Please see staff to renew."})
        messagebox.showerror("Error", str(e))

    def _time_out(self):
        if self._loading:
            return
        name = self._client_var.get()
        if not name:
            messagebox.showwarning("Select", "Select a client first.")
            return
        self._refresh_client_cb()
        self._set_loading(True, f"Timing out {name}...")
        self._run_worker(lambda: self._time_out_worker(name), "att-time-out")

    def _time_out_worker(self, name: str):
        try:
            log = api.time_out(name)
            self.after(0, lambda: self._after_time_out(name, log))
        except APIError as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda msg=msg: self._show_error(msg))

    def _after_time_out(self, name: str, log: dict):
        self._set_loading(False)
        messagebox.showinfo("Time-Out", f"{name} timed out at {log['time_out']}")
        if self._queue:
            self._queue.put({"type": "time_out",
                             "title": f"Goodbye, {name}",
                             "subtitle": f"Timed out at {log['time_out']}"})
        self._filter()