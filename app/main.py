from fastapi import FastAPI
from routers import swimmers, meets, events, meet_entries, time_standards, swim_times

app = FastAPI()
app.include_router(swimmers.router)
app.include_router(meets.router)
app.include_router(events.router)
app.include_router(meet_entries.router)
app.include_router(time_standards.router)
app.include_router(swim_times.router)

@app.get("/")
def root():
    return {"status": "running"}
