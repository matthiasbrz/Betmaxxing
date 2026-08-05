"""HTTP client for The Odds API v4.

Two responsibilities that are worth separating from the mapping logic:

**The key never leaks.** It travels as a query parameter, which means it would
otherwise appear in every logged URL, every exception message and every captured
fixture. :func:`redact` is applied to any URL before it reaches a log or an
exception, and :class:`TheOddsApiClient` raises errors carrying redacted URLs
only.

**Spending is bounded before it happens.** Credit cost is estimated *before* the
call and checked against the configured budget, so a misconfigured scan cannot
quietly consume a month of quota. Quota headers are read back from every
response so the real figure replaces the estimate.

Nothing here interprets odds; that is :mod:`betmaxxing.providers.the_odds_api.mapping`.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from betmaxxing.providers.base import (
    BudgetExceeded,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderUnavailable,
    QuotaInfo,
)

logger = logging.getLogger("betmaxxing.the_odds_api")

_API_KEY_PATTERN = re.compile(r"(apiKey=)[^&\s]+", re.IGNORECASE)

#: Quota headers documented for v4. Absent on some error responses.
HEADER_REMAINING = "x-requests-remaining"
HEADER_USED = "x-requests-used"
HEADER_LAST = "x-requests-last"

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 30.0


def redact(text: str) -> str:
    """Replace any ``apiKey=...`` with a placeholder.

    Applied to URLs before logging and before they enter an exception message.
    """
    return _API_KEY_PATTERN.sub(r"\1***REDACTED***", text)


class TheOddsApiError(ProviderError):
    """A request failed. The message never contains the key."""


class TheOddsApiAuthError(ProviderUnavailable):
    """401/403 — the key is missing, invalid, or lacks the plan for this call."""


@dataclass(frozen=True, slots=True)
class ApiResponse:
    payload: Any
    quota: QuotaInfo


def parse_quota(headers: Any) -> QuotaInfo:
    """Read quota headers, tolerating their absence."""

    def _int(name: str) -> int | None:
        raw = headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return QuotaInfo(
        remaining=_int(HEADER_REMAINING),
        used=_int(HEADER_USED),
        last_cost=_int(HEADER_LAST),
    )


def estimate_cost(*, markets: int, regions: int) -> int:
    """Estimated credit cost of one odds call.

    The published v4 rule is ``markets x regions`` (so 1 for a single-market,
    single-region call). Treated strictly as an **upper bound** for the budget
    guard: the authoritative figure is ``x-requests-last``, read back from the
    response and used to update the spend counter.
    """
    return max(1, markets) * max(1, regions)


class TheOddsApiClient:
    """Thin, budget-aware HTTP wrapper."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        budget_per_scan: int = 50,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        if not api_key:
            raise TheOddsApiAuthError(
                "BETMAXXING_THE_ODDS_API_KEY est vide — aucun appel n'est tenté."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._budget = budget_per_scan
        self._spent = 0
        self._transport = transport
        self._sleep = sleep
        self._quota = QuotaInfo()

    # -- budget -------------------------------------------------------------
    @property
    def credits_spent(self) -> int:
        return self._spent

    @property
    def quota(self) -> QuotaInfo:
        return self._quota

    def _check_budget(self, cost: int) -> None:
        if self._spent + cost > self._budget:
            raise BudgetExceeded(
                f"budget de {self._budget} crédits par scan dépassé "
                f"({self._spent} consommés, {cost} demandés) — appel refusé."
            )

    # -- requests -----------------------------------------------------------
    def get(self, path: str, params: dict[str, Any] | None = None, *, cost: int = 1) -> ApiResponse:
        """GET with retries, budget guard and redacted diagnostics."""
        self._check_budget(cost)
        url = f"{self._base_url}/{path.lstrip('/')}"
        query = {**(params or {}), "apiKey": self._api_key}

        attempt = 0
        while True:
            attempt += 1
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                    response = client.get(url, params=query)
            except httpx.TimeoutException:
                if attempt > self._max_retries:
                    raise TheOddsApiError(
                        f"timeout après {attempt} tentative(s) sur {redact(url)}"
                    ) from None
                self._backoff(attempt, None)
                continue
            except httpx.TransportError as exc:
                # DNS / connection failures. The message may contain the URL.
                if attempt > self._max_retries:
                    raise TheOddsApiError(
                        f"erreur de transport sur {redact(url)}: {redact(str(exc))}"
                    ) from None
                self._backoff(attempt, None)
                continue

            self._quota = parse_quota(response.headers)
            self._spent += self._quota.last_cost or cost

            if response.status_code in (401, 403):
                raise TheOddsApiAuthError(
                    f"authentification refusée ({response.status_code}) sur "
                    f"{redact(str(response.url))} — vérifiez la clé et le plan."
                )
            if response.status_code == 429:
                if attempt > self._max_retries:
                    raise ProviderQuotaExceeded(
                        f"quota/rate limit atteint sur {redact(str(response.url))}"
                    )
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code in RETRYABLE_STATUS:
                if attempt > self._max_retries:
                    raise TheOddsApiError(
                        f"erreur {response.status_code} persistante sur {redact(str(response.url))}"
                    )
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code == 404:
                raise TheOddsApiError(f"ressource introuvable : {redact(str(response.url))}")
            if response.status_code == 422:
                raise TheOddsApiError(
                    f"requête invalide (422) sur {redact(str(response.url))} — "
                    "paramètre sport/market/region probablement non supporté."
                )
            if response.status_code >= 400:
                raise TheOddsApiError(
                    f"erreur {response.status_code} sur {redact(str(response.url))}"
                )

            try:
                payload = response.json()
            except ValueError:
                raise TheOddsApiError(
                    f"réponse JSON invalide depuis {redact(str(response.url))}"
                ) from None

            return ApiResponse(payload=payload, quota=self._quota)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        """Honour ``Retry-After`` when present, else exponential with jitter."""
        if retry_after:
            try:
                self._sleep(min(float(retry_after), MAX_BACKOFF_SECONDS))
                return
            except (TypeError, ValueError):
                pass
        delay = min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
        self._sleep(delay * (0.5 + random.random() / 2.0))
