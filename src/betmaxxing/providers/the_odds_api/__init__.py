"""The Odds API v4 adapter. Status: IMPLEMENTED_UNVERIFIED (no live call made)."""

from betmaxxing.providers.the_odds_api.client import (
    TheOddsApiAuthError,
    TheOddsApiClient,
    TheOddsApiError,
    effective_region_units,
    estimate_cost,
    parse_quota,
    redact,
)
from betmaxxing.providers.the_odds_api.mapping import (
    MARKET_MAP,
    UNSUPPORTED_BY_PROVIDER,
    MappingRejected,
    classify_sport,
    map_market,
)
from betmaxxing.providers.the_odds_api.provider import (
    PROVIDER_NAME,
    ResponseShape,
    TheOddsApiProvider,
)

__all__ = [
    "MARKET_MAP",
    "PROVIDER_NAME",
    "UNSUPPORTED_BY_PROVIDER",
    "MappingRejected",
    "ResponseShape",
    "TheOddsApiAuthError",
    "TheOddsApiClient",
    "TheOddsApiError",
    "TheOddsApiProvider",
    "classify_sport",
    "effective_region_units",
    "estimate_cost",
    "map_market",
    "parse_quota",
    "redact",
]
