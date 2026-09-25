from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routers import events, meet_entries, meets, swim_times, swimmers, time_standards

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.include_router(swimmers.router)
app.include_router(meets.router)
app.include_router(events.router)
app.include_router(meet_entries.router)
app.include_router(time_standards.router)
app.include_router(swim_times.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
def health():
    return {"status": "running"}
