from datetime import date
from pydantic import BaseModel

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
    location: str

class MeetOut(MeetCreate):
    id: int

    class Config:
        from_attributes = True  # lets Pydantic read directly from SQLAlchemy objects
