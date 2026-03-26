"""
Tests for the Deal Intelligence API.

Uses an in-memory SQLite database to test the full deals API without PostgreSQL.
PostgreSQL-specific features (ARRAY, JSONB) are patched to SQLite-compatible types.
"""

import sys
import os
import uuid

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import JSON, String
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.base import Base
from db.models import (
    Deal,
    DealStatus,
    DealVersion,
    Document,
    ParseStatus,
    AnalysisResult,
    Portfolio,
)
from api.deals import (
    _make_deal,
    _sync_deal_from_input,
    _deal_to_dict,
    _run_underwriting,
    ResultType,
)
from engine.financial.models import (
    DealInput,
    AssetClass,
    LoanInput,
    LoanType,
    OperatingAssumptions,
    ExitAssumptions,
)


# ---------------------------------------------------------------------------
# Test database setup (SQLite in-memory)
# ---------------------------------------------------------------------------

# Patch PostgreSQL-specific column types for SQLite compatibility
_pg_type_overrides = {
    "JSONB": JSON,
    "UUID": String(36),
    "ARRAY": String(500),
}


@pytest.fixture(scope="session")
def _patch_pg_types():
    """Patch PostgreSQL dialect types to work with SQLite."""
    import sqlalchemy.dialects.postgresql as pg

    original_jsonb = pg.JSONB
    original_uuid = pg.UUID
    original_array = pg.ARRAY

    pg.JSONB = JSON
    pg.UUID = lambda **kw: String(36)
    pg.ARRAY = lambda *a, **kw: String(500)

    yield

    pg.JSONB = original_jsonb
    pg.UUID = original_uuid
    pg.ARRAY = original_array


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database with all tables for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _sample_deal_input() -> DealInput:
    return DealInput(
        name="Test Multifamily",
        asset_class=AssetClass.MULTIFAMILY,
        purchase_price=4_800_000,
        units=24,
        square_feet=22_000,
        closing_costs=0.01,
        immediate_capex=120_000,
        loan=LoanInput(
            ltv=0.70,
            interest_rate=0.0675,
            amortization_years=30,
            loan_type=LoanType.FIXED,
            origination_fee=0.01,
        ),
        operations=OperatingAssumptions(
            gross_scheduled_income=576_000,
            vacancy_rate=0.05,
            credit_loss_rate=0.01,
            other_income=14_400,
            property_taxes=72_000,
            insurance=18_000,
            management_fee_pct=0.05,
            maintenance_reserves=36_000,
            capex_reserves=24_000,
            utilities=12_000,
            other_expenses=8_400,
            rent_growth_rate=0.03,
            expense_growth_rate=0.02,
        ),
        exit=ExitAssumptions(
            hold_period_years=5,
            exit_cap_rate=0.055,
            selling_costs_pct=0.03,
            discount_rate=0.08,
        ),
    )


@pytest.fixture
def sample_deal_input():
    return _sample_deal_input()


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestSyncDealFromInput:
    def test_syncs_all_fields(self, sample_deal_input):
        deal = Deal(name="test", status=DealStatus.SCREENING)
        _sync_deal_from_input(deal, sample_deal_input)

        assert deal.purchase_price == 4_800_000
        assert deal.units == 24
        assert deal.square_feet == 22_000
        assert deal.market is None  # sample has no market
        assert deal.asset_class == "multifamily"

    def test_syncs_market(self, sample_deal_input):
        sample_deal_input.market = "Austin, TX"
        deal = Deal(name="test", status=DealStatus.SCREENING)
        _sync_deal_from_input(deal, sample_deal_input)
        assert deal.market == "Austin, TX"


class TestMakeDeal:
    def test_creates_deal_with_required_fields(self):
        deal = _make_deal("Test Deal", DealStatus.SCREENING)
        assert deal.name == "Test Deal"
        assert deal.status == DealStatus.SCREENING

    def test_creates_deal_with_all_fields(self):
        deal = _make_deal(
            "Full Deal",
            DealStatus.UNDERWRITING,
            asset_class="multifamily",
            market="Austin, TX",
            purchase_price=5_000_000,
            units=30,
            source="broker_email",
            tags=["value-add", "texas"],
        )
        assert deal.market == "Austin, TX"
        assert deal.purchase_price == 5_000_000
        assert deal.source == "broker_email"

    def test_portfolio_id_converts_to_uuid(self):
        uid = str(uuid.uuid4())
        deal = _make_deal("Test", DealStatus.SCREENING, portfolio_id=uid)
        assert deal.portfolio_id == uuid.UUID(uid)

    def test_portfolio_id_none_when_empty(self):
        deal = _make_deal("Test", DealStatus.SCREENING, portfolio_id=None)
        assert deal.portfolio_id is None


