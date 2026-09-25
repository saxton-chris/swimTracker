from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models import Course, Stroke

# Must match the gender values stored on TimeStandard rows ("F"/"M"),
# otherwise swimmers can never be matched against a standard.
Gender = Literal["F", "M"]


def _reject_null(value):
    """For PATCH schemas: a field may be omitted, but not explicitly set to
    null when the underlying column is NOT NULL (that would 500 on commit)."""
    if value is None:
        raise ValueError("may be omitted but not set to null")
    return value


class SwimmerCreate(BaseModel):
    name: str
    birthdate: date_type
    gender: Gender
    notes: str | None = None


class SwimmerOut(SwimmerCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)  # lets Pydantic read directly from SQLAlchemy objects


class SwimmerUpdate(BaseModel):
    name: str | None = None
    birthdate: date_type | None = None
    gender: Gender | None = None
    notes: str | None = None

    _not_null = field_validator("name", "birthdate", "gender")(_reject_null)


def check_meet_dates(start: date_type, end: date_type | None):
    """Shared by MeetCreate and the PATCH router (which must merge in stored values first)."""
    if end is not None and end < start:
        raise ValueError("end_date must be on or after date")


class MeetCreate(BaseModel):
    name: str
    date: date_type  # first day
    end_date: date_type | None = None  # last day, for multi-day meets
    location: str | None = None

    @model_validator(mode="after")
    def _end_after_start(self):
        check_meet_dates(self.date, self.end_date)
        return self


class MeetOut(MeetCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MeetUpdate(BaseModel):
    name: str | None = None
    date: date_type | None = None
    end_date: date_type | None = None
    location: str | None = None

    _not_null = field_validator("name", "date")(_reject_null)


class EventCreate(BaseModel):
    distance: int = Field(gt=0)
    stroke: Stroke
    course: Course


class EventOut(EventCreate):
    id: int
    name: str  # computed display name, e.g. "50 FR SCY"

    model_config = ConfigDict(from_attributes=True)


class MeetEntryCreate(BaseModel):
    meet_id: int
    swimmer_id: int
    event_id: int


class MeetEntryOut(MeetEntryCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MeetEntryUpdate(BaseModel):
    meet_id: int | None = None
    swimmer_id: int | None = None
    event_id: int | None = None

    _not_null = field_validator("meet_id", "swimmer_id", "event_id")(_reject_null)


class SwimTimeCreate(BaseModel):
    meet_entry_id: int
    time_seconds: float = Field(gt=0)
    notes: str | None = None


class SwimTimeOut(SwimTimeCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class SwimTimeUpdate(BaseModel):
    time_seconds: float | None = Field(default=None, gt=0)
    notes: str | None = None

    _not_null = field_validator("time_seconds")(_reject_null)


class TimeStandardCreate(BaseModel):
    event_id: int
    organization: str
    age_group: str
    gender: Gender
    standard_name: str
    standard_rank: int
    time_seconds: float = Field(gt=0)
    season: str


class TimeStandardOut(TimeStandardCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
