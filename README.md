# Attendance & Sales System
FastAPI backend + Tkinter desktop frontend

---

## Quick-Start (first time)

### Step 1 — Install Python
Make sure Python 3.11+ is installed: https://python.org/downloads

### Step 2 — Set up the backend

```bash
cd project/backend
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # keep defaults for local dev
uvicorn main:app --reload
```

Backend runs at http://localhost:8000  
Swagger docs at http://localhost:8000/docs  
Default login: **admin / admin123**

### Step 3 — Set up the frontend (new terminal)

```bash
cd project/frontend
pip install -r requirements.txt
python main.py
```

---

## Role Permissions

| Feature                  | Admin | Sales |
|--------------------------|:-----:|:-----:|
| Sidebar: Enroll Client   |       |  ✓   |
| Sidebar: Sales (open)    |       |  ✓   |
| Sidebar: Attendance Logs |  ✓   |       |
| Sidebar: Sales Logs (all)|  ✓   |       |
| Sidebar: Client List     |  ✓   |       |
| Sidebar: Item Catalogue  |  ✓   |       |
| Sidebar: Daily Reports   |  ✓   |       |
| Sidebar: Accounts        |  ✓   |       |
| Time-In / Time-Out       |  ✓   |  ✓   |
| Enroll new clients       |  ✓   |  ✓   |
| Re-enroll clients        |  ✓   |  ✓   |
| Edit / delete clients    |  ✓   |       |
| Create / close sales     |  ✓   |  ✓   |
| View open sales          |  ✓   |  ✓   |
| View full sales history  |  ✓   |       |
| Manage item catalogue    |  ✓   |       |
| View daily reports + PDF |  ✓   |       |
| Manage accounts          |  ✓   |       |

---

## Project Structure

```
project/
├── backend/
│   ├── main.py                        Entry point
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── core/
│       │   ├── config.py              Settings (reads .env)
│       │   ├── database.py            SQLAlchemy engine + seed + auto-report
│       │   ├── security.py            Bcrypt + JWT
│       │   └── report_generator.py    Daily PDF report builder
│       ├── models/                    SQLAlchemy ORM tables
│       ├── schemas/                   Pydantic request/response shapes
│       └── api/v1/endpoints/          FastAPI route handlers
└── frontend/
    ├── main.py                        Tkinter root + header + sidebar
    ├── requirements.txt
    └── app/
        ├── api_client.py              All HTTP calls
        └── views/
            ├── login_view.py
            ├── enroll_view.py         Sales: enroll + time-in/out
            ├── sales_open_view.py     Sales: open sales only
            ├── admin_attendance_view.py
            ├── admin_sales_view.py
            ├── clients_view.py
            ├── items_view.py
            ├── reports_view.py
            └── accounts_view.py
```
