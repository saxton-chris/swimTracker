import enum
from datetime import date

from sqlalchemy import Date, Enum as SAEnum, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Stroke(str, enum.Enum):
    FR = "FR"  # Freestyle
    BK = "BK"  # Backstroke
    BR = "BR"  # Breaststroke
    FL = "FL"  # Butterfly
    IM = "IM"  # Individual Medley


class Course(str, enum.Enum):
    SCY = "SCY"  # Short Course Yards
    SCM = "SCM"  # Short Course Meters
    LCM = "LCM"  # Long Course Meters


class Swimmer(Base):
    __tablename__ = "swimmers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    birthdate: Mapped[date] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(10))  # used for matching time standards
    notes: Mapped[str | None] = mapped_column(String(500), default=None)

    meet_entries: Mapped[list["MeetEntry"]] = relationship(back_populates="swimmer")


class Meet(Base):
    __tablename__ = "meets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    date: Mapped[date] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(200), default=None)

    meet_entries: Mapped[list["MeetEntry"]] = relationship(back_populates="meet")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    distance: Mapped[int] = mapped_column()  # e.g. 50, 100, 200
    stroke: Mapped[Stroke] = mapped_column(SAEnum(Stroke))
    course: Mapped[Course] = mapped_column(SAEnum(Course))

    meet_entries: Mapped[list["MeetEntry"]] = relationship(back_populates="event")
    time_standards: Mapped[list["TimeStandard"]] = relationship(back_populates="event")

    __table_args__ = (
        UniqueConstraint("distance", "stroke", "course", name="uix_event"),
    )

    @property
    def name(self) -> str:
        """Display name, e.g. '50 FR SCY'. Not a stored column."""
        return f"{self.distance} {self.stroke.value} {self.course.value}"


class MeetEntry(Base):
    """Links a swimmer to a specific event at a specific meet.

    One row = one swimmer swimming one event at one meet.
    SwimTime hangs off this (a meet entry may or may not have a
    recorded result yet, e.g. before the meet happens).
    """

    __tablename__ = "meet_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    meet_id: Mapped[int] = mapped_column(ForeignKey("meets.id"))
    swimmer_id: Mapped[int] = mapped_column(ForeignKey("swimmers.id"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))

    meet: Mapped["Meet"] = relationship(back_populates="meet_entries")
    swimmer: Mapped["Swimmer"] = relationship(back_populates="meet_entries")
    event: Mapped["Event"] = relationship(back_populates="meet_entries")
    swim_time: Mapped["SwimTime | None"] = relationship(
        back_populates="meet_entry", uselist=False
    )


class SwimTime(Base):
    """The actual recorded result for a meet entry.

    Stored as a float in seconds (e.g. 62.45) rather than a formatted
    string like "1:02.45" - makes comparisons/math against time
    standards trivial. Format for display in the app layer instead.
    """

    __tablename__ = "swim_times"

    id: Mapped[int] = mapped_column(primary_key=True)
    meet_entry_id: Mapped[int] = mapped_column(ForeignKey("meet_entries.id"), unique=True)
    time_seconds: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String(300), default=None)

    meet_entry: Mapped["MeetEntry"] = relationship(back_populates="swim_time")


class TimeStandard(Base):
    """Reference data: the cutoff time for a given standard tier,
    event, age group, and gender (e.g. "BB" standard, 50 Free,
    11-12, Male, 2026 season = 29.99 seconds).

    Independent of swimmers/meets - this is lookup data you'll
    likely bulk-load once per season rather than enter one at a time.
    """

    __tablename__ = "time_standards"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    age_group: Mapped[str] = mapped_column(String(20))  # e.g. "11-12", "10 & Under"
    gender: Mapped[str] = mapped_column(String(10))
    standard_name: Mapped[str] = mapped_column(String(20))  # e.g. "B", "BB", "A", "AA", "AAA"
    standard_rank: Mapped[int] = mapped_column()  # numeric order, e.g. B=1, BB=2, A=3 ... used to find "next standard up"
    time_seconds: Mapped[float] = mapped_column(Float)
    season: Mapped[str] = mapped_column(String(20))  # e.g. "2025-2026"

    event: Mapped["Event"] = relationship(back_populates="time_standards")

    __table_args__ = (
        UniqueConstraint(
            "event_id", "age_group", "gender", "standard_name", "season",
            name="uix_time_standard",
        ),
    )
