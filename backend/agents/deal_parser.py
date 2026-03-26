"""
Natural Language Deal Parser

Converts free-text deal descriptions into structured DealInput objects
using Claude's function-calling / structured output capability.

This is the "magic" entry point that lets users type:
  "Analyze a 24-unit apartment in Austin, TX at $3.2M. Rents average $1,850/mo.
   70% LTV at 6.75%, 5-year hold. Exit at a 5.5 cap."

...and get back a fully populated DealInput ready for underwriting.

Claude extracts values, infers missing assumptions from market norms,
and flags anything it had to assume vs. what was explicitly stated.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from engine.financial.models import (
    DealInput,
    AssetClass,
    LoanInput,
    LoanType,
    OperatingAssumptions,
    ExitAssumptions,
    EquityStructure,
)

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result from the NL deal parser."""

    deal_input: Optional[DealInput] = None
    extracted_values: dict = field(default_factory=dict)  # What was explicitly stated
    assumed_values: dict = field(default_factory=dict)  # What was inferred/defaulted
    clarifications_needed: list[str] = field(default_factory=list)
    raw_extraction: dict = field(default_factory=dict)
    success: bool = False
    error: Optional[str] = None


# The JSON schema Claude should return
EXTRACTION_SCHEMA = {
    "name": "extract_deal",
    "description": "Extract real estate deal parameters from natural language input",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Deal name or property address"},
            "asset_class": {
                "type": "string",
                "enum": [
                    "sfr",
                    "small_multifamily",
                    "multifamily",
                    "office",
                    "retail",
                    "mixed_use",
                    "industrial",
                    "self_storage",
                    "str",
                    "ground_up",
                ],
                "description": "Property type",
            },
            "market": {
                "type": "string",
                "description": "City, state (e.g., 'Austin, TX')",
            },
            "purchase_price": {
                "type": "number",
                "description": "Purchase price in dollars",
            },
            "units": {
                "type": "integer",
                "description": "Number of units (multifamily)",
            },
            "square_feet": {
                "type": "number",
                "description": "Total rentable square footage",
            },
            "year_built": {"type": "integer", "description": "Year property was built"},
            # Financing
            "ltv": {"type": "number", "description": "Loan-to-value ratio (0.0–1.0)"},
            "interest_rate": {
                "type": "number",
                "description": "Annual interest rate (0.0–1.0)",
            },
            "amortization_years": {
                "type": "integer",
                "description": "Loan amortization in years",
            },
            "loan_type": {
                "type": "string",
                "enum": ["fixed", "interest_only", "io_then_amortizing"],
            },
            "io_period_years": {
                "type": "integer",
                "description": "IO period years if applicable",
            },
            # Revenue
            "gross_scheduled_income": {
                "type": "number",
                "description": "Annual gross rents at 100% occupancy",
            },
            "monthly_rent_per_unit": {
                "type": "number",
                "description": "Monthly rent per unit (used to compute GSI if units known)",
            },
            "vacancy_rate": {"type": "number", "description": "Vacancy rate (0.0–1.0)"},
            "other_income_annual": {
                "type": "number",
                "description": "Other annual income",
            },
            # Expenses
            "property_taxes_annual": {
                "type": "number",
                "description": "Annual property taxes",
            },
            "insurance_annual": {"type": "number", "description": "Annual insurance"},
            "management_fee_pct": {
                "type": "number",
                "description": "Management fee as % of EGI",
            },
            "maintenance_annual": {
                "type": "number",
                "description": "Annual maintenance/repairs",
            },
            "capex_annual": {"type": "number", "description": "Annual CapEx reserves"},
            "utilities_annual": {
                "type": "number",
                "description": "Annual utilities (owner-paid)",
            },
            # Growth
            "rent_growth_rate": {
                "type": "number",
                "description": "Annual rent growth rate",
            },
            "expense_growth_rate": {
                "type": "number",
                "description": "Annual expense growth rate",
            },
            # Exit
            "hold_period_years": {
                "type": "integer",
                "description": "Hold period in years",
            },
            "exit_cap_rate": {
                "type": "number",
                "description": "Exit cap rate (0.0–1.0)",
            },
            "selling_costs_pct": {
                "type": "number",
                "description": "Selling costs as % of price",
            },
            "discount_rate": {"type": "number", "description": "Discount rate for NPV"},
            # Equity structure
            "lp_equity_pct": {"type": "number", "description": "LP equity percentage"},
            "preferred_return": {
                "type": "number",
                "description": "LP preferred return rate",
            },
            # Metadata
            "explicitly_stated": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of field names that were explicitly stated in the input",
            },
            "assumed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of field names that were inferred or defaulted",
            },
            "clarifications_needed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Questions to ask the user to improve accuracy",
            },
        },
        "required": [
            "name",
            "asset_class",
            "purchase_price",
            "explicitly_stated",
            "assumed",
        ],
    },
}

