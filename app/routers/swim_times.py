from fastapi import APIRouter, HTTPException

import crud
import schemas
from database import DbSession

router = APIRouter(prefix="/swim_times", tags=["swim_times"])


def _check_relay_fields(entry, relay_leg, split_seconds):
    """A relay leg and split only make sense on a relay event."""
    if not entry.event.relay and (relay_leg is not None or split_seconds is not None):
        raise HTTPException(
            status_code=422, detail=f"relay_leg and split_seconds are only for relays, not {entry.event.name}"
        )


@router.post("/", response_model=schemas.SwimTimeOut)
def add_swim_time(swim_time: schemas.SwimTimeCreate, db: DbSession):
    entry = crud.get_meet_entry_by_id(db, swim_time.meet_entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Meet entry {swim_time.meet_entry_id} not found")

    existing = crud.get_swim_time_by_meet_entry(db, swim_time.meet_entry_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A time already exists for meet entry {swim_time.meet_entry_id} "
            f"- use PATCH /swim_times/{existing.id} to update it",
        )
    _check_relay_fields(entry, swim_time.relay_leg, swim_time.split_seconds)

    return crud.create_swim_time(db, swim_time)


@router.get("/", response_model=list[schemas.SwimTimeOut])
def list_swim_times(db: DbSession, meet_entry_id: int | None = None):
    return crud.get_swim_times(db, meet_entry_id=meet_entry_id)


@router.patch("/{swim_time_id}", response_model=schemas.SwimTimeOut)
def update_swim_time(swim_time_id: int, update: schemas.SwimTimeUpdate, db: DbSession):
    existing = crud.get_swim_time_by_id(db, swim_time_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Swim time {swim_time_id} not found")

    changes = update.model_dump(exclude_unset=True)
    # Un-DQ'ing a result drops its reason unless the client says otherwise.
    if changes.get("dq") is False and "dq_reason" not in changes:
        update = update.model_copy(update={"dq_reason": None})
        changes["dq_reason"] = None

    # Validate the result as it will be after the update (changed fields override stored ones).
    merged = {f: changes.get(f, getattr(existing, f)) for f in ("time_seconds", "dq", "dq_reason")}
    try:
        schemas.check_result(merged["time_seconds"], merged["dq"], merged["dq_reason"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    _check_relay_fields(
        existing.meet_entry,
        changes.get("relay_leg", existing.relay_leg),
        changes.get("split_seconds", existing.split_seconds),
    )

    return crud.update_swim_time(db, swim_time_id, update)


@router.delete("/{swim_time_id}", status_code=204)
def delete_swim_time(swim_time_id: int, db: DbSession):
    if not crud.delete_swim_time(db, swim_time_id):
        raise HTTPException(status_code=404, detail=f"Swim time {swim_time_id} not found")
