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
from auth import hash_password

import routes.auth      as route_auth
import routes.files     as route_files
import routes.upload    as route_upload
import routes.favorites as route_favorites


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if not db.scalars(select(User).filter_by(username="admin")).first():
            db.add(User(
                username="admin",
                password_hash=hash_password("admin123"),
                role=UserRole.ADMIN,
            ))
            db.commit()
            print("[INIT] Compte admin créé — admin / admin123")
    finally:
        db.close()
    yield


app = FastAPI(title="LinkHarvest — Bibliothèque", version="3.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE_DIR, "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(FRONTEND, "templates"))

api = APIRouter(prefix="/api")
api.include_router(route_auth.router)
api.include_router(route_files.router)
api.include_router(route_upload.router)
api.include_router(route_favorites.router)
app.include_router(api)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
