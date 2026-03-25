from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_any
from app.core.database import get_db
from app.models.client import Client
from app.schemas.client import ClientCreate, ClientRead, ClientReEnroll, ClientUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/", response_model=list[ClientRead])
def list_clients(_: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    return db.query(Client).all()


@router.get("/active", response_model=list[ClientRead])
def list_active_clients(_: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    """Return only clients currently timed in (client_status=True)."""
    return db.query(Client).filter(Client.client_status == True).all()


@router.get("/{client_name}", response_model=ClientRead)
def get_client(client_name: str, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.client_name == client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    if db.query(Client).filter(Client.client_name == payload.client_name).first():
        raise HTTPException(status_code=409, detail="Client already exists")
    client = Client(
        client_name=payload.client_name,
        client_duration=payload.client_duration,
        client_status=False,
        client_current_uid_log=0,
        client_budget=payload.client_budget,
        last_enrolled_at=datetime.now(timezone.utc),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.post("/{client_name}/re-enroll", response_model=ClientRead)
def re_enroll_client(
    client_name: str,
    payload: ClientReEnroll,
    _: TokenData = Depends(require_any),
    db: Session = Depends(get_db),
):
    """Update client duration and stamp last_enrolled_at. Accessible by both roles."""
    client = db.query(Client).filter(Client.client_name == client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.client_duration = payload.client_duration
    client.last_enrolled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(client)
    return client


@router.patch("/{client_name}", response_model=ClientRead)
def update_client(
    client_name: str,
    payload: ClientUpdate,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.client_name == client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if payload.client_duration is not None:
        client.client_duration = payload.client_duration
    if payload.client_status is not None:
        client.client_status = payload.client_status
    if payload.client_budget is not None:
        client.client_budget = payload.client_budget
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_name: str,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.client_name == client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
