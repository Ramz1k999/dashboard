from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from database import Base


class Patient(Base):
    """A row on the status board: a patient's name and current location/status."""

    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    location = Column(String(300), nullable=False)
    # "In transit" rows are rendered in italics on the board (e.g. "Transportation to Ultrasound 2")
    is_transit = Column(Boolean, nullable=False, default=False)
    # Manual ordering for the board (falls back to id if not set)
    position = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImportLog(Base):
    """Record of each CSV file picked up from the drop folder."""

    __tablename__ = "import_log"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(300), nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="ok")  # ok | error
    detail = Column(String(500), nullable=True)
    imported_at = Column(DateTime, nullable=False, default=datetime.utcnow)
