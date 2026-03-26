"""
SQLAlchemy 2.0 async models for the PropAI Deal Intelligence Platform.

Core tables:
  - deals: The central object — a property being evaluated or managed
  - deal_versions: Full assumption snapshots (DealInput as JSON)
  - documents: Uploaded files (OMs, T-12s, rent rolls) linked to deals
  - analysis_results: All engine/AI outputs linked to deal + version
  - portfolios: Grouping container for deals
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, SoftDeleteMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DealStatus(str, enum.Enum):
    SCREENING = "screening"
    UNDERWRITING = "underwriting"
    DUE_DILIGENCE = "due_diligence"
    LOI = "loi"
    UNDER_CONTRACT = "under_contract"
    CLOSED = "closed"
    PASSED = "passed"
    DEAD = "dead"


class ParseStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------


class Portfolio(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    deals: Mapped[list[Deal]] = relationship(back_populates="portfolio")


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------


class Deal(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, native_enum=False, length=30),
        default=DealStatus.SCREENING,
        nullable=False,
    )
    asset_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    market: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    square_feet: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Sourcing
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Organization
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("portfolios.id"), nullable=True
    )
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    portfolio: Mapped[Portfolio | None] = relationship(back_populates="deals")
    versions: Mapped[list[DealVersion]] = relationship(
        back_populates="deal", order_by="DealVersion.version_number"
    )
    documents: Mapped[list[Document]] = relationship(back_populates="deal")
    results: Mapped[list[AnalysisResult]] = relationship(back_populates="deal")


# ---------------------------------------------------------------------------
# Deal Versions (full assumption snapshots)
# ---------------------------------------------------------------------------


class DealVersion(Base):
    __tablename__ = "deal_versions"
    __table_args__ = (
        UniqueConstraint("deal_id", "version_number", name="uq_deal_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deals.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deal_input: Mapped[dict] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    deal: Mapped[Deal] = relationship(back_populates="versions")
    results: Mapped[list[AnalysisResult]] = relationship(back_populates="version")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deals.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(20), default="local", nullable=False
    )
    parsed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parse_status: Mapped[ParseStatus] = mapped_column(
        Enum(ParseStatus, native_enum=False, length=20),
        default=ParseStatus.PENDING,
        nullable=False,
    )
    extracted_deal_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    deal: Mapped[Deal] = relationship(back_populates="documents")


# ---------------------------------------------------------------------------
# Analysis Results
# ---------------------------------------------------------------------------


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deals.id"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("deal_versions.id"), nullable=True
    )
    result_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    result_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    deal: Mapped[Deal] = relationship(back_populates="results")
    version: Mapped[DealVersion | None] = relationship(back_populates="results")
