from fastapi import FastAPI
from routers import swimmers, meets

app = FastAPI()
app.include_router(swimmers.router)
app.include_router(meets.router)

@app.get("/")
def root():
    return {"status": "running"}
