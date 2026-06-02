"""
API client — single persistent requests.Session per login session.
Prevents connection exhaustion / memory leak from repeated calls.

Conservative fixes:
  - Adds request timeouts to prevent indefinite hangs.
  - Does NOT add global session locking.
  - Does NOT prefetch sales on login.
  - Does NOT change cache architecture.
  - Keeps original login/prefetch behavior stable.
"""

import threading
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"

# connect timeout, read timeout
DEFAULT_TIMEOUT = (5, 30)


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class DataCache:
    """
    Thread-safe key-value cache for Firestore collection data.
    Keys map to the last fetched result. A None value means not yet loaded.
    """

    KEYS = [
        "clients",
        "subscriptions",
        "items",
        "locker_availability",
        "locker_settings",
        "accounts",
        "attendance",
        "sales",
    ]

    def __init__(self):
        self._data: dict = {}
        self._locks: dict = {k: threading.Lock() for k in self.KEYS}
        self._ready: dict = {k: threading.Event() for k in self.KEYS}

    def set(self, key: str, value) -> None:
        with self._locks.get(key, threading.Lock()):
            self._data[key] = value
            ev = self._ready.get(key)
            if ev:
                ev.set()

    def get(self, key: str, timeout: float = 0.0):
        """
        Return cached value. If not yet loaded and timeout > 0, wait up to
        timeout seconds for a background fetch to complete.
        Returns None if still not available.
        """

        ev = self._ready.get(key)

        if ev and not ev.is_set() and timeout > 0:
            ev.wait(timeout=timeout)

        return self._data.get(key)

    def invalidate(self, *keys: str) -> None:
        for key in keys:
            with self._locks.get(key, threading.Lock()):
                self._data.pop(key, None)
                ev = self._ready.get(key)
                if ev:
                    ev.clear()

    def clear(self) -> None:
        for key in self.KEYS:
            with self._locks.get(key, threading.Lock()):
                self._data.pop(key, None)
                ev = self._ready.get(key)
                if ev:
                    ev.clear()

    def is_ready(self, key: str) -> bool:
        ev = self._ready.get(key)
        return bool(ev and ev.is_set())


