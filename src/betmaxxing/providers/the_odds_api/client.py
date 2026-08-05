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

#: Transport failures that prove the request never reached the provider: the
#: connection was never established, or no connection was ever obtained. Nothing
#: was served, so nothing was billed, and the reservation is released.
NEVER_SENT: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.LocalProtocolError,
    httpx.UnsupportedProtocol,
    httpx.InvalidURL,
)


def may_have_been_billed(error: BaseException) -> bool:
    """Whether this failure leaves the provider's billing in doubt.

    The previous tranche released the reservation for *every* transport error and
    described that as "no response arrived, so no credit was consumed". That is
    only true when the request never left. A **read** timeout means the request
    was sent and the answer was late — the provider may well have served and
    billed it. A write error means we stopped mid-send, which the far end may
    already have completed.

    So the split is by *evidence*, not by exception family: only the failures
    listed in :data:`NEVER_SENT` are free. Everything else stays charged at its
    estimate, because under-counting spend is the one direction a budget must
    never err in.
    """
    if isinstance(error, NEVER_SENT):
        return False
    return isinstance(error, httpx.TransportError)


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
        budget_ledger: Any = None,
        provider_name: str = "the_odds_api",
        now: Any = None,
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
        #: Durable, cross-process daily ceiling. ``None`` keeps the per-scan
        #: guard only, which is all a unit test of the client itself needs.
        self._ledger = budget_ledger
        self._provider_name = provider_name
        self._now = now

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

    def _reserve(self, cost: int, request: str) -> int | None:
        """Authorise one attempt against both ceilings, before it is made."""
        if self._ledger is None:
            self._check_budget(cost)
            return None
        from betmaxxing.domain.timeutil import utc_now

        return int(
            self._ledger.reserve(
                provider=self._provider_name,
                cost=cost,
                request=request,
                now=self._now or utc_now(),
                scan_spent=self._spent,
                scan_budget=self._budget,
            )
        )

    # -- requests -----------------------------------------------------------
    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cost: int = 1,
        billable: bool = True,
    ) -> ApiResponse:
        """GET with retries, budget guard and redacted diagnostics.

        The budget is checked **per attempt**, not once per call. A retry is a
        second request that costs credits exactly like the first, so it has to
        pass the same gate; checking only on entry let ``max_retries`` multiply
        the configured ceiling.

        ``billable=False`` is reserved for the endpoints v4 documents as free —
        today only ``/sports`` discovery. Such a call takes no reservation and
        does not move the spend counter, because charging it would make the
        ceiling refuse work it should have allowed.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        query = {**(params or {}), "apiKey": self._api_key}

        attempt = 0
        while True:
            attempt += 1
            reservation = self._reserve(cost, path) if billable else None
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                    response = client.get(url, params=query)
            except httpx.TimeoutException as exc:
                # A *connect* timeout never reached the provider; a *read* or
                # *write* timeout may have. Only the former is free.
                self._settle_failure(reservation, exc, cost)
                if attempt > self._max_retries:
                    raise TheOddsApiError(
                        f"timeout ({type(exc).__name__}) après {attempt} tentative(s) "
                        f"sur {redact(url)}"
                    ) from None
                self._backoff(attempt, None)
                continue
            except httpx.TransportError as exc:
                # The message may contain the URL, so it is redacted.
                self._settle_failure(reservation, exc, cost)
                if attempt > self._max_retries:
                    raise TheOddsApiError(
                        f"erreur de transport sur {redact(url)}: {redact(str(exc))}"
                    ) from None
                self._backoff(attempt, None)
                continue

            self._quota = parse_quota(response.headers)
            if billable:
                # An absent header means the true cost is unknown; charge the
                # estimate rather than nothing.
                self._spent += self._quota.last_cost if self._quota.last_cost is not None else cost
                self._reconcile(reservation, self._quota.last_cost)

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

    def _reconcile(self, reservation: int | None, observed: int | None) -> None:
        if self._ledger is not None and reservation is not None:
            self._ledger.reconcile(reservation, observed_cost=observed)

    def _release(self, reservation: int | None) -> None:
        if self._ledger is not None and reservation is not None:
            self._ledger.release(reservation)

    def _settle_failure(self, reservation: int | None, error: BaseException, cost: int) -> None:
        """Account a failed attempt according to what we can actually prove.

        Charged at the estimate when billing is in doubt, released only when the
        request demonstrably never left. The per-scan counter follows the same
        rule, so a run of read timeouts exhausts the scan budget instead of
        looping for free.
        """
        if may_have_been_billed(error):
            self._spent += cost
            return
        self._release(reservation)

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
