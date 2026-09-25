from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

router = APIRouter(prefix="/meets", tags=["meets"])

@router.post("/", response_model=schemas.MeetOut)
def add_meet(meet: schemas.MeetCreate, db: Session = Depends(get_db)):
    return crud.create_meet(db, meet)

@router.get("/", response_model=list[schemas.MeetOut])
def list_meets(db: Session = Depends(get_db)):
    return crud.get_meets(db)

@router.patch("/{meet_id}", response_model=schemas.MeetOut)
def update_meet(meet_id: int, update: schemas.MeetUpdate, db: Session = Depends(get_db)):
    updated = crud.update_meet(db, meet_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")
    return updated
