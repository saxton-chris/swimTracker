from sqlalchemy.orm import Session
from models import Swimmer, Meet
import schemas

def create_swimmer(db: Session, swimmer: schemas.SwimmerCreate):
    db_swimmer = Swimmer(**swimmer.model_dump())
    db.add(db_swimmer)
    db.commit()
    db.refresh(db_swimmer)
    return db_swimmer

def get_swimmers(db: Session):
    return db.query(Swimmer).all()

def create_meets(db: Session, meet: schemas.MeetsCreate):
    db_meet = Meet(**meet.model_dump())
    db.add(db_meet)
    db.commit()
    db.refresh(db_meet)
    return db_meet

def get_meets(db: Session):
    return db.query(Meet).all()