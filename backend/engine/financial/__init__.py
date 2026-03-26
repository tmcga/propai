"""
PropAI Financial Engine
=======================
Core underwriting, DCF, and returns analysis for real estate investment.
Supports: SFR, Multifamily, Commercial, Industrial, STR, Ground-Up Development
"""

from .models import (
    AssetClass,
    DealInput,
    LoanInput,
    LoanType,
    OperatingAssumptions,
    ExitAssumptions,
    EquityStructure,
    UnderwritingResult,
    ProFormaYear,
    ReturnMetrics,
    SensitivityTable,
)
from .proforma import ProFormaEngine
from .dcf import DCFEngine
from .waterfall import WaterfallEngine

__all__ = [
    "AssetClass",
    "DealInput",
    "LoanType",
    "LoanInput",
    "OperatingAssumptions",
    "ExitAssumptions",
    "EquityStructure",
    "UnderwritingResult",
    "ProFormaYear",
    "ReturnMetrics",
    "SensitivityTable",
    "ProFormaEngine",
    "DCFEngine",
    "WaterfallEngine",
]
