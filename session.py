"""
session.py — SQLAlchemy synchrone (psycopg2 + CockroachDB)
FastAPI exécute automatiquement les routes `def` dans un ThreadPool.
Aucun blocage de l'event loop, aucun driver asyncpg nécessaire.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(
    os.getenv("COCKROACH_URL", ""),
    connect_args={"sslmode": "verify-full"},
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
