from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

router = APIRouter(prefix="/meet_entries", tags=["meet_entries"])

@router.post("/", response_model=schemas.MeetEntryOut)
def add_meet_entry(meet_entry: schemas.MeetEntryCreate, db: Session = Depends(get_db)):
    if not crud.get_swimmer_by_id(db, meet_entry.swimmer_id):
        raise HTTPException(status_code=404, detail=f"Swimmer {meet_entry.swimmer_id} not found")
    if not crud.get_meet_by_id(db, meet_entry.meet_id):
        raise HTTPException(status_code=404, detail=f"Meet {meet_entry.meet_id} not found")
    if not crud.get_event_by_id(db, meet_entry.event_id):
        raise HTTPException(status_code=404, detail=f"Event {meet_entry.event_id} not found")

    existing = crud.get_meet_entry(db, meet_entry.meet_id, meet_entry.swimmer_id, meet_entry.event_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="This swimmer is already entered in this event at this meet",
        )

    return crud.create_meet_entry(db, meet_entry)

@router.get("/", response_model=list[schemas.MeetEntryOut])
def list_meet_entries(
    meet_id: int | None = None,
    swimmer_id: int | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_meet_entries(db, meet_id=meet_id, swimmer_id=swimmer_id)

@router.patch("/{meet_entry_id}", response_model=schemas.MeetEntryOut)
def update_meet_entry(meet_entry_id: int, update: schemas.MeetEntryUpdate, db: Session = Depends(get_db)):
    existing = crud.get_meet_entry_by_id(db, meet_entry_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Meet entry {meet_entry_id} not found")

    changes = update.model_dump(exclude_unset=True)

    # Validate any FK fields that are actually being changed
    if "swimmer_id" in changes and not crud.get_swimmer_by_id(db, changes["swimmer_id"]):
        raise HTTPException(status_code=404, detail=f"Swimmer {changes['swimmer_id']} not found")
    if "meet_id" in changes and not crud.get_meet_by_id(db, changes["meet_id"]):
        raise HTTPException(status_code=404, detail=f"Meet {changes['meet_id']} not found")
    if "event_id" in changes and not crud.get_event_by_id(db, changes["event_id"]):
        raise HTTPException(status_code=404, detail=f"Event {changes['event_id']} not found")

    # Re-check the uniqueness triple using the post-update values (changed fields override existing ones)
    if changes:
        new_meet_id = changes.get("meet_id", existing.meet_id)
        new_swimmer_id = changes.get("swimmer_id", existing.swimmer_id)
        new_event_id = changes.get("event_id", existing.event_id)
        duplicate = crud.get_meet_entry(db, new_meet_id, new_swimmer_id, new_event_id)
        if duplicate and duplicate.id != meet_entry_id:
            raise HTTPException(
                status_code=400,
                detail="This swimmer is already entered in this event at this meet",
            )

    return crud.update_meet_entry(db, meet_entry_id, update)
