import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.user import utcnow


class Tool(StrEnum):
    tracklist = "tracklist"              # Tracklist ID: DJ set → tracklist con timestamps
    library_upgrade = "library_upgrade"  # DJ Library Upgrader: librería .zip → librería mejorada


class JobStatus(StrEnum):
    uploading = "uploading"  # recibiendo partes
    queued = "queued"        # esperando al worker
    running = "running"
    done = "done"
    failed = "failed"
    expired = "expired"      # resultados borrados tras result_ttl_days


ACTIVE = (JobStatus.queued, JobStatus.running)


class ToolJob(Base):
    """Un trabajo de una herramienta. Nace en `uploading` (su id es también el id de la subida)
    y el worker lo toma cuando pasa a `queued`."""
    __tablename__ = "tool_jobs"
    __table_args__ = (
        Index("ix_tool_jobs_queue", "status", "tool", "created_at"),
        Index("ix_tool_jobs_user", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tool: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.uploading)
    input_name: Mapped[str] = mapped_column(String(255))     # nombre original (solo para mostrarlo)
    input_bytes: Mapped[int] = mapped_column(BigInteger)
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # p. ej. {"formato": "aiff"}
    chunk_size: Mapped[int] = mapped_column(default=0)
    received_parts: Mapped[int] = mapped_column(default=0)   # partes 0..n-1 ya escritas en disco
    progress: Mapped[int] = mapped_column(default=0)         # 0-100
    message: Mapped[str] = mapped_column(String(300), default="")  # texto para el usuario
    error: Mapped[str | None] = mapped_column(Text)          # detalle interno: nunca sale por la API pública
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)        # {"summary": {...}, "files": [...], "drive_url": ...}

    @property
    def total_parts(self) -> int:
        return -(-self.input_bytes // self.chunk_size) if self.chunk_size else 0
