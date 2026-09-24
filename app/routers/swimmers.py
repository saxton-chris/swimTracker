from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
import crud, schemas

router = APIRouter(prefix="/swimmers", tags=["swimmers"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.SwimmerOut)
def add_swimmer(swimmer: schemas.SwimmerCreate, db: Session = Depends(get_db)):
    return crud.create_swimmer(db, swimmer)

@router.get("/", response_model=list[schemas.SwimmerOut])
def list_swimmers(db: Session = Depends(get_db)):
    return crud.get_swimmers(db)

@router.patch("/{swimmer_id}", response_model=schemas.SwimmerOut)
def update_swimmer(swimmer_id: int, update: schemas.SwimmerUpdate, db: Session = Depends(get_db)):
    updated = crud.update_swimmer(db, swimmer_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Swimmer {swimmer_id} not found")
    return updated