PARSER_SYSTEM_PROMPT = """You are a real estate underwriting assistant that extracts deal parameters
from natural language descriptions.

Your job:
1. Extract every value explicitly stated in the input
2. Infer reasonable market-standard defaults for anything not stated
3. Flag what you assumed vs. what was explicit
4. Note anything you need clarified for a more accurate analysis

Default assumptions when not stated:
- Vacancy: 5% (residential), 8% (commercial)
- Credit loss: 1% (residential), 2% (commercial)
- Management fee: 5-8% of EGI (residential), 3-5% (commercial)
- Maintenance reserves: $100-150/unit/month (residential), $1.50-2.50/SF (commercial)
- CapEx reserves: $50-100/unit/month (newer assets), $150-200 (older)
- Insurance: roughly 0.5-1% of purchase price annually
- Property taxes: use 1-2% of value as rough estimate if not stated
- Expense growth: 2-3% annually
- Rent growth: 2-4% depending on market
- Hold period: 5 years if not stated
- LTV: 70% if not stated
- Amortization: 30 years
- Selling costs: 3% (residential), 2% (commercial)
- Discount rate: 8% as standard hurdle

For multifamily: compute GSI as (units × monthly_rent × 12) if monthly rent per unit is given.
Always express rates as decimals (0.065 not 6.5%).
"""


