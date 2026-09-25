from fastapi import APIRouter, HTTPException

import crud
import schemas
from database import DbSession

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/", response_model=schemas.EventOut)
def add_event(event: schemas.EventCreate, db: DbSession):
    existing = crud.get_event(db, event.distance, event.stroke, event.course)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Event '{event.distance} {event.stroke.value} {event.course.value}' already exists",
        )
    return crud.create_event(db, event)


@router.get("/", response_model=list[schemas.EventOut])
def list_events(db: DbSession):
    return crud.get_events(db)
