import io
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

import crud
import import_meet_results
import schemas
from database import get_db

router = APIRouter(prefix="/meets", tags=["meets"])


@router.post("/", response_model=schemas.MeetOut)
def add_meet(meet: schemas.MeetCreate, db: Session = Depends(get_db)):
    return crud.create_meet(db, meet)


@router.get("/", response_model=list[schemas.MeetOut])
def list_meets(db: Session = Depends(get_db)):
    return crud.get_meets(db)


@router.patch("/{meet_id}", response_model=schemas.MeetOut)
def update_meet(meet_id: int, update: schemas.MeetUpdate, db: Session = Depends(get_db)):
    existing = crud.get_meet_by_id(db, meet_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")

    # Check the date range using post-update values (changed fields override stored ones)
    changes = update.model_dump(exclude_unset=True)
    try:
        schemas.check_meet_dates(changes.get("date", existing.date), changes.get("end_date", existing.end_date))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return crud.update_meet(db, meet_id, update)


@router.post("/{meet_id}/import-results", response_model=schemas.MeetImportOut)
def import_meet_results_pdf(
    meet_id: int,
    data: Annotated[bytes, Body(media_type="application/pdf")],
    db: Session = Depends(get_db),
):
    """Import a Hy-Tek results PDF (sent as the raw request body) into this meet.

    Same rules as import_meet_results.py: only swimmers already in the database
    are matched; an existing meet entry gets the time, otherwise the entry is
    created first; a result that already has a time is left alone."""
    if crud.get_meet_by_id(db, meet_id) is None:
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")

    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="The uploaded file isn't a PDF.")

    try:
        results, skip_counts = import_meet_results.parse_pdf(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read the PDF: {e}") from e

    stats = import_meet_results.new_stats()
    import_meet_results.import_results(db, results, meet_id, None, stats, set(), dry_run=False)
    return schemas.MeetImportOut(
        results_parsed=len(results),
        times_imported=stats["times_imported"],
        meet_entries_created=stats["meet_entries_created"],
        times_already_existed=stats["times_already_existed"],
        events_created=stats["events_created"],
        skipped=skip_counts,
    )


@router.delete("/{meet_id}", status_code=204)
def delete_meet(meet_id: int, db: Session = Depends(get_db)):
    if not crud.delete_meet(db, meet_id):
        raise HTTPException(status_code=404, detail=f"Meet {meet_id} not found")