class TestRunUnderwriting:
    def test_returns_result_with_metrics(self, sample_deal_input):
        result = _run_underwriting(sample_deal_input)
        assert result.metrics.going_in_cap_rate > 0
        assert result.metrics.levered_irr > 0
        assert result.metrics.equity_multiple > 1
        assert len(result.pro_forma) == 5

    def test_computes_sensitivity(self, sample_deal_input):
        result = _run_underwriting(sample_deal_input)
        assert result.irr_sensitivity is not None
        assert result.coc_sensitivity is not None


class TestDealToDict:
    def test_basic_serialization(self):
        deal = Deal(
            id=uuid.uuid4(),
            name="Test",
            status=DealStatus.SCREENING,
            asset_class="multifamily",
            market="Austin",
        )
        d = _deal_to_dict(deal)
        assert d["name"] == "Test"
        assert d["status"] == "screening"
        assert d["market"] == "Austin"
        assert "primary_version" not in d
        assert "latest_results" not in d

    def test_with_version(self):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        version = DealVersion(
            id=uuid.uuid4(),
            version_number=1,
            label="V1",
            deal_input={"name": "test"},
            is_primary=True,
        )
        d = _deal_to_dict(deal, version)
        assert d["primary_version"]["version_number"] == 1
        assert d["primary_version"]["label"] == "V1"

    def test_with_results_deduplicates_by_type(self):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        r1 = AnalysisResult(
            id=uuid.uuid4(),
            result_type="underwriting",
            result_data={"metrics": {}},
        )
        r2 = AnalysisResult(
            id=uuid.uuid4(),
            result_type="underwriting",
            result_data={"metrics": {"old": True}},
        )
        d = _deal_to_dict(deal, results=[r1, r2])
        # Only the first (latest) per type is kept
        assert len(d["latest_results"]) == 1
        assert d["latest_results"]["underwriting"]["id"] == str(r1.id)


class TestResultTypeEnum:
    def test_values(self):
        assert ResultType.UNDERWRITING.value == "underwriting"
        assert ResultType.MEMO.value == "memo"
        assert ResultType.DUE_DILIGENCE.value == "due_diligence"


# ---------------------------------------------------------------------------
# Integration tests: database operations
# ---------------------------------------------------------------------------


class TestDealDB:
    @pytest.mark.asyncio
    async def test_create_and_read_deal(self, db_session):
        deal = Deal(
            id=uuid.uuid4(),
            name="Austin Arms",
            status=DealStatus.SCREENING,
            asset_class="multifamily",
            market="Austin, TX",
            purchase_price=4_800_000,
            units=24,
        )
        db_session.add(deal)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(Deal).where(Deal.name == "Austin Arms")
        )
        loaded = result.scalar_one()
        assert loaded.market == "Austin, TX"
        assert loaded.units == 24
        assert loaded.status == DealStatus.SCREENING

    @pytest.mark.asyncio
    async def test_soft_delete(self, db_session):
        deal = Deal(id=uuid.uuid4(), name="To Delete", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.commit()

        deal.soft_delete()
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(Deal).where(Deal.name == "To Delete", Deal.deleted_at.is_(None))
        )
        assert result.scalar_one_or_none() is None


class TestDealVersionDB:
    @pytest.mark.asyncio
    async def test_create_version_with_deal_input(self, db_session, sample_deal_input):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        version = DealVersion(
            id=uuid.uuid4(),
            deal_id=deal.id,
            version_number=1,
            label="Initial",
            deal_input=sample_deal_input.model_dump(),
            is_primary=True,
        )
        db_session.add(version)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(DealVersion).where(DealVersion.deal_id == deal.id)
        )
        loaded = result.scalar_one()
        assert loaded.version_number == 1
        assert loaded.is_primary is True
        assert loaded.deal_input["purchase_price"] == 4_800_000

    @pytest.mark.asyncio
    async def test_deal_input_roundtrips_through_json(
        self, db_session, sample_deal_input
    ):
        """DealInput survives serialization to JSONB and back."""
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        original_dump = sample_deal_input.model_dump()
        version = DealVersion(
            id=uuid.uuid4(),
            deal_id=deal.id,
            version_number=1,
            deal_input=original_dump,
            is_primary=True,
        )
        db_session.add(version)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(DealVersion).where(DealVersion.id == version.id)
        )
        loaded = result.scalar_one()

        # Validate it can be deserialized back to DealInput
        reconstructed = DealInput.model_validate(loaded.deal_input)
        assert reconstructed.purchase_price == sample_deal_input.purchase_price
        assert reconstructed.units == sample_deal_input.units
        assert reconstructed.operations.gross_scheduled_income == 576_000

    @pytest.mark.asyncio
    async def test_multiple_versions(self, db_session, sample_deal_input):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        for i in range(1, 4):
            v = DealVersion(
                id=uuid.uuid4(),
                deal_id=deal.id,
                version_number=i,
                deal_input=sample_deal_input.model_dump(),
                is_primary=(i == 3),
            )
            db_session.add(v)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(DealVersion)
            .where(DealVersion.deal_id == deal.id)
            .order_by(DealVersion.version_number)
        )
        versions = result.scalars().all()
        assert len(versions) == 3
        assert versions[0].is_primary is False
        assert versions[2].is_primary is True


