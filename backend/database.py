import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.environ.get("RIOBSIATM_DB_PATH", os.path.join(os.path.dirname(__file__), "riobsiatm.db"))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False: FastAPI can use the session from different threads
# under the default (non-async) request handling; SQLite is fine with this
# as long as we open one session per request (see get_db in main.py).
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
