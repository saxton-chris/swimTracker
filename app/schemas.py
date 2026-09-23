from datetime import date
from pydantic import BaseModel

from models import Course, Stroke

class SwimmerCreate(BaseModel):
    name: str
    birthdate: date
    gender: str
    notes: str | None = None

class SwimmerOut(SwimmerCreate):
    id: int

    class Config:
        from_attributes = True  # lets Pydantic read directly from SQLAlchemy objects

class MeetCreate(BaseModel):
    name: str
    date: date
    location: str | None = None

class MeetOut(MeetCreate):
    id: int

    class Config:
        from_attributes = True

class EventCreate(BaseModel):
    distance: int
    stroke: Stroke
    course: Course

class EventOut(EventCreate):
    id: int
    name: str  # computed display name, e.g. "50 FR SCY"

    class Config:
        from_attributes = True
