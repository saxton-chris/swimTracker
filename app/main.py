from fastapi import FastAPI
from routers import swimmers

app = FastAPI()
app.include_router(swimmers.router)

@app.get("/")
def root():
    return {"status": "running"}
