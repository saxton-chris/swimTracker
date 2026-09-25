from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

router = APIRouter(prefix="/time_standards", tags=["time_standards"])

@router.post("/", response_model=schemas.TimeStandardOut)
def add_time_standard(time_standard: schemas.TimeStandardCreate, db: Session = Depends(get_db)):
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

@router.get("/", response_model=list[schemas.TimeStandardOut])
def list_time_standards(
    event_id: int | None = None,
    organization: str | None = None,
    age_group: str | None = None,
    gender: str | None = None,
    season: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_time_standards(
        db,
        event_id=event_id,
        organization=organization,
        age_group=age_group,
        gender=gender,
        season=season,
    )
