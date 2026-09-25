from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

router = APIRouter(prefix="/swim_times", tags=["swim_times"])

@router.post("/", response_model=schemas.SwimTimeOut)
def add_swim_time(swim_time: schemas.SwimTimeCreate, db: Session = Depends(get_db)):
    if not crud.get_meet_entry_by_id(db, swim_time.meet_entry_id):
        raise HTTPException(status_code=404, detail=f"Meet entry {swim_time.meet_entry_id} not found")

    existing = crud.get_swim_time_by_meet_entry(db, swim_time.meet_entry_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A time already exists for meet entry {swim_time.meet_entry_id} "
                   f"- use PATCH /swim_times/{existing.id} to update it",
        )

    return crud.create_swim_time(db, swim_time)

@router.get("/", response_model=list[schemas.SwimTimeOut])
def list_swim_times(meet_entry_id: int | None = None, db: Session = Depends(get_db)):
    return crud.get_swim_times(db, meet_entry_id=meet_entry_id)

@router.patch("/{swim_time_id}", response_model=schemas.SwimTimeOut)
def update_swim_time(swim_time_id: int, update: schemas.SwimTimeUpdate, db: Session = Depends(get_db)):
    updated = crud.update_swim_time(db, swim_time_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Swim time {swim_time_id} not found")
    return updated
