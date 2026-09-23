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


class MeetEntryCreate(BaseModel):
    meet_id: int
    swimmer_id: int
    event_id: int


class MeetEntryOut(MeetEntryCreate):
    id: int

    class Config:
        from_attributes = True


class TimeStandardCreate(BaseModel):
    event_id: int
    organization: str
    age_group: str
    gender: str
    standard_name: str
    standard_rank: int
    time_seconds: float
    season: str


class TimeStandardOut(TimeStandardCreate):
    id: int

    class Config:
        from_attributes = True