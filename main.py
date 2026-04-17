import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine import run_solve

app = FastAPI(title="Aspexy OR Solver", version="1.1.0")

_cors_raw = os.getenv("CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.post("/solve")
def solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return run_solve(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
