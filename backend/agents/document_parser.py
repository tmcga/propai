"""
Document Parser Agent
---------------------
Parses real estate documents (Offering Memoranda, T-12s, Rent Rolls)
into structured data that feeds directly into the underwriting engine.

Supports:
  - PDF text extraction (via pdfminer.six, falls back to raw text)
  - Offering Memorandum → DealInput
  - Trailing-12 (T-12) income statement → OperatingAssumptions
  - Rent Roll → unit mix, occupancy, scheduled vs. actual income

Strategy: extract text first, then ask Claude to parse it.
Claude is specifically prompted to flag when numbers are missing
vs. present but ambiguous — so the caller knows what to verify.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic, APITimeoutError, RateLimitError, InternalServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

from engine.financial.models import (
    AssetClass,
    DealInput,
    ExitAssumptions,
    LoanInput,
    OperatingAssumptions,
)


# ── Text extraction ───────────────────────────────────────────────────────

def extract_text_from_pdf(path: str | Path) -> str:
    """Extract raw text from a PDF file. Requires pdfminer.six."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError:
        raise ImportError(
            "pdfminer.six is required for PDF parsing. "
            "Install with: pip install pdfminer.six"
        )
    except Exception as e:
        raise ValueError(f"Could not extract text from PDF: {e}") from e


def clean_text(text: str) -> str:
    """Normalize extracted PDF text for LLM consumption."""
    # Collapse excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    # Remove null bytes and control chars
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text.strip()


# ── Output types ──────────────────────────────────────────────────────────

@dataclass
class RentRollUnit:
    unit_id: str
    unit_type: str          # "1BR/1BA", "Studio", etc.
    square_feet: float | None
    market_rent: float      # monthly asking rent
    actual_rent: float      # monthly rent actually collected (0 if vacant)
    occupied: bool
    lease_end: str | None   # "2025-06", "MTM", etc.
    notes: str = ""


