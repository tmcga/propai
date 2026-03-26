"""
Agent tests with mocked Anthropic API responses.

Tests the agent classes without requiring an API key by mocking
the Anthropic client's messages.create() method.
"""

import sys
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.deal_screener import DealScreener, ScreenInput
from agents.document_parser import DocumentParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(text: str):
    """Create a mock Anthropic message response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def _make_tool_message(tool_name: str, tool_input: dict):
    """Create a mock Anthropic tool_use message response."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    msg = MagicMock()
    msg.content = [block]
    return msg


# ---------------------------------------------------------------------------
# DealScreener Tests
# ---------------------------------------------------------------------------

class TestDealScreener:
    @pytest.fixture
    def screen_input(self):
        return ScreenInput(
            asset_class="multifamily",
            purchase_price=4_800_000,
            market="Austin, TX",
            gross_scheduled_income=576_000,
            units=24,
            avg_unit_rent=2_000,
            vacancy_rate=0.05,
            ltv=0.70,
            interest_rate=0.0675,
            hold_period_years=5,
        )

    def test_math_pass(self, screen_input):
        """Math pass should compute metrics without AI."""
        screener = DealScreener()
        result = screener._math_pass(screen_input)

        assert result["cap_rate"] > 0
        assert result["dscr"] > 0
        assert result["coc"] > 0
        assert result["grm"] > 0
        assert result["price_per_unit"] == 200_000

    @pytest.mark.asyncio
    async def test_screen_with_mocked_ai(self, screen_input):
        """Full screen with mocked AI response."""
        ai_response = json.dumps({
            "verdict": "SOFT_GO",
            "confidence": "MEDIUM",
            "headline": "Deal pencils at target metrics.",
            "strengths": ["Strong market", "Good basis"],
            "concerns": ["Supply risk"],
            "missing_info": [],
            "full_reasoning": "The deal looks reasonable.",
        })

        screener = DealScreener()
        screener._call_api = AsyncMock(return_value=_make_message(ai_response))

        verdict = await screener.screen(screen_input)
        assert verdict.verdict == "SOFT_GO"
        assert verdict.confidence == "MEDIUM"
        assert len(verdict.strengths) == 2
        assert verdict.estimated_cap_rate > 0

    @pytest.mark.asyncio
    async def test_screen_handles_malformed_json(self, screen_input):
        """Should gracefully handle unparseable AI response."""
        screener = DealScreener()
        screener._call_api = AsyncMock(return_value=_make_message("not valid json {{{"))

        verdict = await screener.screen(screen_input)
        assert verdict.confidence == "LOW"
        assert "AI response could not be parsed" in verdict.concerns[0]


# ---------------------------------------------------------------------------
# DocumentParser Tests
# ---------------------------------------------------------------------------

class TestDocumentParser:
    def test_detect_doc_type_t12(self):
        parser = DocumentParser()
        assert parser._detect_doc_type("Trailing 12 month income statement P&L") == "t12"

    def test_detect_doc_type_rent_roll(self):
        parser = DocumentParser()
        assert parser._detect_doc_type("Rent roll unit # lease expiration market rent") == "rent_roll"

    def test_detect_doc_type_om(self):
        parser = DocumentParser()
        assert parser._detect_doc_type("Offering memorandum executive summary cap rate") == "om"

    @pytest.mark.asyncio
    async def test_parse_t12_mocked(self):
        """Parse T-12 with mocked AI response."""
        t12_json = json.dumps({
            "months_of_data": 12,
            "annualized": False,
            "income": {
                "gross_scheduled_income": 576000,
                "vacancy_loss": 28800,
                "concessions": 0,
                "other_income": 14400,
                "effective_gross_income": 561600,
            },
            "expenses": {
                "property_taxes": 72000,
                "insurance": 18000,
                "management_fees": 28080,
                "repairs_maintenance": 36000,
                "utilities": 12000,
                "payroll": 0,
                "administrative": 2400,
                "marketing": 1200,
                "other_expenses": 8400,
                "total_expenses": 178080,
            },
            "net_operating_income": 383520,
            "red_flags": [],
            "notes": [],
        })

        parser = DocumentParser()
        parser._call_api = AsyncMock(return_value=_make_message(t12_json))

        result = await parser.parse_text("sample T-12 text", "t12")
        assert result.doc_type == "t12"
        assert result.t12 is not None
        assert result.t12.net_operating_income == 383520
        assert result.t12.gross_scheduled_income == 576000
        assert result.confidence == "HIGH"