class TestAnalysisResultDB:
    @pytest.mark.asyncio
    async def test_store_underwriting_result(self, db_session, sample_deal_input):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        version = DealVersion(
            id=uuid.uuid4(),
            deal_id=deal.id,
            version_number=1,
            deal_input=sample_deal_input.model_dump(),
            is_primary=True,
        )
        db_session.add(version)
        await db_session.flush()

        result = _run_underwriting(sample_deal_input)
        analysis = AnalysisResult(
            id=uuid.uuid4(),
            deal_id=deal.id,
            version_id=version.id,
            result_type=ResultType.UNDERWRITING.value,
            result_data=result.model_dump(),
        )
        db_session.add(analysis)
        await db_session.commit()

        from sqlalchemy import select

        loaded_result = await db_session.execute(
            select(AnalysisResult).where(AnalysisResult.deal_id == deal.id)
        )
        loaded = loaded_result.scalar_one()
        assert loaded.result_type == "underwriting"
        assert loaded.result_data["metrics"]["going_in_cap_rate"] > 0
        assert loaded.result_data["metrics"]["levered_irr"] > 0


class TestDocumentDB:
    @pytest.mark.asyncio
    async def test_create_document(self, db_session):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        doc = Document(
            id=uuid.uuid4(),
            deal_id=deal.id,
            filename="offering_memo.pdf",
            doc_type="om",
            content_type="application/pdf",
            file_size_bytes=1024000,
            storage_path="test-deal/abc123.pdf",
            storage_backend="local",
            parse_status=ParseStatus.PENDING,
        )
        db_session.add(doc)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(Document).where(Document.deal_id == deal.id)
        )
        loaded = result.scalar_one()
        assert loaded.filename == "offering_memo.pdf"
        assert loaded.parse_status == ParseStatus.PENDING

    @pytest.mark.asyncio
    async def test_parse_status_transitions(self, db_session):
        deal = Deal(id=uuid.uuid4(), name="Test", status=DealStatus.SCREENING)
        db_session.add(deal)
        await db_session.flush()

        doc = Document(
            id=uuid.uuid4(),
            deal_id=deal.id,
            filename="t12.pdf",
            doc_type="t12",
            storage_path="d/f.pdf",
            storage_backend="local",
            parse_status=ParseStatus.PENDING,
        )
        db_session.add(doc)
        await db_session.commit()

        doc.parse_status = ParseStatus.PROCESSING
        await db_session.commit()
        assert doc.parse_status == ParseStatus.PROCESSING

        doc.parse_status = ParseStatus.COMPLETED
        doc.parsed_data = {"net_operating_income": 250000}
        await db_session.commit()
        assert doc.parsed_data["net_operating_income"] == 250000


class TestPortfolioDB:
    @pytest.mark.asyncio
    async def test_create_portfolio_with_deals(self, db_session):
        portfolio = Portfolio(id=uuid.uuid4(), name="Fund I")
        db_session.add(portfolio)
        await db_session.flush()

        for i in range(3):
            deal = Deal(
                id=uuid.uuid4(),
                name=f"Deal {i}",
                status=DealStatus.SCREENING,
                portfolio_id=portfolio.id,
            )
            db_session.add(deal)
        await db_session.commit()

        from sqlalchemy import select, func

        count_result = await db_session.execute(
            select(func.count())
            .select_from(Deal)
            .where(Deal.portfolio_id == portfolio.id)
        )
        assert count_result.scalar_one() == 3