@dataclass
class RentRollSummary:
    total_units: int
    occupied_units: int
    physical_vacancy: float
    scheduled_income_annual: float      # market rents × 12
    actual_income_annual: float         # actual rents × 12 (occupied only)
    loss_to_lease: float                # scheduled - actual (occupied units)
    unit_mix: list[dict]                # {"type": "1BR", "count": 12, "avg_rent": 1800}
    units: list[RentRollUnit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class T12Summary:
    """Parsed trailing-12 income statement."""
    # Income
    gross_scheduled_income: float
    vacancy_loss: float
    concessions: float
    other_income: float
    effective_gross_income: float

    # Expenses (all annual)
    property_taxes: float
    insurance: float
    management_fees: float
    repairs_maintenance: float
    utilities: float
    payroll: float
    administrative: float
    marketing: float
    other_expenses: float
    total_expenses: float

    # NOI
    net_operating_income: float

    # Flags
    annualized: bool = False        # True if only partial year was provided
    months_of_data: int = 12
    red_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    doc_type: str                           # "om", "t12", "rent_roll", "mixed"
    deal_input: DealInput | None            # populated for OM and mixed
    t12: T12Summary | None                  # populated for T12 and OM
    rent_roll: RentRollSummary | None       # populated for rent rolls
    extracted_values: dict[str, Any] = field(default_factory=dict)
    assumed_values: dict[str, Any] = field(default_factory=dict)
    missing_critical: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    confidence: str = "MEDIUM"             # HIGH / MEDIUM / LOW
    raw_text_chars: int = 0


# ── System prompts ────────────────────────────────────────────────────────

OM_SYSTEM = """You are an expert real estate analyst who specializes in parsing
Offering Memorandums (OMs) and investment summaries into structured data.

Your job is to extract every financial number present in the document with
maximum accuracy. When a number is not in the document, say so explicitly —
do NOT invent or estimate numbers. Flag any numbers that look manipulated
(e.g. NOI that implies an unrealistic expense ratio, rent rolls that don't
match stated income, etc.)."""

T12_SYSTEM = """You are an expert real estate analyst specializing in analyzing
Trailing-12 Month (T-12) operating statements.

Extract all income and expense line items. Be alert to:
- Missing expense categories (a real T-12 should have taxes, insurance, management, maintenance)
- Unusually low expenses (sellers sometimes exclude items pre-sale)
- Partial-year statements being presented as full-year
- Management fees that don't appear (common when owner self-manages — add a market-rate estimate)
- One-time items that inflate NOI"""

RENT_ROLL_SYSTEM = """You are an expert real estate analyst specializing in
analyzing rent rolls. Extract unit-level and summary data.

Flag:
- Units with below-market rents (possible long-term tenants or below-market leases)
- High month-to-month (MTM) concentrations (rollover risk)
- Vacant units
- Loss-to-lease (difference between market and in-place rents)
- Lease expirations concentrated in the near term"""


class DocumentParser:

    def __init__(self) -> None:
        self.client = AsyncAnthropic()

    async def parse_bytes(self, content: bytes, doc_type_hint: str = "auto") -> ParsedDocument:
        """Parse raw bytes (PDF or text). Handles PDF extraction automatically."""
        try:
            text = content.decode("utf-8")
            return await self.parse_text(clean_text(text), doc_type_hint)
        except UnicodeDecodeError:
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                return await self.parse_file(tmp_path, doc_type_hint)
            finally:
                os.unlink(tmp_path)

    async def parse_file(self, path: str | Path, doc_type_hint: str = "auto") -> ParsedDocument:
        """Parse a document file (PDF or txt)."""
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            raw_text = extract_text_from_pdf(path)
        else:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        return await self.parse_text(clean_text(raw_text), doc_type_hint)

    async def parse_text(self, text: str, doc_type_hint: str = "auto") -> ParsedDocument:
        """Parse raw document text. Detects document type if hint is 'auto'."""
        # Truncate to ~80k chars to stay within context limits
        text = text[:80_000]
        doc_type = doc_type_hint if doc_type_hint != "auto" else self._detect_doc_type(text)

        if doc_type == "t12":
            return await self._parse_t12(text)
        elif doc_type == "rent_roll":
            return await self._parse_rent_roll(text)
        else:
            return await self._parse_om(text)

    # ── Document type detection ───────────────────────────────────────────

    def _detect_doc_type(self, text: str) -> str:
        text_lower = text.lower()
        t12_signals = ["trailing 12", "t-12", "t12", "income statement", "profit and loss", "p&l"]
        rr_signals = ["rent roll", "unit mix", "unit #", "unit id", "lease expir", "market rent"]
        om_signals = ["offering memorandum", "investment summary", "executive summary", "cap rate"]

        t12_score = sum(1 for s in t12_signals if s in text_lower)
        rr_score = sum(1 for s in rr_signals if s in text_lower)
        om_score = sum(1 for s in om_signals if s in text_lower)

        if t12_score >= rr_score and t12_score >= om_score:
            return "t12"
        if rr_score > t12_score and rr_score >= om_score:
            return "rent_roll"
        return "om"

    # ── OM Parser ─────────────────────────────────────────────────────────

    async def _parse_om(self, text: str) -> ParsedDocument:
        schema = {
            "doc_type": "om",
            "property": {
                "name": "string or null",
                "address": "string or null",
                "city_state": "string or null",
                "asset_class": "multifamily|office|retail|industrial|mixed_use|sfr|self_storage|str|development",
                "units": "integer or null",
                "square_feet": "number or null",
                "year_built": "integer or null",
                "year_renovated": "integer or null",
            },
            "pricing": {
                "asking_price": "number or null",
                "price_per_unit": "number or null",
                "price_per_sf": "number or null",
            },
            "income": {
                "gross_scheduled_income": "annual number or null",
                "vacancy_rate": "decimal (0.05 = 5%) or null",
                "other_income_annual": "number or null",
                "effective_gross_income": "annual number or null",
            },
            "expenses": {
                "property_taxes": "annual number or null",
                "insurance": "annual number or null",
                "management_fee_pct": "decimal or null",
                "maintenance_repairs": "annual number or null",
                "capex_reserves": "annual number or null",
                "utilities": "annual number or null",
                "payroll": "annual number or null",
                "total_expenses": "annual number or null",
            },
            "noi": "annual number or null",
            "cap_rate": "decimal or null",
            "financing": {
                "suggested_ltv": "decimal or null",
                "suggested_loan_amount": "number or null",
            },
            "assumed_values": {
                "description": "object with keys for any values NOT in document but applied as defaults"
            },
            "missing_critical": ["list of critical numbers NOT present in document"],
            "red_flags": ["list of anomalies or concerns found in the document"],
            "confidence": "HIGH|MEDIUM|LOW",
        }

        content = f"""Parse this offering memorandum and return structured JSON matching this schema:

{json.dumps(schema, indent=2)}

DOCUMENT TEXT:
{text}

Return ONLY valid JSON. No markdown, no commentary outside the JSON."""
        response = await self._call_api("claude-sonnet-4-6", 4096, OM_SYSTEM, content)

        raw = self._strip_fences(response.content[0].text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("DocumentParser: failed to parse OM JSON response")
            return ParsedDocument(doc_type="om", deal_input=None, t12=None, rent_roll=None,
                                  confidence="LOW", red_flags=["AI response could not be parsed"])
        return self._build_om_result(data, len(text))

    def _build_om_result(self, data: dict, text_chars: int) -> ParsedDocument:
        prop = data.get("property", {})
        pricing = data.get("pricing", {})
        income = data.get("income", {})
        expenses = data.get("expenses", {})

        purchase_price = pricing.get("asking_price") or 0
        gsi = income.get("gross_scheduled_income") or 0

        deal_input = None
        if purchase_price and gsi:
            try:
                deal_input = DealInput(
                    name=prop.get("name") or f"{prop.get('city_state', 'Unknown')} Property",
                    asset_class=prop.get("asset_class", "multifamily"),
                    purchase_price=purchase_price,
                    units=prop.get("units"),
                    square_feet=prop.get("square_feet"),
                    market=prop.get("city_state") or prop.get("address") or "Unknown",
                    closing_costs=0.01,
                    immediate_capex=0,
                    loan=LoanInput(
                        ltv=0.70,
                        interest_rate=0.0675,
                        amortization_years=30,
                        loan_type="fixed",
                        origination_fee=0.01,
                    ),
                    operations=OperatingAssumptions(
                        gross_scheduled_income=gsi,
                        vacancy_rate=income.get("vacancy_rate") or 0.05,
                        credit_loss_rate=0.005,
                        other_income=income.get("other_income_annual") or 0,
                        property_taxes=expenses.get("property_taxes") or purchase_price * 0.015,
                        insurance=expenses.get("insurance") or purchase_price * 0.004,
                        management_fee_pct=expenses.get("management_fee_pct") or 0.05,
                        maintenance_reserves=expenses.get("maintenance_repairs") or 0,
                        capex_reserves=expenses.get("capex_reserves") or 0,
                        utilities=expenses.get("utilities") or 0,
                        other_expenses=0,
                        rent_growth_rate=0.03,
                        expense_growth_rate=0.02,
                    ),
                    exit=ExitAssumptions(
                        hold_period_years=5,
                        exit_cap_rate=(data.get("cap_rate") or 0.055) + 0.005,
                        selling_costs_pct=0.03,
                        discount_rate=0.08,
                    ),
                )
            except Exception:
                pass  # Partial data — deal_input stays None

        return ParsedDocument(
            doc_type="om",
            deal_input=deal_input,
            t12=None,
            rent_roll=None,
            extracted_values=data,
            assumed_values=data.get("assumed_values", {}),
            missing_critical=data.get("missing_critical", []),
            red_flags=data.get("red_flags", []),
            confidence=data.get("confidence", "MEDIUM"),
            raw_text_chars=text_chars,
        )

    # ── T-12 Parser ───────────────────────────────────────────────────────

    async def _parse_t12(self, text: str) -> ParsedDocument:
        content = f"""Parse this T-12 operating statement into structured JSON:

{{
  "months_of_data": 12,
  "annualized": false,
  "income": {{
    "gross_scheduled_income": null,
    "vacancy_loss": null,
    "concessions": null,
    "other_income": null,
    "effective_gross_income": null
  }},
  "expenses": {{
    "property_taxes": null,
    "insurance": null,
    "management_fees": null,
    "repairs_maintenance": null,
    "utilities": null,
    "payroll": null,
    "administrative": null,
    "marketing": null,
    "other_expenses": null,
    "total_expenses": null
  }},
  "net_operating_income": null,
  "red_flags": [],
  "notes": []
}}

DOCUMENT TEXT:
{text}

Return ONLY valid JSON."""
        response = await self._call_api("claude-sonnet-4-6", 3000, T12_SYSTEM, content)

        raw = self._strip_fences(response.content[0].text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("DocumentParser: failed to parse T-12 JSON response")
            return ParsedDocument(doc_type="t12", deal_input=None, t12=None, rent_roll=None,
                                  confidence="LOW", red_flags=["AI response could not be parsed"])
        inc = data.get("income", {})
        exp = data.get("expenses", {})

        t12 = T12Summary(
            gross_scheduled_income=inc.get("gross_scheduled_income") or 0,
            vacancy_loss=inc.get("vacancy_loss") or 0,
            concessions=inc.get("concessions") or 0,
            other_income=inc.get("other_income") or 0,
            effective_gross_income=inc.get("effective_gross_income") or 0,
            property_taxes=exp.get("property_taxes") or 0,
            insurance=exp.get("insurance") or 0,
            management_fees=exp.get("management_fees") or 0,
            repairs_maintenance=exp.get("repairs_maintenance") or 0,
            utilities=exp.get("utilities") or 0,
            payroll=exp.get("payroll") or 0,
            administrative=exp.get("administrative") or 0,
            marketing=exp.get("marketing") or 0,
            other_expenses=exp.get("other_expenses") or 0,
            total_expenses=exp.get("total_expenses") or 0,
            net_operating_income=data.get("net_operating_income") or 0,
            annualized=data.get("annualized", False),
            months_of_data=data.get("months_of_data", 12),
            red_flags=data.get("red_flags", []),
            notes=data.get("notes", []),
        )

        return ParsedDocument(
            doc_type="t12",
            deal_input=None,
            t12=t12,
            rent_roll=None,
            extracted_values=data,
            missing_critical=[],
            red_flags=t12.red_flags,
            confidence="HIGH" if t12.net_operating_income > 0 else "LOW",
            raw_text_chars=len(text),
        )

    # ── Rent Roll Parser ──────────────────────────────────────────────────

    async def _parse_rent_roll(self, text: str) -> ParsedDocument:
        content = f"""Parse this rent roll into structured JSON:

{{
  "total_units": null,
  "occupied_units": null,
  "unit_mix": [
    {{"type": "1BR/1BA", "count": 0, "avg_market_rent": 0, "avg_actual_rent": 0, "sq_ft": null}}
  ],
  "units": [
    {{
      "unit_id": "101",
      "unit_type": "1BR/1BA",
      "square_feet": null,
      "market_rent": 0,
      "actual_rent": 0,
      "occupied": true,
      "lease_end": "2025-06",
      "notes": ""
    }}
  ],
  "summary": {{
    "scheduled_income_annual": null,
    "actual_income_annual": null,
    "loss_to_lease_annual": null,
    "physical_vacancy_pct": null,
    "mtm_count": null,
    "near_term_expirations_90d": null
  }},
  "red_flags": [],
  "notes": []
}}

DOCUMENT TEXT:
{text}

Return ONLY valid JSON. If the rent roll has many units, summarize the units array to a representative sample plus accurate aggregate summary."""
        response = await self._call_api("claude-sonnet-4-6", 4096, RENT_ROLL_SYSTEM, content)

        raw = self._strip_fences(response.content[0].text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("DocumentParser: failed to parse rent roll JSON response")
            return ParsedDocument(doc_type="rent_roll", deal_input=None, t12=None, rent_roll=None,
                                  confidence="LOW", red_flags=["AI response could not be parsed"])
        summary_data = data.get("summary", {})

        total = data.get("total_units") or 0
        occupied = data.get("occupied_units") or 0
        vacancy = (total - occupied) / total if total > 0 else 0

        rent_roll = RentRollSummary(
            total_units=total,
            occupied_units=occupied,
            physical_vacancy=summary_data.get("physical_vacancy_pct") or vacancy,
            scheduled_income_annual=summary_data.get("scheduled_income_annual") or 0,
            actual_income_annual=summary_data.get("actual_income_annual") or 0,
            loss_to_lease=summary_data.get("loss_to_lease_annual") or 0,
            unit_mix=data.get("unit_mix", []),
            units=[
                RentRollUnit(
                    unit_id=u.get("unit_id", ""),
                    unit_type=u.get("unit_type", ""),
                    square_feet=u.get("square_feet"),
                    market_rent=u.get("market_rent", 0),
                    actual_rent=u.get("actual_rent", 0),
                    occupied=u.get("occupied", True),
                    lease_end=u.get("lease_end"),
                    notes=u.get("notes", ""),
                )
                for u in data.get("units", [])
            ],
            notes=data.get("notes", []),
        )

        return ParsedDocument(
            doc_type="rent_roll",
            deal_input=None,
            t12=None,
            rent_roll=rent_roll,
            extracted_values=data,
            red_flags=data.get("red_flags", []),
            confidence="HIGH" if total > 0 else "LOW",
            raw_text_chars=len(text),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((APITimeoutError, RateLimitError, InternalServerError)),
        reraise=True,
    )
    async def _call_api(self, model: str, max_tokens: int, system: str, content: str):
        return await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        return text.strip()
