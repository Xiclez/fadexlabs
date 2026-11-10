import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import Tool

# Formatos de entrega del DJ Library Upgrader (los mismos nombres que acepta --formato)
UPGRADE_FORMATS = ("aiff", "wav", "flac", "alac", "mp3", "m4a", "original")


class UploadInitIn(BaseModel):
    tool: Tool
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    # Solo DJ Library Upgrader:
    formato: Literal["aiff", "wav", "flac", "alac", "mp3", "m4a", "original"] = "aiff"
    accept_rights: bool = False

    @field_validator("filename")
    @classmethod
    def _basename(cls, v: str) -> str:
        # solo se guarda para mostrarlo; en disco el archivo se llama como el trabajo
        v = v.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not v or v in (".", ".."):
            raise ValueError("Nombre de archivo no válido")
        return "".join(c for c in v if c.isprintable())

    @model_validator(mode="after")
    def _rights(self):
        if self.tool == Tool.library_upgrade and not self.accept_rights:
            raise ValueError("Confirma que tienes derecho a usar la música de tu librería")
        return self


class UploadOut(BaseModel):
    upload_id: uuid.UUID
    chunk_size: int
    total_parts: int
    received_parts: int  # para reanudar: la siguiente parte a enviar


class JobOut(BaseModel):
    id: uuid.UUID
    tool: str
    status: str
    input_name: str
    input_bytes: int
    options: dict
    progress: int
    message: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    summary: dict | None = None
    files: list[str] = []
    drive_url: str | None = None
    # mientras se sube:
    chunk_size: int | None = None
    total_parts: int | None = None
    received_parts: int | None = None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int


class ToolLimits(BaseModel):
    max_bytes: int
    per_day: int
    extensions: list[str]


class ToolsInfo(BaseModel):
    chunk_size: int
    result_days: int
    tracklist: ToolLimits
    library_upgrade: ToolLimits
    library_max_files: int
    formats: list[str]


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    email_verified: bool
    whatsapp: str | None
    beta_seat: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminJobOut(JobOut):
    user_id: uuid.UUID
    user_email: str
    error: str | None
