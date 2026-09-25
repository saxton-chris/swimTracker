from fastapi import APIRouter, HTTPException

import crud
import schemas
from database import DbSession

router = APIRouter(prefix="/swim_times", tags=["swim_times"])


@router.post("/", response_model=schemas.SwimTimeOut)
def add_swim_time(swim_time: schemas.SwimTimeCreate, db: DbSession):
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
def list_swim_times(db: DbSession, meet_entry_id: int | None = None):
    return crud.get_swim_times(db, meet_entry_id=meet_entry_id)


@router.patch("/{swim_time_id}", response_model=schemas.SwimTimeOut)
def update_swim_time(swim_time_id: int, update: schemas.SwimTimeUpdate, db: DbSession):
    updated = crud.update_swim_time(db, swim_time_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Swim time {swim_time_id} not found")
    return updated


@router.delete("/{swim_time_id}", status_code=204)
def delete_swim_time(swim_time_id: int, db: DbSession):
    if not crud.delete_swim_time(db, swim_time_id):
        raise HTTPException(status_code=404, detail=f"Swim time {swim_time_id} not found")
