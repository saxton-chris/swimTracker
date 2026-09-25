import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routers import events, meet_entries, meets, swim_times, swimmers, time_standards

STATIC_DIR = Path(__file__).parent / "static"

# Browsers refuse to run an ES module unless it's served as JavaScript. On Windows,
# Python reads file types from the registry, where .js is sometimes "text/plain".
mimetypes.add_type("text/javascript", ".js")

app = FastAPI(title="Swim Tracker", summary="Meet results and time standards for a swimmer")
app.include_router(swimmers.router)
app.include_router(meets.router)
app.include_router(events.router)
app.include_router(meet_entries.router)
app.include_router(time_standards.router)
app.include_router(swim_times.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    """Make browsers re-check the page and its static files on every load.
    Without a Cache-Control header they guess a cache lifetime, and can keep
    running old JS modules against a new index.html after an update. Unchanged
    files still come back as a cheap 304 thanks to the ETag."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "running"}
