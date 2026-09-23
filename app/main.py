from fastapi import FastAPI
from routers import swimmers, meets, events

app = FastAPI()
app.include_router(swimmers.router)
app.include_router(meets.router)
app.include_router(events.router)

@app.get("/")
def root():
    return {"status": "running"}
