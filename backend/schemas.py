from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PatientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    location: str = Field(..., min_length=1, max_length=300)
    is_transit: bool = False
    position: int = 0


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    """All fields optional so PATCH-style partial updates work through PUT."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    location: Optional[str] = Field(None, min_length=1, max_length=300)
    is_transit: Optional[bool] = None
    position: Optional[int] = None


class PatientOut(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime


class ImportLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    row_count: int
    status: str
    detail: Optional[str] = None
    imported_at: datetime