class APIClient:
    def __init__(self):
        self._token: str | None = None
        self.account_name: str | None = None
        self.account_type: str | None = None
        self._session = requests.Session()
        self.cache = DataCache()

    @property
    def is_admin(self) -> bool:
        return self.account_type == "admin"

    def _reset_session(self):
        try:
            self._session.close()
        except Exception:
            pass

        self._session = requests.Session()

    def _prefetch_one(self, key: str, fn) -> None:
        """Fetch one key in a background thread and store in cache."""

        def _run():
            try:
                result = fn()
                self.cache.set(key, result)
            except Exception:
                # On failure set empty so views don't wait forever
                self.cache.set(
                    key,
                    [] if key not in (
                        "locker_availability",
                        "locker_settings",
                    ) else {}
                )

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"prefetch-{key}",
        ).start()

    def _prefetch_all(self) -> None:
        """Kick off background pre-fetch for all cache keys after login."""

        self._prefetch_one(
            "clients",
            lambda: self._get("/clients")
        )

        self._prefetch_one(
            "subscriptions",
            lambda: self._get("/subscriptions")
        )

        self._prefetch_one(
            "items",
            lambda: self._get("/items")
        )

        self._prefetch_one(
            "locker_availability",
            lambda: self._get("/lockers/available")
        )

        self._prefetch_one(
            "locker_settings",
            lambda: self._get("/lockers/settings")
        )

        self._prefetch_one(
            "accounts",
            lambda: self._get("/accounts")
        )

        # IMPORTANT:
        # Do NOT prefetch sales here.
        # /sales can be heavy and was likely causing the freeze.

    def _refresh_bg(self, *keys: str) -> None:
        """Invalidate keys and kick off background re-fetch."""

        self.cache.invalidate(*keys)

        fn_map = {
            "clients": lambda: self._get("/clients"),
            "subscriptions": lambda: self._get("/subscriptions"),
            "items": lambda: self._get("/items"),
            "locker_availability": lambda: self._get("/lockers/available"),
            "locker_settings": lambda: self._get("/lockers/settings"),
            "accounts": lambda: self._get("/accounts"),
            # Keep sales out of automatic background refresh for now.
            # SalesView should load sales in its own worker thread.
        }

        for key in keys:
            if key in fn_map:
                self._prefetch_one(key, fn_map[key])

    # ── Auth ─────────────────────────────────────────────────

    def login(self, username: str, password: str) -> None:
        r = self._session.post(
            f"{BASE_URL}/auth/login",
            data={
                "username": username,
                "password": password,
            },
            timeout=DEFAULT_TIMEOUT,
        )

        self._raise(r)

        body = r.json()

        self._token = body["access_token"]
        self.account_name = username
        self.account_type = body["account_type"]

        threading.Thread(
            target=self._prefetch_all,
            daemon=True,
            name="prefetch-all",
        ).start()

    def logout(self) -> None:
        self._token = None
        self.account_name = None
        self.account_type = None
        self.cache.clear()
        self._reset_session()

    # ── Accounts ─────────────────────────────────────────────

    def list_accounts(self):
        c = self.cache.get("accounts", timeout=3)
        return c if c is not None else self._get("/accounts")

    def create_account(self, name, role, password):
        r = self._post(
            "/accounts",
            {
                "account_name": name,
                "account_type": role,
                "password": password,
            },
        )
        self._refresh_bg("accounts")
        return r

    def update_account(self, name, role=None, password=None):
        body = {}

        if role:
            body["account_type"] = role

        if password:
            body["password"] = password

        r = self._patch(f"/accounts/{name}", body)
        self._refresh_bg("accounts")
        return r

    def delete_account(self, name):
        self._delete(f"/accounts/{name}")
        self._refresh_bg("accounts")

    # ── Subscriptions ─────────────────────────────────────────

    def list_subscriptions(self):
        c = self.cache.get("subscriptions", timeout=3)
        return c if c is not None else self._get("/subscriptions")

    def create_subscription(self, data):
        r = self._post("/subscriptions", data)
        self._refresh_bg("subscriptions")
        return r

    def update_subscription(self, name, data):
        r = self._patch(f"/subscriptions/{name}", data)
        self._refresh_bg("subscriptions")
        return r

    def delete_subscription(self, name):
        self._delete(f"/subscriptions/{name}")
        self._refresh_bg("subscriptions")

    def rename_subscription(self, name: str, new_name: str):
        r = self._post(
            f"/subscriptions/{name}/rename",
            {"new_name": new_name},
        )
        self._refresh_bg("subscriptions")
        return r

    # ── Clients ───────────────────────────────────────────────

    def list_clients(self):
        c = self.cache.get("clients", timeout=3)
        return c if c is not None else self._get("/clients")

    def list_active_clients(self):
        return self._get("/clients/active")

    def get_client(self, name):
        return self._get(f"/clients/{name}")

    def get_client_subscriptions(self, name):
        return self._get(f"/clients/{name}/subscriptions")

    def create_client(self, data):
        r = self._post("/clients", data)
        self._refresh_bg("clients")
        return r

    def re_enroll_client(self, name, subscription_name):
        r = self._post(
            f"/clients/{name}/re-enroll",
            {"subscription_name": subscription_name},
        )
        self._refresh_bg("clients")
        return r

    def update_client(self, name, data):
        r = self._patch(f"/clients/{name}", data)
        self._refresh_bg("clients")
        return r

    def delete_client(self, name):
        self._delete(f"/clients/{name}")
        self._refresh_bg("clients")

    def deduct_trainer(self, name):
        r = self._post(f"/clients/{name}/deduct-trainer", {})
        self._refresh_bg("clients")
        return r

    def enroll_fingerprint(self, name):
        r = self._post(f"/clients/{name}/enroll-fingerprint", {})
        self._refresh_bg("clients")
        return r

    def get_enroll_progress(self):
        return self._get("/clients/enroll-fingerprint/progress")

    # ── Attendance ────────────────────────────────────────────

    def list_attendance(
        self,
        client_name=None,
        date_from=None,
        date_to=None,
        date_exact=None,
    ):
        params = {}

        if client_name:
            params["client_name"] = client_name

        if date_from:
            params["date_from"] = date_from

        if date_to:
            params["date_to"] = date_to

        if date_exact:
            params["date_exact"] = date_exact

        return self._get_params("/attendance", params)

    def get_client_attendance(self, name):
        return self._get(f"/attendance/client/{name}")

    def time_in(self, client_name):
        r = self._post(
            "/attendance/time-in",
            {"client_name": client_name},
        )
        self._refresh_bg("clients")
        return r

    def time_out(self, client_name):
        r = self._post(
            "/attendance/time-out",
            {"client_name": client_name},
        )
        self._refresh_bg("clients")
        return r

    def finger_touch(self):
        """
        Blocks up to ~32 s waiting for a finger to be physically placed.
        Returns True on touch, False on timeout or error.
        """

        try:
            r = self._session.post(
                f"{BASE_URL}/attendance/finger-touch",
                json={},
                headers=self._headers(),
                timeout=(5, 35),  # read timeout > server-side 30 s
            )

            if r.status_code == 200:
                return r.json().get("touched", False)

        except Exception:
            pass

        return False

    def fingerprint_scan(self):
        """
        Blocks up to ~10 s for next finger scan result.
        Returns display event dict or None on error.
        Read timeout must exceed scanner's 7 s capture window.
        """

        try:
            r = self._session.post(
                f"{BASE_URL}/attendance/scan",
                json={},
                headers=self._headers(),
                timeout=(5, 12),
            )

            if r.status_code == 200:
                return r.json()

        except Exception:
            pass

        return None

    # ── Items ─────────────────────────────────────────────────

    def list_items(self):
        c = self.cache.get("items", timeout=3)
        return c if c is not None else self._get("/items")

    def create_item(self, name, price, stock):
        r = self._post(
            "/items",
            {
                "item_name": name,
                "price": price,
                "stock": stock,
            },
        )
        self._refresh_bg("items")
        return r

    def update_item(self, name, price=None, stock=None):
        body = {}

        if price is not None:
            body["price"] = price

        if stock is not None:
            body["stock"] = stock

        r = self._patch(f"/items/{name}", body)
        self._refresh_bg("items")
        return r

    def delete_item(self, name):
        self._delete(f"/items/{name}")
        self._refresh_bg("items")

    def rename_item(self, item_name: str, new_name: str):
        r = self._post(
            f"/items/{item_name}/rename",
            {"new_name": new_name},
        )
        self._refresh_bg("items")
        return r

    # ── Sales ─────────────────────────────────────────────────

    def list_open_sales(self):
        return self._get("/sales/open")

    def list_all_sales(
        self,
        client_name=None,
        item_name=None,
        date_from=None,
        date_to=None,
        date_exact=None,
        sale_status=None,
    ):
        params = {}

        if client_name:
            params["client_name"] = client_name

        if item_name:
            params["item_name"] = item_name

        if date_from:
            params["date_from"] = date_from

        if date_to:
            params["date_to"] = date_to

        if date_exact:
            params["date_exact"] = date_exact

        if sale_status:
            params["sale_status"] = sale_status

        # No cache here for now.
        # SalesView should fetch this in a worker thread.
        return self._get_params("/sales", params)

    def get_client_sales(self, name):
        return self._get(f"/sales/client/{name}")

    def get_sale(self, uid):
        """Fetch one sale with item_list. Used when a Sales row is selected."""
        return self._get(f"/sales/detail/{uid}")

    def open_sale(self, client_name):
        r = self._post(
            "/sales/open",
            {"client_name": client_name},
        )

        # Do not auto-refresh sales cache here.
        # SalesView will refresh itself after mutation.
        self._refresh_bg("clients")
        return r

    def add_item_to_sale(self, uid, item_name, qty):
        r = self._post(
            f"/sales/{uid}/add-item",
            {
                "item_name": item_name,
                "item_qty": qty,
            },
        )

        self._refresh_bg("items")
        return r

    def remove_item_from_sale(self, uid, item_name):
        r = self._delete_json(
            f"/sales/{uid}/remove-item/{item_name}"
        )

        self._refresh_bg("items")
        return r

    def close_sale(self, uid):
        r = self._post(f"/sales/{uid}/close", {})

        self._refresh_bg("clients", "items")
        return r

    def delete_sale(self, uid):
        """
        Admin only.
        Deletes a sale log through DELETE /sales/{uid}.
        """
        r = self._delete_json(f"/sales/{uid}")

        self._refresh_bg("clients", "items")
        return r

    # ── Lockers ───────────────────────────────────────────────

    def get_locker_settings(self):
        c = self.cache.get("locker_settings", timeout=3)
        return c if c is not None else self._get("/lockers/settings")

    def update_locker_settings(self, data):
        r = self._patch("/lockers/settings", data)
        self._refresh_bg("locker_settings", "locker_availability")
        return r

    def get_locker_availability(self):
        c = self.cache.get("locker_availability", timeout=3)
        return c if c is not None else self._get("/lockers/available")

    def rent_locker(self, client_name):
        r = self._post(
            "/lockers/rent",
            {"client_name": client_name},
        )
        self._refresh_bg("locker_availability", "clients")
        return r

    def assign_locker(self, client_name, locker_number):
        r = self._post(
            "/lockers/assign",
            {
                "client_name": client_name,
                "locker_number": locker_number,
            },
        )
        self._refresh_bg("locker_availability", "clients")
        return r

    def unassign_locker(self, locker_number: int):
        r = self._delete(f"/lockers/unassign/{locker_number}")
        self._refresh_bg("locker_availability", "clients")
        return r

    def list_locker_rentals(self):
        return self._get("/lockers/rentals")

    def get_client_locker_rentals(self, name):
        return self._get(f"/lockers/rentals/{name}")

    # ── Reports ───────────────────────────────────────────────

    def get_daily_report(self, date_str):
        return self._get(f"/reports/daily/{date_str}")

    def get_daily_pdf(self, date_str) -> bytes:
        r = self._session.get(
            f"{BASE_URL}/reports/daily/{date_str}/pdf",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.content

    def get_monthly_report(self, year, month):
        return self._get(f"/reports/monthly/{year}/{month}")

    def get_monthly_pdf(self, year, month) -> bytes:
        r = self._session.get(
            f"{BASE_URL}/reports/monthly/{year}/{month}/pdf",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.content

    # ── HTTP helpers ──────────────────────────────────────────

    def _headers(self):
        if not self._token:
            raise APIError("Not logged in")

        return {
            "Authorization": f"Bearer {self._token}"
        }

    def _get(self, path):
        r = self._session.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.json()

    def _get_params(self, path, params):
        r = self._session.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.json()

    def _post(self, path, body):
        r = self._session.post(
            f"{BASE_URL}{path}",
            json=body,
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.json()

    def _patch(self, path, body):
        r = self._session.patch(
            f"{BASE_URL}{path}",
            json=body,
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.json()

    def _delete(self, path):
        r = self._session.delete(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)

    def _delete_json(self, path):
        r = self._session.delete(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.json()

    @staticmethod
    def _raise(r):
        if not r.ok:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text

            raise APIError(str(detail), r.status_code)


api = APIClient()