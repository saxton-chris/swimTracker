from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

router = APIRouter(prefix="/swimmers", tags=["swimmers"])

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

@router.delete("/{swimmer_id}", status_code=204)
def delete_swimmer(swimmer_id: int, db: Session = Depends(get_db)):
    if not crud.delete_swimmer(db, swimmer_id):
        raise HTTPException(status_code=404, detail=f"Swimmer {swimmer_id} not found")
