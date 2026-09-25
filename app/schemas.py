from datetime import date as date_type
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from models import Course, Stroke

# Must match the gender values stored on TimeStandard rows ("F"/"M"),
# otherwise swimmers can never be matched against a standard.
Gender = Literal["F", "M"]

# Text limits match the column sizes in models.py (SQLite itself doesn't enforce them).
# Names are trimmed and can't be blank.
SwimmerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MeetName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
SwimmerNotes = Annotated[str, StringConstraints(max_length=500)]
Location = Annotated[str, StringConstraints(max_length=200)]
TimeNotes = Annotated[str, StringConstraints(max_length=300)]
DqReason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
RelayLeg = Annotated[int, Field(ge=1, le=4)]
PositiveSeconds = Annotated[float, Field(gt=0)]


def _reject_null(value):
    """For PATCH schemas: a field may be omitted, but not explicitly set to
    null when the underlying column is NOT NULL (that would 500 on commit)."""
    if value is None:
        raise ValueError("may be omitted but not set to null")
    return value


class SwimmerCreate(BaseModel):
    name: SwimmerName
    birthdate: date_type
    gender: Gender
    notes: SwimmerNotes | None = None


class SwimmerOut(SwimmerCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)  # lets Pydantic read directly from SQLAlchemy objects


class SwimmerUpdate(BaseModel):
    name: SwimmerName | None = None
    birthdate: date_type | None = None
    gender: Gender | None = None
    notes: SwimmerNotes | None = None

    _not_null = field_validator("name", "birthdate", "gender")(_reject_null)


def check_meet_dates(start: date_type, end: date_type | None):
    """Shared by MeetCreate and the PATCH router (which must merge in stored values first)."""
    if end is not None and end < start:
        raise ValueError("end_date must be on or after date")


class MeetCreate(BaseModel):
    name: MeetName
    date: date_type  # first day
    end_date: date_type | None = None  # last day, for multi-day meets
    location: Location | None = None

    @model_validator(mode="after")
    def _end_after_start(self):
        check_meet_dates(self.date, self.end_date)
        return self


class MeetOut(MeetCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MeetUpdate(BaseModel):
    name: MeetName | None = None
    date: date_type | None = None
    end_date: date_type | None = None
    location: Location | None = None

    _not_null = field_validator("name", "date")(_reject_null)


class MeetImportOut(BaseModel):
    """Summary of importing a results PDF into a meet."""

    results_parsed: int  # individual results found in the PDF, all teams
    times_imported: int
    meet_entries_created: int
    times_already_existed: int
    events_created: int
    skipped: dict[str, int]  # relay_or_time_trial / dq_or_no_show / unparsed_row


class EventCreate(BaseModel):
    distance: int = Field(gt=0)
    stroke: Stroke  # IM + relay = medley relay
    course: Course
    relay: bool = False


class EventOut(EventCreate):
    id: int
    name: str  # computed display name, e.g. "50 FR SCY" or "200 MED-R LCM"

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


def check_result(time_seconds: float | None, dq: bool, dq_reason: str | None):
    """Shared by SwimTimeCreate and the PATCH router (which must merge in stored values first)."""
    if not dq and time_seconds is None:
        raise ValueError("time_seconds is required unless the swim is a DQ")
    if dq_reason and not dq:
        raise ValueError("dq_reason is only allowed on a DQ")


class SwimTimeCreate(BaseModel):
    """A result. For a DQ the time is optional (the time swum, if the results show one).
    For a relay, time_seconds is the team's time and relay_leg/split_seconds are this swimmer's leg."""

    meet_entry_id: int
    time_seconds: PositiveSeconds | None = None
    notes: TimeNotes | None = None
    dq: bool = False
    dq_reason: DqReason | None = None
    relay_leg: RelayLeg | None = None
    split_seconds: PositiveSeconds | None = None

    @model_validator(mode="after")
    def _valid_result(self):
        check_result(self.time_seconds, self.dq, self.dq_reason)
        return self


class SwimTimeOut(SwimTimeCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class SwimTimeUpdate(BaseModel):
    time_seconds: PositiveSeconds | None = None  # null clears it (allowed only for a DQ)
    notes: TimeNotes | None = None
    dq: bool | None = None
    dq_reason: DqReason | None = None
    relay_leg: RelayLeg | None = None
    split_seconds: PositiveSeconds | None = None

    _not_null = field_validator("dq")(_reject_null)


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


class TimeStandardSetOut(BaseModel):
    """One published set of standards: an organization's tiers for one season."""

    organization: str
    season: str

    model_config = ConfigDict(from_attributes=True)
