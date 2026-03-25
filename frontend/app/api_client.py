import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    def __init__(self):
        self._token: str | None = None
        self.account_name: str | None = None
        self.account_type: str | None = None

    # ── Auth ─────────────────────────────────────────────────

    def login(self, username: str, password: str) -> None:
        r = requests.post(f"{BASE_URL}/auth/login", data={"username": username, "password": password})
        self._raise(r)
        body = r.json()
        self._token = body["access_token"]
        self.account_name = username
        self.account_type = body["account_type"]

    def logout(self) -> None:
        self._token = None
        self.account_name = None
        self.account_type = None

    @property
    def is_admin(self) -> bool:
        return self.account_type == "admin"

    # ── Accounts ─────────────────────────────────────────────

    def list_accounts(self) -> list[dict]:
        return self._get("/accounts")

    def create_account(self, name: str, role: str, password: str) -> dict:
        return self._post("/accounts", {"account_name": name, "account_type": role, "password": password})

    def update_account(self, name: str, role: str | None = None, password: str | None = None) -> dict:
        body = {}
        if role:
            body["account_type"] = role
        if password:
            body["password"] = password
        return self._patch(f"/accounts/{name}", body)

    def delete_account(self, name: str) -> None:
        self._delete(f"/accounts/{name}")

    # ── Clients ──────────────────────────────────────────────

    def list_clients(self) -> list[dict]:
        return self._get("/clients")

    def list_active_clients(self) -> list[dict]:
        return self._get("/clients/active")

    def get_client(self, name: str) -> dict:
        return self._get(f"/clients/{name}")

    def create_client(self, name: str, duration: str, budget: float) -> dict:
        return self._post("/clients", {"client_name": name, "client_duration": duration, "client_budget": budget})

    def re_enroll_client(self, name: str, duration: str) -> dict:
        return self._post(f"/clients/{name}/re-enroll", {"client_duration": duration})

    def update_client(self, name: str, **kwargs) -> dict:
        return self._patch(f"/clients/{name}", kwargs)

    def delete_client(self, name: str) -> None:
        self._delete(f"/clients/{name}")

    # ── Attendance ───────────────────────────────────────────

    def list_attendance(self) -> list[dict]:
        return self._get("/attendance")

    def get_attendance_by_date(self, date_str: str) -> list[dict]:
        return self._get(f"/attendance/date/{date_str}")

    def time_in(self, client_name: str) -> dict:
        return self._post("/attendance/time-in", {"client_name": client_name})

    def time_out(self, client_name: str) -> dict:
        return self._post("/attendance/time-out", {"client_name": client_name})

    # ── Items ────────────────────────────────────────────────

    def list_items(self) -> list[dict]:
        return self._get("/items")

    def create_item(self, name: str, price: float, stock: int) -> dict:
        return self._post("/items", {"item_name": name, "price": price, "stock": stock})

    def update_item(self, name: str, price: float | None = None, stock: int | None = None) -> dict:
        body = {}
        if price is not None:
            body["price"] = price
        if stock is not None:
            body["stock"] = stock
        return self._patch(f"/items/{name}", body)

    def delete_item(self, name: str) -> None:
        self._delete(f"/items/{name}")

    # ── Sales ────────────────────────────────────────────────

    def list_all_sales(self) -> list[dict]:
        return self._get("/sales")

    def list_open_sales(self) -> list[dict]:
        return self._get("/sales/open")

    def get_sales_by_date(self, date_str: str) -> list[dict]:
        return self._get(f"/sales/date/{date_str}")

    def open_sale(self, client_name: str) -> dict:
        return self._post("/sales/open", {"client_name": client_name})

    def add_item_to_sale(self, uid: int, item_name: str, item_qty: int) -> dict:
        return self._post(f"/sales/{uid}/add-item", {"item_name": item_name, "item_qty": item_qty})

    def remove_item_from_sale(self, uid: int, item_name: str) -> dict:
        return self._delete_json(f"/sales/{uid}/remove-item/{item_name}")

    def close_sale(self, uid: int) -> dict:
        return self._post(f"/sales/{uid}/close", {})

    # ── Reports ──────────────────────────────────────────────

    def list_report_dates(self) -> list[str]:
        return self._get("/reports")

    def get_report(self, date_str: str) -> dict:
        return self._get(f"/reports/{date_str}")

    def get_report_pdf(self, date_str: str) -> bytes:
        r = requests.get(f"{BASE_URL}/reports/{date_str}/pdf", headers=self._headers())
        self._raise(r)
        return r.content

    # ── HTTP helpers ─────────────────────────────────────────

    def _headers(self) -> dict:
        if not self._token:
            raise APIError("Not logged in")
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str):
        r = requests.get(f"{BASE_URL}{path}", headers=self._headers())
        self._raise(r)
        return r.json()

    def _post(self, path: str, body: dict):
        r = requests.post(f"{BASE_URL}{path}", json=body, headers=self._headers())
        self._raise(r)
        return r.json()

    def _patch(self, path: str, body: dict):
        r = requests.patch(f"{BASE_URL}{path}", json=body, headers=self._headers())
        self._raise(r)
        return r.json()

    def _delete(self, path: str) -> None:
        r = requests.delete(f"{BASE_URL}{path}", headers=self._headers())
        self._raise(r)

    def _delete_json(self, path: str):
        r = requests.delete(f"{BASE_URL}{path}", headers=self._headers())
        self._raise(r)
        return r.json()

    @staticmethod
    def _raise(r: requests.Response) -> None:
        if not r.ok:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise APIError(str(detail), r.status_code)


api = APIClient()
