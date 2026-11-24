from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
                       **({"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800} if not settings.database_url.startswith("sqlite") else {}))
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        yield db
