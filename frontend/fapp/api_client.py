"""
API client — single persistent requests.Session per login session.
Prevents connection exhaustion / memory leak from repeated calls.
"""
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    def __init__(self):
        self._token:        str | None = None
        self.account_name:  str | None = None
        self.account_type:  str | None = None
        self._session = requests.Session()

    @property
    def is_admin(self) -> bool:
        return self.account_type == "admin"

    def _reset_session(self):
        try:
            self._session.close()
        except Exception:
            pass
        self._session = requests.Session()

    # ── Auth ─────────────────────────────────────────────────

    def login(self, username: str, password: str) -> None:
        r = self._session.post(
            f"{BASE_URL}/auth/login",
            data={"username": username, "password": password})
        self._raise(r)
        body = r.json()
        self._token       = body["access_token"]
        self.account_name = username
        self.account_type = body["account_type"]

    def logout(self) -> None:
        self._token       = None
        self.account_name = None
        self.account_type = None
        self._reset_session()

    # ── Accounts ─────────────────────────────────────────────

    def list_accounts(self):
        return self._get("/accounts")

    def create_account(self, name, role, password):
        return self._post("/accounts", {
            "account_name": name,
            "account_type": role,
            "password":     password,
        })

    def update_account(self, name, role=None, password=None):
        body = {}
        if role:     body["account_type"] = role
        if password: body["password"]     = password
        return self._patch(f"/accounts/{name}", body)

    def delete_account(self, name):
        self._delete(f"/accounts/{name}")

    # ── Subscriptions ─────────────────────────────────────────

    def list_subscriptions(self):
        return self._get("/subscriptions")

    def create_subscription(self, data):
        return self._post("/subscriptions", data)

    def update_subscription(self, name, data):
        return self._patch(f"/subscriptions/{name}", data)

    def delete_subscription(self, name):
        self._delete(f"/subscriptions/{name}")

    # ── Clients ───────────────────────────────────────────────

    def list_clients(self):
        return self._get("/clients")

    def list_active_clients(self):
        return self._get("/clients/active")

    def get_client(self, name):
        return self._get(f"/clients/{name}")

    def get_client_subscriptions(self, name):
        return self._get(f"/clients/{name}/subscriptions")

    def create_client(self, data):
        return self._post("/clients", data)

    def re_enroll_client(self, name, subscription_name):
        return self._post(f"/clients/{name}/re-enroll",
                          {"subscription_name": subscription_name})

    def update_client(self, name, data):
        return self._patch(f"/clients/{name}", data)

    def delete_client(self, name):
        self._delete(f"/clients/{name}")

    def deduct_trainer(self, name):
        return self._post(f"/clients/{name}/deduct-trainer", {})

    def enroll_fingerprint(self, name):
        return self._post(f"/clients/{name}/enroll-fingerprint", {})

    # ── Attendance ────────────────────────────────────────────

    def list_attendance(self, client_name=None, date_from=None,
                        date_to=None, date_exact=None):
        params = {}
        if client_name: params["client_name"] = client_name
        if date_from:   params["date_from"]   = date_from
        if date_to:     params["date_to"]     = date_to
        if date_exact:  params["date_exact"]  = date_exact
        return self._get_params("/attendance", params)

    def get_client_attendance(self, name):
        return self._get(f"/attendance/client/{name}")

    def time_in(self, client_name):
        return self._post("/attendance/time-in",
                          {"client_name": client_name})

    def time_out(self, client_name):
        return self._post("/attendance/time-out",
                          {"client_name": client_name})

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
                timeout=(5, 35),   # read timeout > server-side 30 s
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
        return self._get("/items")

    def create_item(self, name, price, stock):
        return self._post("/items", {
            "item_name": name,
            "price":     price,
            "stock":     stock,
        })

    def update_item(self, name, price=None, stock=None):
        body = {}
        if price is not None: body["price"] = price
        if stock is not None: body["stock"] = stock
        return self._patch(f"/items/{name}", body)

    def delete_item(self, name):
        self._delete(f"/items/{name}")

    # ── Sales ─────────────────────────────────────────────────

    def list_open_sales(self):
        return self._get("/sales/open")

    def list_all_sales(self, client_name=None, item_name=None,
                       date_from=None, date_to=None,
                       date_exact=None, sale_status=None):
        params = {}
        if client_name:  params["client_name"]  = client_name
        if item_name:    params["item_name"]     = item_name
        if date_from:    params["date_from"]     = date_from
        if date_to:      params["date_to"]       = date_to
        if date_exact:   params["date_exact"]    = date_exact
        if sale_status:  params["sale_status"]   = sale_status
        return self._get_params("/sales", params)

    def get_client_sales(self, name):
        return self._get(f"/sales/client/{name}")

    def open_sale(self, client_name):
        return self._post("/sales/open", {"client_name": client_name})

    def add_item_to_sale(self, uid, item_name, qty):
        return self._post(f"/sales/{uid}/add-item",
                          {"item_name": item_name, "item_qty": qty})

    def remove_item_from_sale(self, uid, item_name):
        return self._delete_json(
            f"/sales/{uid}/remove-item/{item_name}")

    def close_sale(self, uid):
        return self._post(f"/sales/{uid}/close", {})

    # ── Lockers ───────────────────────────────────────────────

    def get_locker_settings(self):
        return self._get("/lockers/settings")

    def update_locker_settings(self, data):
        return self._patch("/lockers/settings", data)

    def get_locker_availability(self):
        return self._get("/lockers/available")

    def rent_locker(self, client_name):
        return self._post("/lockers/rent",
                          {"client_name": client_name})

    def assign_locker(self, client_name, locker_number):
        return self._post("/lockers/assign", {
            "client_name":   client_name,
            "locker_number": locker_number,
        })

    def unassign_locker(self, locker_number: int):
        return self._delete(f"/lockers/unassign/{locker_number}")

    def get_enroll_progress(self):
        return self._get("/clients/enroll-fingerprint/progress")

    def rename_subscription(self, name: str, new_name: str):
        return self._post(f"/subscriptions/{name}/rename",
                          {"new_name": new_name})

    def rename_item(self, item_name: str, new_name: str):
        return self._post(f"/items/{item_name}/rename",
                          {"new_name": new_name})

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
            headers=self._headers())
        self._raise(r)
        return r.content

    def get_monthly_report(self, year, month):
        return self._get(f"/reports/monthly/{year}/{month}")

    def get_monthly_pdf(self, year, month) -> bytes:
        r = self._session.get(
            f"{BASE_URL}/reports/monthly/{year}/{month}/pdf",
            headers=self._headers())
        self._raise(r)
        return r.content

    # ── HTTP helpers ──────────────────────────────────────────

    def _headers(self):
        if not self._token:
            raise APIError("Not logged in")
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path):
        r = self._session.get(f"{BASE_URL}{path}",
                              headers=self._headers())
        self._raise(r)
        return r.json()

    def _get_params(self, path, params):
        r = self._session.get(f"{BASE_URL}{path}",
                              headers=self._headers(),
                              params=params)
        self._raise(r)
        return r.json()

    def _post(self, path, body):
        r = self._session.post(f"{BASE_URL}{path}",
                               json=body,
                               headers=self._headers())
        self._raise(r)
        return r.json()

    def _patch(self, path, body):
        r = self._session.patch(f"{BASE_URL}{path}",
                                json=body,
                                headers=self._headers())
        self._raise(r)
        return r.json()

    def _delete(self, path):
        r = self._session.delete(f"{BASE_URL}{path}",
                                 headers=self._headers())
        self._raise(r)

    def _delete_json(self, path):
        r = self._session.delete(f"{BASE_URL}{path}",
                                 headers=self._headers())
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