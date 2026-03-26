"""
Deal Intelligence API — persistent deal lifecycle management.

Wraps the existing stateless underwriting/AI engines with database persistence.
Existing stateless endpoints (/api/underwrite, /api/ai/*) are NOT modified.
"""

from __future__ import annotations

import enum
import time
import uuid
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from db.models import (
    Deal,
    DealStatus,
    DealVersion,
    Document,
    ParseStatus,
    AnalysisResult,
    Portfolio,
)
from db.session import get_db
from engine.financial.models import DealInput
from engine.financial.proforma import ProFormaEngine
from engine.financial.waterfall import WaterfallEngine
from services.storage import get_storage

router = APIRouter(prefix="/api/deals", tags=["deals"])


# ---------------------------------------------------------------------------
# Result type enum (avoids scattered string literals)
# ---------------------------------------------------------------------------

class ResultType(str, enum.Enum):
    UNDERWRITING = "underwriting"
    MEMO = "memo"
    SCREEN_VERDICT = "screen_verdict"
    DUE_DILIGENCE = "due_diligence"


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class DealCreateStructured(BaseModel):
    mode: Literal["structured"]
    deal_input: DealInput
    name: str | None = None
    portfolio_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    source: str = "manual"
    source_detail: str = ""


class DealCreateQuick(BaseModel):
    mode: Literal["quick"]
    name: str
    asset_class: str | None = None
    market: str | None = None
    purchase_price: float | None = None
    units: int | None = None
    square_feet: float | None = None
    portfolio_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    source: str = "manual"
    source_detail: str = ""


class DealCreateNL(BaseModel):
    mode: Literal["natural_language"]
    text: str
    portfolio_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "ai_parse"
    source_detail: str = ""


DealCreateBody = Annotated[
    Union[DealCreateStructured, DealCreateQuick, DealCreateNL],
    Field(discriminator="mode"),
]


class DealUpdate(BaseModel):
    name: str | None = None
    status: DealStatus | None = None
    tags: list[str] | None = None
    notes: str | None = None
    portfolio_id: str | None = None
    source: str | None = None
    source_detail: str | None = None


class VersionCreate(BaseModel):
    deal_input: DealInput
    label: str = ""
    change_summary: str = ""
    set_primary: bool = True


class CompareRequest(BaseModel):
    deal_ids: list[str] = Field(..., min_length=2, max_length=5)


class PortfolioCreate(BaseModel):
    name: str = "Untitled Portfolio"
    description: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sync_deal_from_input(deal: Deal, deal_input: DealInput) -> None:
    """Keep deal metadata in sync with the latest DealInput."""
    deal.purchase_price = deal_input.purchase_price
    deal.units = deal_input.units
    deal.square_feet = deal_input.square_feet
    deal.market = deal_input.market
    deal.asset_class = (
        deal_input.asset_class.value
        if hasattr(deal_input.asset_class, "value")
        else str(deal_input.asset_class)
    )


async def _get_deal_or_404(db: AsyncSession, deal_id: str) -> Deal:
    stmt = select(Deal).where(
        Deal.id == uuid.UUID(deal_id), Deal.deleted_at.is_(None)
    )
    result = await db.execute(stmt)
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


