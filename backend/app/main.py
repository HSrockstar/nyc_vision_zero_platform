from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.health import readiness

app = FastAPI(title="Vision Zero 基础后端", version="0.1.0")


@app.get("/health/live")
def live() -> dict:
    return {"status": "alive"}


@app.get("/health/ready")
def ready() -> JSONResponse:
    body, status = readiness()
    return JSONResponse(body, status_code=status)
