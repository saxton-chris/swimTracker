from sqlalchemy.orm import Session
from models import Swimmer, Meet, Event
import schemas

def create_swimmer(db: Session, swimmer: schemas.SwimmerCreate):
    db_swimmer = Swimmer(**swimmer.model_dump())
    db.add(db_swimmer)
    db.commit()
    db.refresh(db_swimmer)
    return db_swimmer

def get_swimmers(db: Session):
    return db.query(Swimmer).all()

def create_meet(db: Session, meet: schemas.MeetCreate):
    db_meet = Meet(**meet.model_dump())
    db.add(db_meet)
    db.commit()
    db.refresh(db_meet)
    return db_meet

def get_meets(db: Session):
    return db.query(Meet).all()

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
