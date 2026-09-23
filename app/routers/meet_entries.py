from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
import crud, schemas

router = APIRouter(prefix="/meet_entries", tags=["meet_entries"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.MeetEntryOut)
def add_meet_entry(meet_entry: schemas.MeetEntryCreate, db: Session = Depends(get_db)):
    if not crud.get_swimmer_by_id(db, meet_entry.swimmer_id):
        raise HTTPException(status_code=404, detail=f"Swimmer {meet_entry.swimmer_id} not found")
    if not crud.get_meet_by_id(db, meet_entry.meet_id):
        raise HTTPException(status_code=404, detail=f"Meet {meet_entry.meet_id} not found")
    if not crud.get_event_by_id(db, meet_entry.event_id):
        raise HTTPException(status_code=404, detail=f"Event {meet_entry.event_id} not found")

    existing = crud.get_meet_entry(db, meet_entry.meet_id, meet_entry.swimmer_id, meet_entry.event_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="This swimmer is already entered in this event at this meet",
        )

    return crud.create_meet_entry(db, meet_entry)

@router.get("/", response_model=list[schemas.MeetEntryOut])
def list_meet_entries(
    meet_id: int | None = None,
    swimmer_id: int | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_meet_entries(db, meet_id=meet_id, swimmer_id=swimmer_id)
