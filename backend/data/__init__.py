"""
PropAI Data Layer — external API clients for market intelligence.

All clients are async, implement Redis caching, and degrade gracefully
when APIs are unavailable or keys are not configured.
"""

from .census import CensusClient
from .fred import FREDClient
from .hud import HUDClient
from .zillow import ZillowClient
from .market_service import MarketService

__all__ = [
    "CensusClient",
    "FREDClient",
    "HUDClient",
    "ZillowClient",
    "MarketService",
]