async def _get_primary_version(db: AsyncSession, deal_id: uuid.UUID) -> DealVersion | None:
    stmt = select(DealVersion).where(
        DealVersion.deal_id == deal_id, DealVersion.is_primary.is_(True)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _next_version_number(db: AsyncSession, deal_id: uuid.UUID) -> int:
    stmt = (
        select(func.coalesce(func.max(DealVersion.version_number), 0))
        .where(DealVersion.deal_id == deal_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one() + 1


async def _clear_primary(db: AsyncSession, deal_id: uuid.UUID) -> None:
    """Bulk-unset is_primary on all versions for a deal."""
    stmt = (
        update(DealVersion)
        .where(DealVersion.deal_id == deal_id, DealVersion.is_primary.is_(True))
        .values(is_primary=False)
    )
    await db.execute(stmt)


def _run_underwriting(deal_input: DealInput):
    """Run underwriting engine (shared logic used by multiple endpoints)."""
    engine = ProFormaEngine(deal_input)
    result = engine.underwrite(include_sensitivity=True)
    if deal_input.equity_structure:
        wf = WaterfallEngine(
            equity_structure=deal_input.equity_structure,
            total_equity=result.equity_invested,
            cash_flows=engine._equity_cfs,
        )
        result.waterfall = wf.compute()
    return result


def _deal_to_dict(deal: Deal, version: DealVersion | None = None, results: list | None = None) -> dict:
    """Serialize a deal to API response."""
    d = {
        "id": str(deal.id),
        "name": deal.name,
        "status": deal.status.value if deal.status else None,
        "asset_class": deal.asset_class,
        "market": deal.market,
        "purchase_price": float(deal.purchase_price) if deal.purchase_price else None,
        "units": deal.units,
        "square_feet": float(deal.square_feet) if deal.square_feet else None,
        "year_built": deal.year_built,
        "address": deal.address,
        "source": deal.source,
        "source_detail": deal.source_detail,
        "portfolio_id": str(deal.portfolio_id) if deal.portfolio_id else None,
        "tags": deal.tags or [],
        "notes": deal.notes,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
        "updated_at": deal.updated_at.isoformat() if deal.updated_at else None,
    }
    if version:
        d["primary_version"] = {
            "id": str(version.id),
            "version_number": version.version_number,
            "label": version.label,
            "deal_input": version.deal_input,
            "change_summary": version.change_summary,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }
    if results is not None:
        d["latest_results"] = {}
        for r in results:
            if r.result_type not in d["latest_results"]:
                d["latest_results"][r.result_type] = {
                    "id": str(r.id),
                    "result_type": r.result_type,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "result_data": r.result_data,
                }
    return d


def _make_deal(
    name: str,
    status: DealStatus,
    *,
    asset_class: str | None = None,
    market: str | None = None,
    purchase_price: float | None = None,
    units: int | None = None,
    square_feet: float | None = None,
    source: str | None = None,
    source_detail: str | None = None,
    portfolio_id: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> Deal:
    """Construct a Deal from common fields (avoids copy-paste across create modes)."""
    return Deal(
        name=name,
        status=status,
        asset_class=asset_class,
        market=market,
        purchase_price=purchase_price,
        units=units,
        square_feet=square_feet,
        source=source,
        source_detail=source_detail,
        portfolio_id=uuid.UUID(portfolio_id) if portfolio_id else None,
        tags=tags or None,
        notes=notes or None,
    )


# ---------------------------------------------------------------------------
# Deal CRUD
# ---------------------------------------------------------------------------

@router.post("", summary="Create a new deal")
async def create_deal(body: DealCreateBody, db: AsyncSession = Depends(get_db)):
    """
    Create a deal in one of three modes:

    - **structured**: Provide a full DealInput JSON
    - **quick**: Provide minimal info (name, market, price)
    - **natural_language**: Provide free text, AI parses it
    """
    if isinstance(body, DealCreateStructured):
        deal_input = body.deal_input
        deal = _make_deal(
            name=body.name or deal_input.name,
            status=DealStatus.UNDERWRITING,
            market=deal_input.market,
            purchase_price=deal_input.purchase_price,
            units=deal_input.units,
            square_feet=deal_input.square_feet,
            source=body.source,
            source_detail=body.source_detail,
            portfolio_id=body.portfolio_id,
            tags=body.tags,
            notes=body.notes,
        )
        _sync_deal_from_input(deal, deal_input)
        db.add(deal)
        await db.flush()

        version = DealVersion(
            deal_id=deal.id,
            version_number=1,
            label="Initial assumptions",
            deal_input=deal_input.model_dump(),
            is_primary=True,
        )
        db.add(version)
        await db.commit()
        await db.refresh(deal)
        return _deal_to_dict(deal, version)

    elif isinstance(body, DealCreateNL):
        from agents.deal_parser import DealParser
        parser = DealParser(api_key=settings.anthropic_api_key)
        parse_result = await parser.parse(body.text)

        if not parse_result.success or not parse_result.deal_input:
            raise HTTPException(
                status_code=422,
                detail=f"Could not parse deal: {parse_result.error}",
            )

        deal_input = parse_result.deal_input
        deal = _make_deal(
            name=deal_input.name,
            status=DealStatus.SCREENING,
            source=body.source,
            source_detail=body.source_detail,
            portfolio_id=body.portfolio_id,
            tags=body.tags,
        )
        _sync_deal_from_input(deal, deal_input)
        db.add(deal)
        await db.flush()

        version = DealVersion(
            deal_id=deal.id,
            version_number=1,
            label="AI-parsed from natural language",
            deal_input=deal_input.model_dump(),
            change_summary=f"Extracted: {list(parse_result.extracted_values.keys())}. Assumed: {list(parse_result.assumed_values.keys())}.",
            is_primary=True,
        )
        db.add(version)
        await db.commit()
        await db.refresh(deal)

        response = _deal_to_dict(deal, version)
        response["parse_info"] = {
            "extracted_values": parse_result.extracted_values,
            "assumed_values": parse_result.assumed_values,
            "clarifications_needed": parse_result.clarifications_needed,
        }
        return response

    else:  # DealCreateQuick
        deal = _make_deal(
            name=body.name,
            status=DealStatus.SCREENING,
            asset_class=body.asset_class,
            market=body.market,
            purchase_price=body.purchase_price,
            units=body.units,
            square_feet=body.square_feet,
            source=body.source,
            source_detail=body.source_detail,
            portfolio_id=body.portfolio_id,
            tags=body.tags,
            notes=body.notes,
        )
        db.add(deal)
        await db.commit()
        await db.refresh(deal)
        return _deal_to_dict(deal)


@router.get("", summary="List deals")
async def list_deals(
    status: DealStatus | None = Query(None),
    asset_class: str | None = Query(None),
    portfolio_id: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """List deals with optional filters."""
    stmt = (
        select(Deal)
        .where(Deal.deleted_at.is_(None))
        .options(selectinload(Deal.versions))
    )

    if status:
        stmt = stmt.where(Deal.status == status)
    if asset_class:
        stmt = stmt.where(Deal.asset_class == asset_class)
    if portfolio_id:
        stmt = stmt.where(Deal.portfolio_id == uuid.UUID(portfolio_id))
    if search:
        stmt = stmt.where(Deal.name.ilike(f"%{search}%"))

    stmt = stmt.order_by(Deal.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    deals = result.scalars().unique().all()

    items = []
    for deal in deals:
        primary = next((v for v in deal.versions if v.is_primary), None)
        items.append(_deal_to_dict(deal, primary))

    return {"items": items, "count": len(items), "offset": offset}


@router.get("/{deal_id}", summary="Get deal detail")
async def get_deal(deal_id: str, db: AsyncSession = Depends(get_db)):
    """Get a deal with its primary version and latest results."""
    deal = await _get_deal_or_404(db, deal_id)
    version = await _get_primary_version(db, deal.id)

    # Latest result per type using DISTINCT ON (PostgreSQL)
    stmt = (
        select(AnalysisResult)
        .distinct(AnalysisResult.result_type)
        .where(AnalysisResult.deal_id == deal.id)
        .order_by(AnalysisResult.result_type, AnalysisResult.created_at.desc())
    )
    result = await db.execute(stmt)
    results = result.scalars().all()

    return _deal_to_dict(deal, version, results)


@router.patch("/{deal_id}", summary="Update deal metadata")
async def update_deal(
    deal_id: str,
    body: DealUpdate,
    db: AsyncSession = Depends(get_db),
):
    deal = await _get_deal_or_404(db, deal_id)

    if body.name is not None:
        deal.name = body.name
    if body.status is not None:
        deal.status = body.status
    if body.tags is not None:
        deal.tags = body.tags
    if body.notes is not None:
        deal.notes = body.notes
    if body.portfolio_id is not None:
        deal.portfolio_id = uuid.UUID(body.portfolio_id) if body.portfolio_id else None
    if body.source is not None:
        deal.source = body.source
    if body.source_detail is not None:
        deal.source_detail = body.source_detail

    await db.commit()
    await db.refresh(deal)
    version = await _get_primary_version(db, deal.id)
    return _deal_to_dict(deal, version)


@router.delete("/{deal_id}", summary="Soft delete a deal")
async def delete_deal(deal_id: str, db: AsyncSession = Depends(get_db)):
    deal = await _get_deal_or_404(db, deal_id)
    deal.soft_delete()
    await db.commit()
    return {"deleted": True, "id": deal_id}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.post("/{deal_id}/versions", summary="Create a new version")
async def create_version(
    deal_id: str,
    body: VersionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new assumption version for a deal."""
    deal = await _get_deal_or_404(db, deal_id)
    next_num = await _next_version_number(db, deal.id)

    if body.set_primary:
        await _clear_primary(db, deal.id)

    version = DealVersion(
        deal_id=deal.id,
        version_number=next_num,
        label=body.label or f"Version {next_num}",
        deal_input=body.deal_input.model_dump(),
        change_summary=body.change_summary,
        is_primary=body.set_primary,
    )
    db.add(version)
    _sync_deal_from_input(deal, body.deal_input)

    await db.commit()
    await db.refresh(version)

    return {
        "id": str(version.id),
        "deal_id": str(deal.id),
        "version_number": version.version_number,
        "label": version.label,
        "is_primary": version.is_primary,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.get("/{deal_id}/versions", summary="List versions")
async def list_versions(deal_id: str, db: AsyncSession = Depends(get_db)):
    deal = await _get_deal_or_404(db, deal_id)
    stmt = (
        select(DealVersion)
        .where(DealVersion.deal_id == deal.id)
        .order_by(DealVersion.version_number)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    return [
        {
            "id": str(v.id),
            "version_number": v.version_number,
            "label": v.label,
            "is_primary": v.is_primary,
            "change_summary": v.change_summary,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@router.post("/{deal_id}/documents", summary="Upload a document")
async def upload_document(
    deal_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form("auto"),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document (PDF, text) to a deal."""
    deal = await _get_deal_or_404(db, deal_id)
    storage = get_storage()

    content = await file.read()
    path = await storage.save(
        deal_id=str(deal.id),
        data=content,
        filename=file.filename or "document",
    )

    doc = Document(
        deal_id=deal.id,
        filename=file.filename or "document",
        doc_type=doc_type,
        content_type=file.content_type,
        file_size_bytes=len(content),
        storage_path=path,
        storage_backend=settings.storage_backend,
        parse_status=ParseStatus.PENDING,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return {
        "id": str(doc.id),
        "deal_id": str(deal.id),
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "file_size_bytes": doc.file_size_bytes,
        "parse_status": doc.parse_status.value,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/{deal_id}/documents", summary="List documents")
async def list_documents(deal_id: str, db: AsyncSession = Depends(get_db)):
    deal = await _get_deal_or_404(db, deal_id)
    stmt = (
        select(Document)
        .where(Document.deal_id == deal.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "doc_type": d.doc_type,
            "file_size_bytes": d.file_size_bytes,
            "parse_status": d.parse_status.value,
            "has_parsed_data": d.parsed_data is not None,
            "has_extracted_deal": d.extracted_deal_input is not None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.post("/{deal_id}/documents/{doc_id}/parse", summary="Parse document with AI")
async def parse_document(
    deal_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Trigger AI parsing of an uploaded document."""
    deal = await _get_deal_or_404(db, deal_id)
    stmt = select(Document).where(
        Document.id == uuid.UUID(doc_id), Document.deal_id == deal.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage()
    content = await storage.get(doc.storage_path)

    doc.parse_status = ParseStatus.PROCESSING
    await db.commit()

    try:
        from agents.document_parser import DocumentParser

        parser = DocumentParser()
        parsed = await parser.parse_bytes(content, doc.doc_type)

        import dataclasses
        parsed_dict = dataclasses.asdict(parsed) if dataclasses.is_dataclass(parsed) else {}

        doc.parsed_data = parsed_dict
        doc.parse_status = ParseStatus.COMPLETED
        doc.doc_type = parsed.doc_type

        if parsed.deal_input:
            doc.extracted_deal_input = parsed.deal_input.model_dump()

        await db.commit()
        await db.refresh(doc)

        return {
            "id": str(doc.id),
            "parse_status": "completed",
            "doc_type": doc.doc_type,
            "has_extracted_deal": doc.extracted_deal_input is not None,
            "confidence": parsed.confidence,
            "red_flags": parsed.red_flags,
        }

    except Exception as e:
        doc.parse_status = ParseStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}")


@router.post("/{deal_id}/documents/{doc_id}/apply", summary="Apply parsed data as new version")
async def apply_parsed_document(
    deal_id: str,
    doc_id: str,
    label: str = "From parsed document",
    db: AsyncSession = Depends(get_db),
):
    """Create a new deal version from a parsed document's extracted DealInput."""
    deal = await _get_deal_or_404(db, deal_id)
    stmt = select(Document).where(
        Document.id == uuid.UUID(doc_id), Document.deal_id == deal.id
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc or not doc.extracted_deal_input:
        raise HTTPException(status_code=400, detail="No extracted deal data available")

    deal_input = DealInput.model_validate(doc.extracted_deal_input)
    next_num = await _next_version_number(db, deal.id)
    await _clear_primary(db, deal.id)

    version = DealVersion(
        deal_id=deal.id,
        version_number=next_num,
        label=label,
        deal_input=deal_input.model_dump(),
        change_summary=f"Applied from parsed {doc.doc_type}: {doc.filename}",
        is_primary=True,
    )
    db.add(version)
    _sync_deal_from_input(deal, deal_input)

    await db.commit()
    await db.refresh(version)
    return {
        "version_id": str(version.id),
        "version_number": version.version_number,
        "label": version.label,
    }


# ---------------------------------------------------------------------------
# Analysis (persistent underwriting)
# ---------------------------------------------------------------------------

@router.post("/{deal_id}/underwrite", summary="Run underwriting and save result")
async def underwrite_deal(deal_id: str, db: AsyncSession = Depends(get_db)):
    """Run the underwriting engine on the primary version, persist the result."""
    deal = await _get_deal_or_404(db, deal_id)
    version = await _get_primary_version(db, deal.id)
    if not version:
        raise HTTPException(status_code=400, detail="No version available to underwrite")

    deal_input = DealInput.model_validate(version.deal_input)

    start = time.perf_counter()
    result = _run_underwriting(deal_input)
    elapsed = round(time.perf_counter() - start, 3)

    analysis = AnalysisResult(
        deal_id=deal.id,
        version_id=version.id,
        result_type=ResultType.UNDERWRITING.value,
        result_data=result.model_dump(),
        metadata_={"elapsed_seconds": elapsed, "version_number": version.version_number},
    )
    db.add(analysis)

    if deal.status == DealStatus.SCREENING:
        deal.status = DealStatus.UNDERWRITING

    await db.commit()
    await db.refresh(analysis)

    return {
        "result_id": str(analysis.id),
        "deal_id": str(deal.id),
        "version_number": version.version_number,
        "elapsed_seconds": elapsed,
        "result": result.model_dump(),
    }


@router.get("/{deal_id}/results", summary="List analysis results")
async def list_results(deal_id: str, db: AsyncSession = Depends(get_db)):
    deal = await _get_deal_or_404(db, deal_id)
    stmt = (
        select(AnalysisResult)
        .where(AnalysisResult.deal_id == deal.id)
        .order_by(AnalysisResult.created_at.desc())
    )
    result = await db.execute(stmt)
    results = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "result_type": r.result_type,
            "version_id": str(r.version_id) if r.version_id else None,
            "metadata": r.metadata_,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ]


@router.get("/{deal_id}/results/{result_id}", summary="Get analysis result")
async def get_result(deal_id: str, result_id: str, db: AsyncSession = Depends(get_db)):
    deal = await _get_deal_or_404(db, deal_id)
    stmt = select(AnalysisResult).where(
        AnalysisResult.id == uuid.UUID(result_id),
        AnalysisResult.deal_id == deal.id,
    )
    result = await db.execute(stmt)
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Result not found")

    return {
        "id": str(analysis.id),
        "deal_id": str(deal.id),
        "result_type": analysis.result_type,
        "version_id": str(analysis.version_id) if analysis.version_id else None,
        "result_data": analysis.result_data,
        "metadata": analysis.metadata_,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


# ---------------------------------------------------------------------------
# Deal Comparison
# ---------------------------------------------------------------------------

@router.post("/compare", summary="Compare deals side-by-side")
async def compare_deals(body: CompareRequest, db: AsyncSession = Depends(get_db)):
    """Compare up to 5 deals side-by-side with their key metrics."""
    deal_uuids = [uuid.UUID(d) for d in body.deal_ids]

    # Batch-load deals + versions in 2 queries (not N+1)
    stmt = (
        select(Deal)
        .where(Deal.id.in_(deal_uuids), Deal.deleted_at.is_(None))
        .options(selectinload(Deal.versions))
    )
    result = await db.execute(stmt)
    deals = {d.id: d for d in result.scalars().unique().all()}

    # Batch-load latest underwriting results
    result_stmt = (
        select(AnalysisResult)
        .where(
            AnalysisResult.deal_id.in_(deal_uuids),
            AnalysisResult.result_type == ResultType.UNDERWRITING.value,
        )
        .order_by(AnalysisResult.deal_id, AnalysisResult.created_at.desc())
        .distinct(AnalysisResult.deal_id)
    )
    result = await db.execute(result_stmt)
    latest_by_deal = {r.deal_id: r for r in result.scalars().all()}

    deals_data = []
    for did in deal_uuids:
        deal = deals.get(did)
        if not deal:
            continue

        primary = next((v for v in deal.versions if v.is_primary), None)
        latest = latest_by_deal.get(did)

        entry = {
            "deal_id": str(deal.id),
            "name": deal.name,
            "status": deal.status.value,
            "market": deal.market,
            "asset_class": deal.asset_class,
            "purchase_price": float(deal.purchase_price) if deal.purchase_price else None,
            "units": deal.units,
        }

        if latest and latest.result_data:
            metrics = latest.result_data.get("metrics", {})
            entry["metrics"] = {
                "going_in_cap_rate": metrics.get("going_in_cap_rate"),
                "cash_on_cash_yr1": metrics.get("cash_on_cash_yr1"),
                "dscr_yr1": metrics.get("dscr_yr1"),
                "levered_irr": metrics.get("levered_irr"),
                "equity_multiple": metrics.get("equity_multiple"),
                "npv": metrics.get("npv"),
            }
        else:
            entry["metrics"] = None

        deals_data.append(entry)

    return {"deals": deals_data}


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

@router.post("/portfolios", summary="Create portfolio", tags=["portfolios"])
async def create_portfolio(body: PortfolioCreate, db: AsyncSession = Depends(get_db)):
    portfolio = Portfolio(name=body.name, description=body.description)
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return {
        "id": str(portfolio.id),
        "name": portfolio.name,
        "description": portfolio.description,
    }


@router.get("/portfolios", summary="List portfolios", tags=["portfolios"])
async def list_portfolios(db: AsyncSession = Depends(get_db)):
    stmt = select(Portfolio).where(Portfolio.deleted_at.is_(None))
    result = await db.execute(stmt)
    portfolios = result.scalars().all()

    # Single grouped count query instead of N+1
    count_stmt = (
        select(Deal.portfolio_id, func.count().label("cnt"))
        .where(Deal.deleted_at.is_(None), Deal.portfolio_id.isnot(None))
        .group_by(Deal.portfolio_id)
    )
    count_result = await db.execute(count_stmt)
    counts = dict(count_result.all())

    return {
        "items": [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "deal_count": counts.get(p.id, 0),
            }
            for p in portfolios
        ]
    }
