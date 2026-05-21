# Attendance & Sales System v2

FastAPI + Firestore backend, Tkinter desktop frontend.

## Prerequisites

- Python 3.11+
- `firebase_credentials.json` (Firebase service account key)
- DigitalPersona One Touch SDK (optional — for fingerprint scanner)

## Setup

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Place firebase_credentials.json in backend/

uvicorn main:app --reload
```

```powershell
# Frontend (new terminal)
cd frontend
pip install requests
# If fingerprint scanner installed:
# pip install python-dpfj
python frontend_main.py
```

## Production Build (single exe)

```powershell
# From project2 root
pip install pyinstaller
python -m PyInstaller launch.spec
```

Place `firebase_credentials.json` next to `dist/AttendanceSalesSystem.exe`.

## Default credentials

`admin` / `admin123`  (created automatically on first startup)

## Sidebar navigation

| Tab | Admin | Sales |
|---|:---:|:---:|
| Enroll Client | | ✓ |
| Sales (open) | | ✓ |
| Attendance Logs | ✓ | |
| Sales Logs | ✓ | |
| Client List | ✓ | |
| Item Catalogue | ✓ | |
| Subscription Plans | ✓ | |
| Locker Management | ✓ | |
| Reports | ✓ | |
| Settings | ✓ | |
| Accounts | ✓ | |
