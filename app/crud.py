from sqlalchemy.orm import Session
from models import Swimmer
import schemas

def create_swimmer(db: Session, swimmer: schemas.SwimmerCreate):
    db_swimmer = Swimmer(**swimmer.model_dump())
    db.add(db_swimmer)
    db.commit()
    db.refresh(db_swimmer)
    return db_swimmer

def get_swimmers(db: Session):
    return db.query(Swimmer).all()
