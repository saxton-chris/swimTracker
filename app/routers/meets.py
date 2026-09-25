from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import crud
import schemas
from database import get_db

router = APIRouter(prefix="/meets", tags=["meets"])


@router.post("/", response_model=schemas.MeetOut)
def add_meet(meet: schemas.MeetCreate, db: Session = Depends(get_db)):
    return crud.create_meet(db, meet)


@router.get("/", response_model=list[schemas.MeetOut])
def list_meets(db: Session = Depends(get_db)):
    return crud.get_meets(db)


@router.patch("/{meet_id}", response_model=schemas.MeetOut)
def update_meet(meet_id: int, update: schemas.MeetUpdate, db: Session = Depends(get_db)):
    existing = crud.get_meet_by_id(db, meet_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")

    # Check the date range using post-update values (changed fields override stored ones)
    changes = update.model_dump(exclude_unset=True)
    try:
        schemas.check_meet_dates(changes.get("date", existing.date), changes.get("end_date", existing.end_date))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return crud.update_meet(db, meet_id, update)


@router.delete("/{meet_id}", status_code=204)
def delete_meet(meet_id: int, db: Session = Depends(get_db)):
    if not crud.delete_meet(db, meet_id):
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")