class DealParser:
    """
    Parses natural language deal descriptions into structured DealInput objects.

    Usage:
        parser = DealParser()
        result = await parser.parse(
            "24-unit apartment in Austin TX asking $4.8M. "
            "Average rents $2,000/mo. 70% LTV at 6.75%, 5yr hold, exit at 5.5 cap."
        )
        deal = result.deal_input
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client: Optional[anthropic.AsyncAnthropic] = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set.")
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def parse(self, text: str) -> ParseResult:
        """
        Parse a natural language deal description.

        Args:
            text: Free-form deal description. Examples:
                  "24-unit apartment in Austin at $4.8M, rents $2k/mo, 70% LTV"
                  "SFR rental at 123 Main St, Nashville TN. Listed at $425k.
                   3/2, 1400 SF, rents for $2,200/mo. Looking at 25% down."
                  "Analyze this office building: 15,000 SF, Chicago, $3M ask.
                   $28/SF NNN leases, 90% occupied, 6.5% going-in cap."

        Returns:
            ParseResult with .deal_input ready for underwriting
        """
        result = ParseResult()

        try:
            client = self._get_client()

            message = await self._call_api(client, text)

            # Extract tool use result
            tool_result = None
            for block in message.content:
                if block.type == "tool_use" and block.name == "extract_deal":
                    tool_result = block.input
                    break

            if not tool_result:
                result.error = "Claude did not return structured extraction."
                return result

            result.raw_extraction = tool_result
            result.extracted_values = {
                k: v
                for k in tool_result.get("explicitly_stated", [])
                if (v := tool_result.get(k)) is not None
            }
            result.assumed_values = {
                k: v
                for k in tool_result.get("assumed", [])
                if (v := tool_result.get(k)) is not None
            }
            result.clarifications_needed = tool_result.get("clarifications_needed", [])

            # Build DealInput from extracted values
            result.deal_input = self._build_deal_input(tool_result)
            result.success = True

        except anthropic.AuthenticationError:
            result.error = "Invalid ANTHROPIC_API_KEY. Check your .env configuration."
        except anthropic.APIConnectionError:
            result.error = (
                "Could not connect to Anthropic API. Check your internet connection."
            )
        except Exception as e:
            result.error = f"Parse failed: {str(e)}"
            logger.error("DealParser error", exc_info=True)

        return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            )
        ),
        reraise=True,
    )
    async def _call_api(self, client: anthropic.AsyncAnthropic, text: str):
        """Call the Anthropic API with retry logic for transient failures."""
        return await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=PARSER_SYSTEM_PROMPT,
            tools=[EXTRACTION_SCHEMA],
            tool_choice={"type": "tool", "name": "extract_deal"},
            messages=[
                {
                    "role": "user",
                    "content": f"Extract deal parameters from this description:\n\n{text}",
                }
            ],
        )

    def _build_deal_input(self, raw: dict) -> DealInput:
        """Convert raw Claude extraction into a validated DealInput."""

        purchase_price = float(raw["purchase_price"])

        # Compute GSI from monthly rent if units given
        gsi = raw.get("gross_scheduled_income")
        if gsi is None:
            monthly_rent = raw.get("monthly_rent_per_unit")
            units = raw.get("units")
            if monthly_rent and units:
                gsi = float(monthly_rent) * int(units) * 12
            else:
                raise ValueError(
                    "Could not determine gross scheduled income. "
                    "Please provide annual rent, monthly rent per unit, or unit count + rent."
                )

        # Expense estimates — use purchase price % as fallback
        property_taxes = raw.get("property_taxes_annual") or purchase_price * 0.015
        insurance = raw.get("insurance_annual") or purchase_price * 0.006
        maintenance = raw.get("maintenance_annual") or (
            (raw.get("units") or 0) * 1200  # $100/unit/mo default
            or gsi * 0.05
        )
        capex = raw.get("capex_annual") or (
            (raw.get("units") or 0) * 600  # $50/unit/mo default
            or 0.0
        )

        return DealInput(
            name=raw.get("name", "Untitled Deal"),
            asset_class=AssetClass(raw.get("asset_class", "multifamily")),
            purchase_price=purchase_price,
            units=raw.get("units"),
            square_feet=raw.get("square_feet"),
            year_built=raw.get("year_built"),
            market=raw.get("market"),
            closing_costs=0.01,
            immediate_capex=0.0,
            loan=LoanInput(
                ltv=float(raw.get("ltv", 0.70)),
                interest_rate=float(raw.get("interest_rate", 0.0675)),
                amortization_years=int(raw.get("amortization_years", 30)),
                loan_type=LoanType(raw.get("loan_type", "fixed")),
                io_period_years=int(raw.get("io_period_years", 0)),
                origination_fee=0.01,
            ),
            operations=OperatingAssumptions(
                gross_scheduled_income=float(gsi),
                vacancy_rate=float(raw.get("vacancy_rate", 0.05)),
                credit_loss_rate=0.01,
                other_income=float(raw.get("other_income_annual", 0.0)),
                property_taxes=float(property_taxes),
                insurance=float(insurance),
                management_fee_pct=float(raw.get("management_fee_pct", 0.05)),
                maintenance_reserves=float(maintenance),
                capex_reserves=float(capex),
                utilities=float(raw.get("utilities_annual", 0.0)),
                other_expenses=0.0,
                rent_growth_rate=float(raw.get("rent_growth_rate", 0.03)),
                expense_growth_rate=float(raw.get("expense_growth_rate", 0.02)),
            ),
            exit=ExitAssumptions(
                hold_period_years=int(raw.get("hold_period_years", 5)),
                exit_cap_rate=float(raw.get("exit_cap_rate", 0.055)),
                selling_costs_pct=float(raw.get("selling_costs_pct", 0.03)),
                discount_rate=float(raw.get("discount_rate", 0.08)),
            ),
            equity_structure=EquityStructure(
                lp_equity_pct=float(raw.get("lp_equity_pct", 0.90)),
                gp_equity_pct=1.0 - float(raw.get("lp_equity_pct", 0.90)),
                preferred_return=float(raw.get("preferred_return", 0.08)),
            )
            if raw.get("lp_equity_pct")
            else None,
        )
