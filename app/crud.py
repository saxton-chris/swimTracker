from sqlalchemy.orm import Session

import schemas
from models import Event, Meet, MeetEntry, Swimmer, SwimTime, TimeStandard


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


def create_swimmer(db: Session, swimmer: schemas.SwimmerCreate):
    db_swimmer = Swimmer(**swimmer.model_dump())
    db.add(db_swimmer)
    db.commit()
    db.refresh(db_swimmer)
    return db_swimmer


def get_swimmers(db: Session):
    return db.query(Swimmer).all()


def update_swimmer(db: Session, swimmer_id: int, update: schemas.SwimmerUpdate):
    return _apply_update(db, db.get(Swimmer, swimmer_id), update)


def delete_swimmer(db: Session, swimmer_id: int):
    return _delete(db, db.get(Swimmer, swimmer_id))


def create_meet(db: Session, meet: schemas.MeetCreate):
    db_meet = Meet(**meet.model_dump())
    db.add(db_meet)
    db.commit()
    db.refresh(db_meet)
    return db_meet


def get_meets(db: Session):
    return db.query(Meet).all()


def update_meet(db: Session, meet_id: int, update: schemas.MeetUpdate):
    return _apply_update(db, db.get(Meet, meet_id), update)


def delete_meet(db: Session, meet_id: int):
    return _delete(db, db.get(Meet, meet_id))


def create_event(db: Session, event: schemas.EventCreate):
    db_event = Event(**event.model_dump())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


def get_events(db: Session):
    return db.query(Event).all()


def get_event(db: Session, distance: int, stroke, course):
    return (
        db.query(Event)
        .filter(Event.distance == distance, Event.stroke == stroke, Event.course == course)
        .first()
    )


def get_swimmer_by_id(db: Session, swimmer_id: int):
    return db.get(Swimmer, swimmer_id)


def get_meet_by_id(db: Session, meet_id: int):
    return db.get(Meet, meet_id)


def get_event_by_id(db: Session, event_id: int):
    return db.get(Event, event_id)


def get_meet_entry(db: Session, meet_id: int, swimmer_id: int, event_id: int):
    return (
        db.query(MeetEntry)
        .filter(
            MeetEntry.meet_id == meet_id,
            MeetEntry.swimmer_id == swimmer_id,
            MeetEntry.event_id == event_id,
        )
        .first()
    )


def create_meet_entry(db: Session, meet_entry: schemas.MeetEntryCreate):
    db_meet_entry = MeetEntry(**meet_entry.model_dump())
    db.add(db_meet_entry)
    db.commit()
    db.refresh(db_meet_entry)
    return db_meet_entry


def get_meet_entries(db: Session, meet_id: int | None = None, swimmer_id: int | None = None):
    query = db.query(MeetEntry)
    if meet_id is not None:
        query = query.filter(MeetEntry.meet_id == meet_id)
    if swimmer_id is not None:
        query = query.filter(MeetEntry.swimmer_id == swimmer_id)
    return query.all()


def get_meet_entry_by_id(db: Session, meet_entry_id: int):
    return db.get(MeetEntry, meet_entry_id)


def update_meet_entry(db: Session, meet_entry_id: int, update: schemas.MeetEntryUpdate):
    return _apply_update(db, get_meet_entry_by_id(db, meet_entry_id), update)


def delete_meet_entry(db: Session, meet_entry_id: int):
    return _delete(db, get_meet_entry_by_id(db, meet_entry_id))


def get_time_standard(
    db: Session, event_id: int, organization: str, age_group: str, gender: str,
    standard_name: str, season: str,
):
    return (
        db.query(TimeStandard)
        .filter(
            TimeStandard.event_id == event_id,
            TimeStandard.organization == organization,
            TimeStandard.age_group == age_group,
            TimeStandard.gender == gender,
            TimeStandard.standard_name == standard_name,
            TimeStandard.season == season,
        )
        .first()
    )


def create_time_standard(db: Session, time_standard: schemas.TimeStandardCreate):
    db_time_standard = TimeStandard(**time_standard.model_dump())
    db.add(db_time_standard)
    db.commit()
    db.refresh(db_time_standard)
    return db_time_standard


def get_time_standards(
    db: Session,
    event_id: int | None = None,
    organization: str | None = None,
    age_group: str | None = None,
    gender: str | None = None,
    season: str | None = None,
):
    query = db.query(TimeStandard)
    if event_id is not None:
        query = query.filter(TimeStandard.event_id == event_id)
    if organization is not None:
        query = query.filter(TimeStandard.organization == organization)
    if age_group is not None:
        query = query.filter(TimeStandard.age_group == age_group)
    if gender is not None:
        query = query.filter(TimeStandard.gender == gender)
    if season is not None:
        query = query.filter(TimeStandard.season == season)
    return query.all()


def create_swim_time(db: Session, swim_time: schemas.SwimTimeCreate):
    db_swim_time = SwimTime(**swim_time.model_dump())
    db.add(db_swim_time)
    db.commit()
    db.refresh(db_swim_time)
    return db_swim_time


def get_swim_time_by_id(db: Session, swim_time_id: int):
    return db.get(SwimTime, swim_time_id)


def get_swim_time_by_meet_entry(db: Session, meet_entry_id: int):
    return db.query(SwimTime).filter(SwimTime.meet_entry_id == meet_entry_id).first()


def get_swim_times(db: Session, meet_entry_id: int | None = None):
    query = db.query(SwimTime)
    if meet_entry_id is not None:
        query = query.filter(SwimTime.meet_entry_id == meet_entry_id)
    return query.all()


def update_swim_time(db: Session, swim_time_id: int, update: schemas.SwimTimeUpdate):
    return _apply_update(db, get_swim_time_by_id(db, swim_time_id), update)


def delete_swim_time(db: Session, swim_time_id: int):
    return _delete(db, get_swim_time_by_id(db, swim_time_id))
