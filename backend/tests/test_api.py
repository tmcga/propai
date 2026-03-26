"""
API integration tests for PropAI endpoints.

Tests the underwriting and utility endpoints (no ANTHROPIC_API_KEY required).
AI endpoints are tested separately in test_agents.py with mocked responses.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Root & Health
# ---------------------------------------------------------------------------


class TestRoot:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "PropAI"
        assert data["status"] == "operational"

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# Underwriting Endpoints
# ---------------------------------------------------------------------------


class TestUnderwriting:
    def test_sample_deal(self, client):
        resp = client.get("/api/underwrite/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "The Austin Arms — 24-Unit Multifamily"
        assert data["purchase_price"] == 4_800_000
        assert data["units"] == 24

    def test_sample_result(self, client):
        resp = client.get("/api/underwrite/sample/result")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deal_name"] == "The Austin Arms — 24-Unit Multifamily"
        assert data["purchase_price"] == 4_800_000
        assert "metrics" in data
        assert "pro_forma" in data

    def test_full_underwrite(self, client, sample_deal):
        resp = client.post("/api/underwrite", json=sample_deal.model_dump())
        assert resp.status_code == 200
        data = resp.json()
        assert data["deal_name"] == "Test Multifamily"
        assert data["metrics"]["going_in_cap_rate"] > 0
        assert data["metrics"]["levered_irr"] > 0
        assert data["metrics"]["equity_multiple"] > 1
        assert len(data["pro_forma"]) == 5  # 5-year hold

    def test_quick_underwrite(self, client, sample_deal):
        resp = client.post("/api/underwrite/quick", json=sample_deal.model_dump())
        assert resp.status_code == 200
        data = resp.json()
        assert "going_in_cap_rate" in data
        assert "levered_irr" in data
        assert "equity_multiple" in data

    def test_underwrite_invalid_input(self, client):
        resp = client.post("/api/underwrite", json={"bad": "data"})
        assert resp.status_code == 422  # Pydantic validation error

    def test_underwrite_result_has_sensitivity(self, client, sample_deal):
        resp = client.post("/api/underwrite", json=sample_deal.model_dump())
        data = resp.json()
        assert data["irr_sensitivity"] is not None
        assert data["coc_sensitivity"] is not None


# ---------------------------------------------------------------------------
# Screen Endpoints
# ---------------------------------------------------------------------------


class TestScreen:
    def test_screen_sample(self, client):
        resp = client.get("/api/screen/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verdict"] == "SOFT_GO"
        assert "estimated_cap_rate" in data


# ---------------------------------------------------------------------------
# LP Comms Endpoints
# ---------------------------------------------------------------------------


class TestLPComms:
    def test_lp_comms_sample(self, client):
        resp = client.get("/api/lp-comms/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["comm_type"] == "monthly_update"
        assert "body_markdown" in data
