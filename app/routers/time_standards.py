from fastapi import APIRouter, HTTPException

import crud
import schemas
from database import DbSession

router = APIRouter(prefix="/time_standards", tags=["time_standards"])


@router.post("/", response_model=schemas.TimeStandardOut)
def add_time_standard(time_standard: schemas.TimeStandardCreate, db: DbSession):
    if not crud.get_event_by_id(db, time_standard.event_id):
        raise HTTPException(status_code=404, detail=f"Event {time_standard.event_id} not found")

    existing = crud.get_time_standard(
        db,
        time_standard.event_id,
        time_standard.organization,
        time_standard.age_group,
        time_standard.gender,
        time_standard.standard_name,
        time_standard.season,
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A time standard already exists for this event/organization/age group/gender/standard/season",
        )

    return crud.create_time_standard(db, time_standard)


@router.get("/sets", response_model=list[schemas.TimeStandardSetOut])
def list_time_standard_sets(db: DbSession):
    """The organization/season combinations that have standards loaded."""
    return crud.get_time_standard_sets(db)


@router.get("/", response_model=list[schemas.TimeStandardOut])
def list_time_standards(
    db: DbSession,
    event_id: int | None = None,
    organization: str | None = None,
    age_group: str | None = None,
    gender: schemas.Gender | None = None,  # "F"/"M": anything else is a 422, not a silently empty list
    season: str | None = None,
):
    return crud.get_time_standards(
        db,
        event_id=event_id,
        organization=organization,
        age_group=age_group,
        gender=gender,
        season=season,
    )
