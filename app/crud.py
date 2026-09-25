from sqlalchemy import select
from sqlalchemy.orm import Session

import schemas
from models import Event, Meet, MeetEntry, Swimmer, SwimTime, TimeStandard


def _create(db: Session, obj, *, commit: bool = True):
    """Add a new row. commit=False leaves it pending so bulk imports can commit once at the end."""
    db.add(obj)
    if commit:
        db.commit()
        db.refresh(obj)
    return obj


def _apply_update(db: Session, db_obj, update):
    """Copy only the fields the client actually sent onto db_obj and commit."""
    if db_obj is None:
        return None
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def _delete(db: Session, db_obj):
    """Delete db_obj (ORM cascades remove dependents). Returns False if it didn't exist."""
    if db_obj is None:
        return False
    db.delete(db_obj)
    db.commit()
    return True


# --- swimmers ----------------------------------------------------------------


def create_swimmer(db: Session, swimmer: schemas.SwimmerCreate):
    return _create(db, Swimmer(**swimmer.model_dump()))


def get_swimmers(db: Session):
    return db.scalars(select(Swimmer)).all()


def get_swimmer_by_id(db: Session, swimmer_id: int):
    return db.get(Swimmer, swimmer_id)


def update_swimmer(db: Session, swimmer_id: int, update: schemas.SwimmerUpdate):
    return _apply_update(db, db.get(Swimmer, swimmer_id), update)


def delete_swimmer(db: Session, swimmer_id: int):
    return _delete(db, db.get(Swimmer, swimmer_id))


# --- meets -------------------------------------------------------------------


def create_meet(db: Session, meet: schemas.MeetCreate):
    return _create(db, Meet(**meet.model_dump()))


def get_meets(db: Session):
    return db.scalars(select(Meet)).all()


def get_meet_by_id(db: Session, meet_id: int):
    return db.get(Meet, meet_id)


def update_meet(db: Session, meet_id: int, update: schemas.MeetUpdate):
    return _apply_update(db, db.get(Meet, meet_id), update)


def delete_meet(db: Session, meet_id: int):
    return _delete(db, db.get(Meet, meet_id))


# --- events ------------------------------------------------------------------


def create_event(db: Session, event: schemas.EventCreate):
    return _create(db, Event(**event.model_dump()))


def get_events(db: Session):
    return db.scalars(select(Event)).all()


def get_event(db: Session, distance: int, stroke, course):
    return db.scalars(
        select(Event).where(Event.distance == distance, Event.stroke == stroke, Event.course == course)
    ).first()


def get_event_by_id(db: Session, event_id: int):
    return db.get(Event, event_id)


# --- meet entries ------------------------------------------------------------


def create_meet_entry(db: Session, meet_entry: schemas.MeetEntryCreate):
    return _create(db, MeetEntry(**meet_entry.model_dump()))


def get_meet_entry(db: Session, meet_id: int, swimmer_id: int, event_id: int):
    return db.scalars(
        select(MeetEntry).where(
            MeetEntry.meet_id == meet_id,
            MeetEntry.swimmer_id == swimmer_id,
            MeetEntry.event_id == event_id,
        )
    ).first()


def get_meet_entries(db: Session, meet_id: int | None = None, swimmer_id: int | None = None):
    stmt = select(MeetEntry)
    if meet_id is not None:
        stmt = stmt.where(MeetEntry.meet_id == meet_id)
    if swimmer_id is not None:
        stmt = stmt.where(MeetEntry.swimmer_id == swimmer_id)
    return db.scalars(stmt).all()


def get_meet_entry_by_id(db: Session, meet_entry_id: int):
    return db.get(MeetEntry, meet_entry_id)


def update_meet_entry(db: Session, meet_entry_id: int, update: schemas.MeetEntryUpdate):
    return _apply_update(db, get_meet_entry_by_id(db, meet_entry_id), update)


def delete_meet_entry(db: Session, meet_entry_id: int):
    return _delete(db, get_meet_entry_by_id(db, meet_entry_id))


# --- time standards ----------------------------------------------------------


def create_time_standard(db: Session, time_standard: schemas.TimeStandardCreate, *, commit: bool = True):
    return _create(db, TimeStandard(**time_standard.model_dump()), commit=commit)


def get_time_standard(
    db: Session,
    event_id: int,
    organization: str,
    age_group: str,
    gender: str,
    standard_name: str,
    season: str,
):
    return db.scalars(
        select(TimeStandard).where(
            TimeStandard.event_id == event_id,
            TimeStandard.organization == organization,
            TimeStandard.age_group == age_group,
            TimeStandard.gender == gender,
            TimeStandard.standard_name == standard_name,
            TimeStandard.season == season,
        )
    ).first()


def get_time_standard_sets(db: Session):
    """Each distinct (organization, season) that has standards loaded, e.g. ("USA Swimming", "2024-2028")."""
    return db.execute(
        select(TimeStandard.organization, TimeStandard.season)
        .distinct()
        .order_by(TimeStandard.organization, TimeStandard.season)
    ).all()


def get_time_standards(
    db: Session,
    event_id: int | None = None,
    organization: str | None = None,
    age_group: str | None = None,
    gender: str | None = None,
    season: str | None = None,
):
    stmt = select(TimeStandard)
    if event_id is not None:
        stmt = stmt.where(TimeStandard.event_id == event_id)
    if organization is not None:
        stmt = stmt.where(TimeStandard.organization == organization)
    if age_group is not None:
        stmt = stmt.where(TimeStandard.age_group == age_group)
    if gender is not None:
        stmt = stmt.where(TimeStandard.gender == gender)
    if season is not None:
        stmt = stmt.where(TimeStandard.season == season)
    return db.scalars(stmt).all()


# --- swim times --------------------------------------------------------------


def create_swim_time(db: Session, swim_time: schemas.SwimTimeCreate):
    return _create(db, SwimTime(**swim_time.model_dump()))


def get_swim_time_by_id(db: Session, swim_time_id: int):
    return db.get(SwimTime, swim_time_id)


def get_swim_time_by_meet_entry(db: Session, meet_entry_id: int):
    return db.scalars(select(SwimTime).where(SwimTime.meet_entry_id == meet_entry_id)).first()


def get_swim_times(db: Session, meet_entry_id: int | None = None):
    stmt = select(SwimTime)
    if meet_entry_id is not None:
        stmt = stmt.where(SwimTime.meet_entry_id == meet_entry_id)
    return db.scalars(stmt).all()


def update_swim_time(db: Session, swim_time_id: int, update: schemas.SwimTimeUpdate):
    return _apply_update(db, get_swim_time_by_id(db, swim_time_id), update)


def delete_swim_time(db: Session, swim_time_id: int):
    return _delete(db, get_swim_time_by_id(db, swim_time_id))
