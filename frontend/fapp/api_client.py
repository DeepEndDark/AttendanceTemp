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
import time
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"

# connect timeout, read timeout
DEFAULT_TIMEOUT = (5, 30)


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class NetworkError(APIError):
    """
    Raised when the backend process is unreachable at the network level
    (connection refused, DNS failure, timeout).  Distinct from APIError
    so callers can show "No connection" instead of a generic server error.
    """
    def __init__(self, message: str = "Cannot reach server."):
        super().__init__(message, status_code=0)


class DataCache:
    """
    Thread-safe key-value cache with TTL for Firestore collection data.
    Keys map to the last fetched result. A None value means not yet loaded.
    TTL defaults to 300s (5 minutes) — entries auto-expire silently.
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

    TTL = 300.0   # seconds before a cached entry is considered stale

    def __init__(self):
        self._data:  dict = {}
        self._times: dict = {}   # key -> timestamp of last set()
        self._locks: dict = {k: threading.Lock() for k in self.KEYS}
        self._ready: dict = {k: threading.Event() for k in self.KEYS}

    def set(self, key: str, value) -> None:
        with self._locks.get(key, threading.Lock()):
            self._data[key]  = value
            self._times[key] = time.monotonic()
            ev = self._ready.get(key)
            if ev:
                ev.set()

    def get(self, key: str, timeout: float = 0.0):
        """
        Return cached value if still within TTL.
        If not yet loaded and timeout > 0, wait up to timeout seconds.
        Returns None if unavailable or expired (triggers a fresh fetch).
        """
        ev = self._ready.get(key)

        if ev and not ev.is_set() and timeout > 0:
            ev.wait(timeout=timeout)

        # Read data and timestamp atomically under the lock
        with self._locks.get(key, threading.Lock()):
            ts = self._times.get(key)
            if ts is not None and (time.monotonic() - ts) > self.TTL:
                # Expired — clear under same lock
                self._data.pop(key, None)
                self._times.pop(key, None)
                if ev:
                    ev.clear()
                return None
            return self._data.get(key)

    def invalidate(self, *keys: str) -> None:
        for key in keys:
            with self._locks.get(key, threading.Lock()):
                self._data.pop(key, None)
                self._times.pop(key, None)
                ev = self._ready.get(key)
                if ev:
                    ev.clear()

    def clear(self) -> None:
        for key in self.KEYS:
            with self._locks.get(key, threading.Lock()):
                self._data.pop(key, None)
                self._times.pop(key, None)
                ev = self._ready.get(key)
                if ev:
                    ev.clear()

    def is_ready(self, key: str) -> bool:
        ev = self._ready.get(key)
        ts = self._times.get(key)
        if ts is not None and (time.monotonic() - ts) > self.TTL:
            return False
        return bool(ev and ev.is_set())


class APIClient:
    """Thin wrapper around requests.Session for the backend.

    Register a 401 handler via APIClient.set_unauthorized_handler(fn) after
    login. When any request returns 401 (expired/invalid token) the handler
    is called on the Tkinter main thread so it can redirect to login.
    """

    _on_unauthorized = None   # set by frontend_main after login
    _on_network_error = None  # set by frontend_main after login

    @classmethod
    def set_unauthorized_handler(cls, fn):
        cls._on_unauthorized = fn

    @classmethod
    def clear_unauthorized_handler(cls):
        cls._on_unauthorized = None

    @classmethod
    def set_network_error_handler(cls, fn):
        """fn(message: str) is called on the Tkinter main thread whenever
        a request exhausts its retries due to a network-level failure."""
        cls._on_network_error = fn

    @classmethod
    def clear_network_error_handler(cls):
        cls._on_network_error = None

    @classmethod
    def _fire_network_error(cls, message: str):
        if cls._on_network_error:
            try:
                cls._on_network_error(message)
            except Exception:
                pass

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
            except NetworkError as exc:
                # Surface this to the UI instead of silently hiding it —
                # an empty list looks identical to "no data" otherwise.
                self._fire_network_error(str(exc))
                self.cache.set(
                    key,
                    [] if key not in (
                        "locker_availability",
                        "locker_settings",
                    ) else {}
                )
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

    def ping(self) -> tuple[bool, str]:
        """
        Returns (reachable, firebase_status).
        firebase_status is one of: "ok", "credentials_missing", "error",
        "unknown" — "unknown" is also used when the backend is unreachable.
        Used by the login page poller; does NOT require authentication.
        """
        try:
            r = self._session.get(
                f"{BASE_URL.rsplit('/api', 1)[0]}/health",
                timeout=(3, 5),
            )
            try:
                fb = r.json().get("firebase", "unknown")
            except Exception:
                fb = "unknown"
            return True, fb
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ):
            return False, "unknown"

    def login(self, username: str, password: str) -> None:
        try:
            r = self._session.post(
                f"{BASE_URL}/auth/login",
                data={
                    "username": username,
                    "password": password,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            raise NetworkError("Cannot reach server. Check that the backend is running.") from exc

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

    def local_admin_login(self, username: str, password: str) -> None:
        """
        Bootstrap login used only to unlock the Firebase setup panel when
        Firestore is unreachable.  Does not trigger prefetch — there is no
        normal session to start, just a short-lived token for one action.
        """
        try:
            r = self._session.post(
                f"{BASE_URL}/auth/local-login",
                data={"username": username, "password": password},
                timeout=DEFAULT_TIMEOUT,
            )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            raise NetworkError("Cannot reach server. Check that the backend is running.") from exc

        self._raise(r)
        body = r.json()
        self._local_admin_token = body["access_token"]

    def apply_firebase_config(self, json_path: str) -> dict:
        """
        Uploads a Firebase service-account JSON file using the local-admin
        token obtained from local_admin_login().  Raises APIError with the
        backend's detail message on validation or connection failure.
        """
        if not getattr(self, "_local_admin_token", None):
            raise APIError("Not authenticated as local admin.")

        try:
            with open(json_path, "rb") as f:
                r = self._session.post(
                    f"{BASE_URL}/admin/apply-firebase-config",
                    files={"file": ("firebase_credentials.json", f, "application/json")},
                    headers={"Authorization": f"Bearer {self._local_admin_token}"},
                    timeout=(5, 20),
                )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            raise NetworkError("Cannot reach server. Check that the backend is running.") from exc

        self._raise(r)
        return r.json()

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

    def delete_attendance(self, log_uid: int):
        r = self._delete(f"/attendance/{log_uid}")
        self._refresh_bg("clients")
        return r

    def finger_touch(self):
        """
        Blocks up to ~32 s waiting for a finger to be physically placed.
        Returns (touched: bool, scanner_available: bool).
        Raises NetworkError if the backend is unreachable.
        """
        try:
            r = self._session.post(
                f"{BASE_URL}/attendance/finger-touch",
                json={},
                headers=self._headers(),
                timeout=(5, 35),  # read timeout > server-side 30 s
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("touched", False), data.get("scanner_available", True)
            return False, False
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            raise NetworkError() from exc
        except Exception:
            return False, False

    def fingerprint_scan(self):
        """
        Blocks up to ~10 s for next finger scan result.
        Returns display event dict or None on error.
        Read timeout must exceed scanner's 7 s capture window.
        Raises NetworkError if the backend is unreachable.
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
            return None
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            raise NetworkError() from exc
        except Exception:
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

    # ── Reports ───────────────────────────────────────────────

    def get_daily_report(self, date_str):
        return self._get(f"/reports/daily/{date_str}")

    def get_daily_pdf(self, date_str, plan: str | None = None) -> bytes:
        params = {"plan": plan} if plan else None
        r = self._session.get(
            f"{BASE_URL}/reports/daily/{date_str}/pdf",
            headers=self._headers(),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.content

    def get_monthly_report(self, year, month):
        return self._get(f"/reports/monthly/{year}/{month}")

    def get_monthly_pdf(self, year, month, plan: str | None = None) -> bytes:
        params = {"plan": plan} if plan else None
        r = self._session.get(
            f"{BASE_URL}/reports/monthly/{year}/{month}/pdf",
            headers=self._headers(),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise(r)
        return r.content

    def get_custom_report(self, start_str: str, end_str: str):
        return self._get(f"/reports/custom/{start_str}/{end_str}")

    def get_custom_pdf(self, start_str: str, end_str: str,
                       plan: str | None = None) -> bytes:
        params = {"plan": plan} if plan else None
        r = self._session.get(
            f"{BASE_URL}/reports/custom/{start_str}/{end_str}/pdf",
            headers=self._headers(),
            params=params,
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

    def _request(self, fn, retries: int = 3, backoff: float = 1.5):
        """
        Calls fn() (a lambda making one requests call) with retry on
        transient network failures. Raises NetworkError after all retries
        are exhausted; re-raises APIError (HTTP 4xx/5xx) immediately
        without retrying, since those are not network issues.
        """
        for attempt in range(retries):
            try:
                return fn()
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ):
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                continue

        err = NetworkError(
            f"Cannot reach server after {retries} attempts. "
            "Check that the backend is running."
        )
        self._fire_network_error(str(err))
        raise err

    def _get(self, path):
        r = self._request(lambda: self._session.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        return r.json()

    def _get_params(self, path, params):
        r = self._request(lambda: self._session.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        return r.json()

    def _post(self, path, body):
        r = self._request(lambda: self._session.post(
            f"{BASE_URL}{path}",
            json=body,
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        return r.json()

    def _patch(self, path, body):
        r = self._request(lambda: self._session.patch(
            f"{BASE_URL}{path}",
            json=body,
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        return r.json()

    def _delete(self, path):
        r = self._request(lambda: self._session.delete(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        try:
            return r.json()
        except Exception:
            return {}

    def _delete_json(self, path):
        r = self._request(lambda: self._session.delete(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        ))
        self._raise(r)
        return r.json()

    @staticmethod
    def _raise(r):
        if not r.ok:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text

            exc = APIError(str(detail), r.status_code)

            if r.status_code == 401 and APIClient._on_unauthorized:
                try:
                    APIClient._on_unauthorized()
                except Exception:
                    pass

            raise exc


api = APIClient()