"""
user_app/main.py — Application utilisateur (port 8001)
Lancement : cd user_app && uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from session import engine, SessionLocal, Base
from models import User, UserRole

import routes.files     as route_files
import routes.favorites as route_favorites




app = FastAPI(title="LinkHarvest — Bibliothèque", version="3.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE_DIR, "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(FRONTEND, "templates"))

api = APIRouter(prefix="/api")

api.include_router(route_files.router)

api.include_router(route_favorites.router)
app.include_router(api)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
