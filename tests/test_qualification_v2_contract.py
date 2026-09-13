"""Protocol v2: what the first version of D-071 claimed but did not enforce.

Every test here was written against the uncorrected head and had to fail there.
The nine defects it closes were reproduced by an independent read-only audit, and
each one has its own class below so a regression names itself.

The shape of the contract:

* the freshness threshold is a **literal** in the protocol, never a setting;
* a qualifying receipt is **v4**, stamped with the protocol and adapter-evidence
  versions it was produced under, and recorded **after** the protocol's effective
  instant;
* v2 and v3 receipts stay readable history and qualify nothing;
* admissibility is a **positive** (command, status) table, closed by default;
* a receipt that disagrees with itself fails closed, in both directions;
* "UTC day" means a day in UTC.

Nothing here opens a socket, reads a real receipt, or touches a real key: every
receipt is synthetic and signed with the suite's synthetic secret.
"""

from __future__ import annotations

import json as jsonlib
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from helpers_activation import FAKE_RECEIPT_SECRET

#: Every test in this module reads the receipt directory through
#: ``activation.receipt_dir()``. Without this, an unrelated
#: ``.activation-receipts`` in the working directory would be picked up and could
#: close the qualification gate for the whole module — see the fixture's docstring.
pytestmark = pytest.mark.usefixtures("isolated_receipt_directory")

#: The protocol 8 manifest. A corpus that is meant to reach the human-review gate
#: has to be inside the pre-registered campaign since v8: a receipt naming another
#: competition or another bookmaker is an evidence conflict, not weak evidence.
FOOTBALL = "soccer_epl"
FOOTBALL_2 = "soccer_spain_la_liga"
TENNIS = "tennis_atp_us_open"
TENNIS_2 = "tennis_wta_us_open"
BOOK = "pinnacle"

#: The protocol's own effective instant, parsed once here so the tests position
#: themselves relative to the constant rather than to a date they invent.
NOT_BEFORE = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
DAY_ONE = NOT_BEFORE + timedelta(days=1)
DAY_TWO = NOT_BEFORE + timedelta(days=2)
DAY_THREE = NOT_BEFORE + timedelta(days=3)
BEFORE_EFFECT = NOT_BEFORE - timedelta(days=20)
#: One UTC day well inside the evidence window, and the calendar day after it.
_ONE_UTC_DAY = (NOT_BEFORE + timedelta(days=2)).date().isoformat()
_ONE_DAY_LATER = (NOT_BEFORE + timedelta(days=3)).date().isoformat()


# ---------------------------------------------------------------------------
# Synthetic, signed receipts
# ---------------------------------------------------------------------------
_SIGNING = FAKE_RECEIPT_SECRET


# ---------------------------------------------------------------------------
# v6 provenance shim — see D-076
# ---------------------------------------------------------------------------
# `qualification.evaluate` and `build_activation_state` now require receipts whose
# signature has already been checked, because until v6 they checked it themselves and
# that dragged the secret — and a key file they created — into a module documented as
# pure. These two helpers mint that provenance the way `audit_receipts` does, so every
# assertion below keeps testing exactly what it tested before.
def _verify_with_secret(payload: Any) -> bool:
    """`verify_receipt` takes the secret explicitly since v6 (D-076)."""
    return act.verify_receipt(payload, _SIGNING)


def _tag_with_secret(event_id: str) -> str:
    """`event_tag` takes the secret explicitly since v6 (D-076)."""
    return act.event_tag(event_id, _SIGNING)


def _trusted(receipts: Any, unverifiable: int = 0) -> Any:
    """One real audit of a throwaway directory — see `helpers_receipt_boundary`.

    D-077: the provenance type has no public constructor and no key-taking factory, so
    a suite acquires evidence the way production does. Every assertion below is
    unchanged; only this function is.
    """
    from helpers_receipt_boundary import audited

    return audited(receipts, unverifiable, secret=_SIGNING)


def _evaluate(receipts: Any, unverifiable: int = 0, **kw: Any) -> Any:
    return qual.evaluate(_trusted(receipts, unverifiable), **kw)


def _state(receipts: Any, unverifiable: int = 0, **kw: Any) -> Any:
    return act.build_activation_state(_trusted(receipts, unverifiable), **kw)


def signed(**fields: Any) -> dict[str, Any]:
    """A signed synthetic v4 receipt. Defaults describe an admissible core mapping."""
    moment: datetime = fields.pop("moment", DAY_ONE)
    document: dict[str, Any] = {
        "schema_version": 4,
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": fields.pop("receipt_id", "00" * 8),
        "command": "core",
        "status": str(act.ActivationStatus.CORE_LIVE_VERIFIED),
        "recorded_at": fields.pop("recorded_at", moment.isoformat()),
        "expires_at": (moment + act.RECEIPT_TTL).isoformat(),
        "sport_key": FOOTBALL,
        "bookmaker": BOOK,
        "network_attempted": True,
        "may_have_reached_provider": True,
        # Mandatory since protocol v4, and consistent with the network flag by
        # construction. The harness writes `attempts` on every receipt, so a fixture
        # that omitted it described a document the producer never emits; derived
        # rather than hard-coded so a case overriding the flag stays honest.
        "attempts": 1 if fields.get("network_attempted", True) is True else 0,
        "estimated_credits": 1,
        "observed_credits": 1,
        "accounted_credits": 1,
        "markets_requested": ["h2h"],
        "market_states": {"h2h": str(act.MarketState.OBSERVED_MAPPED)},
        "markets_mapped": ["h2h"],
        "selections_mapped": 3,
        "freshness": {"h2h": 600},
        "mapping_rejections": [],
        "event_tag": fields.pop("event_tag", "a" * 32),
        "bookmaker_state": str(act.BookmakerState.OBSERVED),
    }
    document.update(fields)
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document, _SIGNING)
    return document


def additional(**fields: Any) -> dict[str, Any]:
    """A signed synthetic `additional` receipt with all five markets mapped."""
    markets = list(act.ADDITIONAL_MARKETS)
    base: dict[str, Any] = {
        "command": "additional",
        "status": str(act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        "estimated_credits": 5,
        "observed_credits": 5,
        "accounted_credits": 5,
        "markets_requested": markets,
        "market_states": {m: str(act.MarketState.OBSERVED_MAPPED) for m in markets},
        "markets_mapped": markets,
        "selections_mapped": 11,
        "freshness": dict.fromkeys(markets, 300),
    }
    base.update(fields)
    return signed(**base)


def full_corpus(
    *, moment_shift: timedelta = timedelta(0), id_offset: int = 0, **over: Any
) -> list[dict[str, Any]]:
    """The minimal corpus that satisfies all eight criteria under protocol v2.

    ``id_offset`` exists because two corpora combined in one directory are eight
    *different* receipts twice over, not eight receipts written twice: the harness
    draws every ``receipt_id`` from :func:`secrets.token_hex`, so it never reuses
    one. Without the offset both calls produced identical identifiers carrying
    different signed bytes, which protocol v4 correctly reports as a conflict and
    excludes from every threshold.
    """
    rows = [
        (FOOTBALL, DAY_ONE, "a"),
        (FOOTBALL_2, DAY_TWO, "b"),
        (FOOTBALL, DAY_TWO, "c"),
        (TENNIS, DAY_ONE, "d"),
        (TENNIS_2, DAY_TWO, "f"),
        (TENNIS, DAY_THREE, "0"),
    ]
    corpus = [
        signed(
            receipt_id=f"{i + id_offset:016x}",
            sport_key=key,
            moment=moment + moment_shift,
            event_tag=tag * 32,
            **over,
        )
        for i, (key, moment, tag) in enumerate(rows, start=1)
    ]
    corpus += [
        additional(
            receipt_id=f"{0xAA + id_offset:016x}",
            sport_key=FOOTBALL,
            moment=DAY_ONE + moment_shift,
            event_tag="1" * 32,
            **over,
        ),
        additional(
            receipt_id=f"{0xBB + id_offset:016x}",
            sport_key=FOOTBALL_2,
            moment=DAY_TWO + moment_shift,
            event_tag="2" * 32,
            **over,
        ),
    ]
    return corpus


def entry(document: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for candidate in document["criteria_results"]:
        if candidate["criterion_id"] == criterion_id:
            return candidate
    raise AssertionError(f"no criterion {criterion_id}")


def passing(document: dict[str, Any]) -> list[str]:
    return [e["criterion_id"] for e in document["criteria_results"] if e["passed"]]


def cost(document: dict[str, Any]) -> dict[str, Any]:
    return entry(document, "COST_CONFORMITY")


# ---------------------------------------------------------------------------
# H1 — the threshold is a literal the environment cannot move
# ---------------------------------------------------------------------------
class TestTheProtocolThresholdIsALiteral:
    """v1 read `Settings().max_odds_age_seconds` at import.

    That made the "pre-registered" threshold a runtime variable: an operator with
    ``BETMAXXING_MAX_ODDS_AGE_SECONDS=123`` in a `.env` got a *different*
    protocol under the same version number, in the direction that matters —
    raising it lets a stale quote support a freshness claim.
    """

    def test_the_versioned_constants_are_literals(self) -> None:
        """The threshold is fixed; the protocol number is pinned by the v3 contract.

        This class guards the v2 closures, which are unchanged. When the authorised
        v3 bump moved the protocol number, pinning it here as well would have said
        nothing extra — `tests/test_qualification_v3_contract.py` pins it exactly.
        """
        assert qual.PROTOCOL_MAX_ODDS_AGE_SECONDS == 900
        assert isinstance(qual.PROVIDER_VALIDATION_PROTOCOL_VERSION, int)
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION >= 2
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4

    def test_the_module_reads_no_configuration_at_all(self) -> None:
        source = Path(qual.__file__).read_text(encoding="utf-8")
        for forbidden in ("Settings", "get_settings", "dotenv", "os.environ", "getenv"):
            assert forbidden not in source, forbidden

    def test_a_synthetic_env_file_cannot_move_the_threshold(self, tmp_path: Path) -> None:
        """A `.env` and an exported variable, both ignored. No key, no secret."""
        (tmp_path / ".env").write_text("BETMAXXING_MAX_ODDS_AGE_SECONDS=123\n", encoding="utf-8")
        package_root = str(Path(act.__file__).resolve().parents[3])
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from betmaxxing.providers.the_odds_api import qualification as q; "
                "print(q.PROTOCOL_MAX_ODDS_AGE_SECONDS, q.PROVIDER_VALIDATION_PROTOCOL_VERSION)",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": package_root,
                "BETMAXXING_MAX_ODDS_AGE_SECONDS": "123",
            },
        )
        assert proc.returncode == 0, proc.stderr[-400:]
        # Neither value moved: the threshold stays 900 and the protocol number is
        # the module's own, not the environment's.
        assert proc.stdout.split() == [
            "900",
            str(qual.PROVIDER_VALIDATION_PROTOCOL_VERSION),
        ]

    def test_every_criterion_scope_states_the_protocol_threshold(self) -> None:
        for criterion in qual.CRITERIA:
            assert "900" in criterion.scope

    def test_the_threshold_is_inclusive_and_901_is_not(self) -> None:
        fresh = signed(freshness={"h2h": 900})
        stale = signed(freshness={"h2h": 901})
        assert qual.admissible_for(fresh, qual.CRITERIA[0]) is True
        assert qual.admissible_for(stale, qual.CRITERIA[0]) is False

    def test_the_status_path_never_instantiates_settings(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`status` is a local read. Nothing on that path needs configuration."""
        import betmaxxing.config as config
        from helpers_activation import run

        def bomb(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("`status` instantiated Settings")

        monkeypatch.setattr(config.Settings, "__init__", bomb)
        config.reset_settings_cache()
        result = run("status", "--json")
        assert result.exit_code == 0, result.output

    def test_the_products_own_default_is_still_900(self) -> None:
        """Read off the field definition, not by instantiating anything.

        The two numbers agreeing today is a fact worth recording; the protocol no
        longer *depends* on it, which is the whole point of H1.
        """
        from betmaxxing.config import Settings

        assert Settings.model_fields["max_odds_age_seconds"].default == 900


# ---------------------------------------------------------------------------
# H2 — evidence must postdate the protocol and name the versions it ran under
# ---------------------------------------------------------------------------
class TestEvidenceIsBoundToProtocolAndImplementation:
    """v1 accepted any signed v2/v3 receipt, whenever it was recorded.

    So observations made weeks before the criteria existed satisfied them — the
    exact thing pre-registration is supposed to rule out — and nothing tied a
    proof to the parser version that produced it.
    """

    def test_the_effective_instant_is_a_literal_utc_string(self) -> None:
        moment = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
        assert moment.tzinfo is not None
        assert moment.utcoffset() == timedelta(0)

    def test_a_complete_v3_corpus_after_the_date_qualifies_nothing(self) -> None:
        document = _evaluate(full_corpus(schema_version=3), 0)
        assert passing(document) == []
        assert document["qualification_state"] == str(qual.QualificationState.INSUFFICIENT_EVIDENCE)
        assert document["qualification_historical_nonqualifying_receipts"] == 8
        assert document["qualification_admissible_receipts"] == 0
        assert document["qualification_reasons"]["stale_schema"] == 8

    def test_a_complete_v4_corpus_before_the_date_qualifies_nothing(self) -> None:
        document = _evaluate(full_corpus(moment_shift=BEFORE_EFFECT - DAY_ONE), 0)
        assert passing(document) == []
        assert document["qualification_reasons"]["before_effective_instant"] == 8

    def test_another_protocol_version_qualifies_nothing(self) -> None:
        document = _evaluate(full_corpus(qualification_protocol_version=1), 0)
        assert passing(document) == []
        assert document["qualification_reasons"]["other_protocol_version"] == 8

    def test_another_adapter_evidence_version_qualifies_nothing(self) -> None:
        document = _evaluate(full_corpus(provider_adapter_evidence_version=2), 0)
        assert passing(document) == []
        assert document["qualification_reasons"]["other_adapter_evidence_version"] == 8

    def test_a_v4_corpus_of_the_current_versions_after_the_date_qualifies(self) -> None:
        """The gate's corpus is the pre-registered register, since 03C-2F quater.

        ``full_corpus()`` above is this module's eight paid receipts, and they are what
        every *other* test here needs: one field flipped, one population counted. They no
        longer reach the gate on their own, because the campaign position is recognised
        from the receipts and eight paid steps with no discovery behind them is a corpus
        no command could have produced. The criteria and their thresholds are untouched —
        what changed is that a corpus has to be producible to be believed.
        """
        import helpers_campaign_v8 as v8

        document = _evaluate(v8.register_corpus(secret=_SIGNING), 0)
        assert sorted(passing(document)) == sorted(c.criterion_id for c in qual.CRITERIA)
        assert document["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
        assert document["eligible_for_human_promotion_review"] is True
        assert document["qualification_admissible_receipts"] == 12

    def test_two_old_coverage_missing_calls_no_longer_feed_the_cost_criterion(self) -> None:
        """They used to contribute 2/6 while proving nothing about the parser."""
        old = [
            signed(
                receipt_id=f"{i:016x}",
                schema_version=3,
                moment=BEFORE_EFFECT,
                status=str(act.ActivationStatus.COVERAGE_MISSING),
                market_states={"h2h": str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)},
                markets_mapped=[],
                selections_mapped=0,
                freshness={},
                bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
                event_tag=f"{i}" * 32,
            )
            for i in (1, 2)
        ]
        assert cost(_evaluate(old, 0))["observed"]["provider_reached_conforming_cost"] == 0

    def test_older_schemas_stay_readable_history_and_are_not_unverifiable(self) -> None:
        mixed = full_corpus(schema_version=2, id_offset=0x2000) + full_corpus()
        document = _evaluate(mixed, 0)
        assert document["qualification_unverifiable_receipts"] == 0
        assert document["qualification_historical_nonqualifying_receipts"] == 8
        assert document["qualification_admissible_receipts"] == 8
        assert frozenset({2, 3, 4}) <= act.SUPPORTED_SCHEMA_VERSIONS

    def test_tampering_with_either_version_field_breaks_the_signature(self) -> None:
        for field in ("qualification_protocol_version", "provider_adapter_evidence_version"):
            receipt = signed()
            receipt[field] = 99
            assert _verify_with_secret(receipt) is False
            # v6 moved this refusal upstream to `audit_receipts`; D-077 made the audit the
            # only way in, so the refusal is now a *count* rather than an exception. The
            # property is unchanged and still checked on both halves: the altered receipt
            # verifies as False, and it lands in the unverifiable population having
            # supported nothing.
            document = _evaluate([receipt], 0)
            assert document["qualification_unverifiable_receipts"] == 1
            assert document["qualification_admissible_receipts"] == 0

    @pytest.mark.parametrize(
        "recorded_at",
        ["2026-08-11T12:00:00", "not-a-date", "", "2026-08-11"],
    )
    def test_an_unusable_instant_never_qualifies(self, recorded_at: str) -> None:
        document = _evaluate([signed(recorded_at=recorded_at)], 0)
        assert passing(document) == []
        assert document["qualification_admissible_receipts"] == 0
        assert document["qualification_reasons"]["unusable_recorded_at"] == 1

    def test_a_non_textual_instant_never_qualifies(self) -> None:
        document = _evaluate([signed(recorded_at=17)], 0)
        assert document["qualification_admissible_receipts"] == 0


# ---------------------------------------------------------------------------
# H4 — a positive table, closed by default
# ---------------------------------------------------------------------------
class TestAdmissibilityIsAPositiveTable:
    """v1 refused a blacklist and accepted everything else.

    A status invented next year, or one belonging to the other command, produced
    positive evidence. "Closed" was claimed in the docstring and open in the code.
    """

    def test_the_table_names_the_expected_pairs(self) -> None:
        assert qual.ADMISSIBLE_STATUSES_BY_COMMAND["core"] == frozenset(
            {str(act.ActivationStatus.CORE_LIVE_VERIFIED)}
        )
        assert qual.ADMISSIBLE_STATUSES_BY_COMMAND["additional"] == frozenset(
            {
                str(act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
                str(act.ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
            }
        )

    def test_an_unknown_status_on_core_is_refused(self) -> None:
        document = _evaluate(full_corpus(status="FUTURE_UNKNOWN_STATUS"), 0)
        assert passing(document) == []

    def test_a_status_from_the_other_command_is_refused(self) -> None:
        core_like = [
            signed(
                receipt_id=f"{i:016x}",
                sport_key=key,
                moment=moment,
                event_tag=tag * 32,
                status=str(act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
            )
            for i, (key, moment, tag) in enumerate(
                [(FOOTBALL, DAY_ONE, "a"), (FOOTBALL_2, DAY_TWO, "b"), (FOOTBALL, DAY_TWO, "c")],
                start=1,
            )
        ]
        assert "CORE_MAPPING_FOOTBALL" not in passing(_evaluate(core_like, 0))

        extra_like = [
            additional(
                receipt_id="aa" * 8,
                sport_key=FOOTBALL,
                moment=DAY_ONE,
                event_tag="1" * 32,
                status=str(act.ActivationStatus.CORE_LIVE_VERIFIED),
            ),
            additional(
                receipt_id="bb" * 8,
                sport_key=FOOTBALL_2,
                moment=DAY_TWO,
                event_tag="2" * 32,
                status=str(act.ActivationStatus.CORE_LIVE_VERIFIED),
            ),
        ]
        assert passing(_evaluate(extra_like, 0)) == []

    def test_partial_coverage_is_admissible_for_the_markets_it_mapped(self) -> None:
        """And for those only — which is what "partial" has to mean.

        The fixture used to carry ``ADDITIONAL_PARTIAL_COVERAGE`` with *all five*
        markets mapped, a document ``_additional_status`` never emits: with everything
        mapped it reports ``ADDITIONAL_LIVE_VERIFIED``. Protocol v5 refuses that shape,
        so the fixture now describes a real partial coverage — four markets mapped, the
        fifth not returned — and the assertion gains the half it was missing: the market
        that was not mapped is not carried by the ones that were.
        """
        markets = list(act.ADDITIONAL_MARKETS)
        mapped, unmapped = markets[:-1], markets[-1]
        shape: dict[str, Any] = {
            "status": str(act.ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
            "market_states": {
                **dict.fromkeys(mapped, str(act.MarketState.OBSERVED_MAPPED)),
                unmapped: str(act.MarketState.NOT_RETURNED),
            },
            "markets_mapped": mapped,
            "selections_mapped": 9,
            "freshness": dict.fromkeys(mapped, 300),
        }
        partial = [
            additional(
                receipt_id="aa" * 8,
                sport_key=FOOTBALL,
                moment=DAY_ONE,
                event_tag="1" * 32,
                **shape,
            ),
            additional(
                receipt_id="bb" * 8,
                sport_key=FOOTBALL_2,
                moment=DAY_TWO,
                event_tag="2" * 32,
                **shape,
            ),
        ]
        satisfied = passing(_evaluate(partial, 0))
        for market in mapped:
            assert f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}" in satisfied
        assert f"ADDITIONAL_MAPPING_FOOTBALL_{unmapped.upper()}" not in satisfied


class TestCostConformityIsDefinedInItsOwnTerms:
    """A conforming cost observation is not "any receipt that is not a mismatch"."""

    def _six(self, **over: Any) -> list[dict[str, Any]]:
        return [
            signed(
                receipt_id=f"{i:016x}",
                sport_key=FOOTBALL,
                moment=DAY_ONE,
                event_tag=f"{i}" * 32,
                **over,
            )
            for i in range(1, 7)
        ]

    def test_six_conforming_paid_calls_pass(self) -> None:
        assert cost(_evaluate(self._six(), 0))["passed"] is True

    def test_a_coverage_missing_call_pays_and_counts_for_cost_only(self) -> None:
        missing = self._six(
            status=str(act.ActivationStatus.COVERAGE_MISSING),
            market_states={"h2h": str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)},
            markets_mapped=[],
            selections_mapped=0,
            freshness={},
            bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
        )
        document = _evaluate(missing, 0)
        assert cost(document)["passed"] is True
        assert passing(document) == ["COST_CONFORMITY"]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("status", "FUTURE_UNKNOWN_STATUS"),
            ("observed_credits", None),
            ("observed_credits", True),
            ("observed_credits", -1),
            ("observed_credits", 99),
            ("accounted_credits", 2),
            ("network_attempted", False),
            ("may_have_reached_provider", False),
            ("estimated_credits", 99),
        ],
    )
    def test_a_cost_that_is_not_established_does_not_count(self, field: str, value: Any) -> None:
        document = _evaluate(self._six(**{field: value}), 0)
        assert cost(document)["observed"]["provider_reached_conforming_cost"] == 0
        assert cost(document)["passed"] is False

    @pytest.mark.parametrize(
        "status",
        [act.ActivationStatus.COST_MISMATCH, act.ActivationStatus.COST_UNVERIFIED],
    )
    def test_one_nonconforming_call_fails_the_criterion(self, status: Any) -> None:
        receipts = [
            *self._six(),
            signed(receipt_id="ff" * 8, status=str(status), event_tag="9" * 32),
        ]
        document = _evaluate(receipts, 0)
        result = cost(document)
        # Protocol v5 files COST_UNVERIFIED under "cost not established" rather than
        # "cost nonconforming": a header nobody could read is not a tariff that
        # disagreed. v6 adds that a receipt the contract rejects is caught as an evidence
        # conflict instead of being priced. Blocking is what this test is about, and it
        # blocks either way.
        blocked_by_cost = sum(result["observed"][name] for name in qual.BLOCKING_COST_BUCKETS)
        assert blocked_by_cost == 1 or document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert result["passed"] is False or document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False


# ---------------------------------------------------------------------------
# H5 — contradictions in both directions
# ---------------------------------------------------------------------------
class TestContradictionsAreReciprocal:
    """v1 caught "selections without a mapped market" and not its converse.

    So a receipt saying *the bookmaker was never returned* and *nothing was
    mapped* still proved five markets mapped, with no conflict raised.
    """

    def _pair(self, **over: Any) -> list[dict[str, Any]]:
        return [
            additional(
                receipt_id="aa" * 8, sport_key=FOOTBALL, moment=DAY_ONE, event_tag="1" * 32, **over
            ),
            additional(
                receipt_id="bb" * 8,
                sport_key=FOOTBALL_2,
                moment=DAY_TWO,
                event_tag="2" * 32,
                **over,
            ),
        ]

    def test_mapped_markets_without_mapped_selections_fail_closed(self) -> None:
        document = _evaluate(self._pair(selections_mapped=0), 0)
        assert passing(document) == []
        assert document["evidence_conflicts"] != []
        assert document["qualification_state"] == str(qual.QualificationState.EVIDENCE_CONFLICT)

    def test_an_absent_bookmaker_cannot_have_mapped_markets(self) -> None:
        document = _evaluate(self._pair(bookmaker_state=str(act.BookmakerState.NOT_RETURNED)), 0)
        assert passing(document) == []
        assert document["evidence_conflicts"] != []

    def test_an_absent_bookmaker_cannot_have_a_mapped_market_list(self) -> None:
        document = _evaluate(
            self._pair(
                bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
                market_states=dict.fromkeys(
                    act.ADDITIONAL_MARKETS, str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)
                ),
                selections_mapped=0,
            ),
            0,
        )
        assert passing(document) == []
        assert document["evidence_conflicts"] != []

    def test_the_mapped_list_must_agree_with_the_market_map(self) -> None:
        document = _evaluate(self._pair(markets_mapped=["draw_no_bet"]), 0)
        assert passing(document) == []
        assert document["evidence_conflicts"] != []

    def test_a_mapped_market_needs_a_usable_freshness_age(self) -> None:
        broken = dict.fromkeys(act.ADDITIONAL_MARKETS, 300)
        broken["draw_no_bet"] = -1
        document = _evaluate(self._pair(freshness=broken), 0)
        assert passing(document) == []
        assert document["evidence_conflicts"] != []

    def test_selections_without_any_mapped_market_still_fails(self) -> None:
        document = _evaluate(
            self._pair(
                market_states=dict.fromkeys(
                    act.ADDITIONAL_MARKETS, str(act.MarketState.OBSERVED_REJECTED)
                ),
                markets_mapped=[],
            ),
            0,
        )
        assert document["evidence_conflicts"] != []

    def test_the_five_probes_that_used_to_pass_now_produce_a_conflict(self) -> None:
        """The audit's H5 probe, verbatim: 5/5 criteria and no conflict, before."""
        document = _evaluate(
            self._pair(
                selections_mapped=0,
                bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
                mapping_rejections=[],
            ),
            0,
        )
        assert [e for e in document["criteria_results"] if e["passed"]] == []
        assert len(document["evidence_conflicts"]) >= 1

    def test_a_conflict_never_names_an_event(self) -> None:
        document = _evaluate(self._pair(selections_mapped=0), 0)
        for conflict in document["evidence_conflicts"]:
            assert "1" * 32 not in conflict
            assert "2" * 32 not in conflict


# ---------------------------------------------------------------------------
# H6 — a UTC day is a day in UTC
# ---------------------------------------------------------------------------
class TestUtcDaysAreNormalisedToUtc:
    """v1 took the civil date as written, so an offset invented a second day."""

    def test_the_same_utc_day_written_two_ways_is_one_day(self) -> None:
        assert qual.utc_day("2026-08-11T00:30:00+02:00") == "2026-08-10"
        assert qual.utc_day("2026-08-10T23:30:00+00:00") == "2026-08-10"

    def test_three_observations_on_one_utc_day_do_not_satisfy_two(self) -> None:
        same_day = [
            signed(receipt_id=f"{i:016x}", sport_key=key, recorded_at=stamp, event_tag=tag * 32)
            for i, (key, stamp, tag) in enumerate(
                [
                    # Derived from the effective instant rather than typed: these were
                    # three literals, so every protocol bump quietly turned them into
                    # history and the test asserted nothing. The property is untouched —
                    # the same three clock times, the same offset, all on one UTC day.
                    (FOOTBALL, f"{_ONE_DAY_LATER}T00:30:00+02:00", "a"),
                    (FOOTBALL_2, f"{_ONE_UTC_DAY}T23:30:00+00:00", "b"),
                    (FOOTBALL, f"{_ONE_UTC_DAY}T23:45:00+00:00", "c"),
                ],
                start=1,
            )
        ]
        result = entry(_evaluate(same_day, 0), "CORE_MAPPING_FOOTBALL")
        assert result["observed"]["utc_days"] == 1
        assert result["passed"] is False

    def test_two_real_utc_days_satisfy_the_threshold(self) -> None:
        two_days = [
            signed(receipt_id=f"{i:016x}", sport_key=key, moment=moment, event_tag=tag * 32)
            for i, (key, moment, tag) in enumerate(
                [(FOOTBALL, DAY_ONE, "a"), (FOOTBALL_2, DAY_TWO, "b"), (FOOTBALL, DAY_TWO, "c")],
                start=1,
            )
        ]
        assert entry(_evaluate(two_days, 0), "CORE_MAPPING_FOOTBALL")["passed"] is True

    def test_a_naive_instant_contributes_no_day(self) -> None:
        assert qual.utc_day("2026-08-11T12:00:00") == ""
        assert qual.utc_day(17) == ""
        assert qual.utc_day("nonsense") == ""


# ---------------------------------------------------------------------------
# H7 — the tag policy, tested against the values actually injected
# ---------------------------------------------------------------------------
class TestTheHmacTagPolicy:
    """D-062 keeps a per-observation coverage list, and the tag is the local HMAC
    surrogate — it is *meant* to be visible there, and nowhere else.

    The previous assertion asked whether a sentinel the fixture never produces was
    absent, so it could not fail. It is replaced, not weakened.
    """

    def _write(self, workspace: Path, receipts: list[dict[str, Any]]) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        for index, receipt in enumerate(receipts, start=1):
            payload = {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            payload["recorded_at"] = (
                datetime.fromisoformat(str(payload["recorded_at"])) + timedelta(minutes=index)
            ).isoformat()
            act.write_receipt(payload)

    def test_the_tags_really_injected_appear_in_the_coverage_block(self, workspace: Path) -> None:
        from helpers_activation import run

        corpus = full_corpus()
        self._write(workspace, corpus)
        payload = jsonlib.loads(run("status", "--json").stdout)
        shown = {
            observation["event_tag"] for observation in payload["bookmaker_coverage_observations"]
        }
        injected = {str(receipt["event_tag"]) for receipt in corpus}
        assert injected <= shown, injected - shown

    def test_no_tag_reaches_the_qualification_block(self, workspace: Path) -> None:
        from helpers_activation import run

        corpus = full_corpus()
        self._write(workspace, corpus)
        payload = jsonlib.loads(run("status", "--json").stdout)
        rendered = jsonlib.dumps(
            {
                "criteria_results": payload["criteria_results"],
                "qualification_reasons": payload["qualification_reasons"],
                "evidence_conflicts": payload["evidence_conflicts"],
                "qualification_note": payload["qualification_note"],
            }
        )
        for receipt in corpus:
            assert str(receipt["event_tag"]) not in rendered

    def test_the_output_still_leaks_no_key_odd_team_or_signature(self, workspace: Path) -> None:
        from helpers_activation import FAKE_KEY, run

        self._write(workspace, full_corpus())
        out = run("status", "--json").stdout
        for forbidden in (FAKE_KEY, "1.63", "Olympique", "apiKey=", "signature", "://"):
            assert forbidden not in out, forbidden


# ---------------------------------------------------------------------------
# S2 — the D-062 counter keeps its own meaning
# ---------------------------------------------------------------------------
class TestTheAuditCounterIsNotOverwritten:
    """`**qualification` used to spread a same-named key over the D-062 field."""

    def test_the_two_counters_coexist_and_now_read_one_audit(self) -> None:
        receipts = full_corpus() + full_corpus(schema_version=3, id_offset=0x1000)
        unknown = signed(receipt_id="ee" * 8, schema_version=99)
        document = _state([*receipts, unknown], unverifiable=4)
        # Both keys still exist and are both published, which is what this test was
        # written to protect: a `**qualification` spread once overwrote the D-062 field
        # with a same-named key of a different provenance.
        #
        # What changed at D-077, deliberately: there is now **one** audit, and both
        # counters read it. They can no longer disagree, because the two provenances that
        # let them disagree were the two ways of counting the same files — and having two
        # was the defect, not the feature. The unreadable receipt (`schema_version=99`)
        # is counted here as well, so the number is five, not four.
        assert document["unverifiable_receipts"] == 5
        assert document["qualification_unverifiable_receipts"] == 5
        assert document["verified_receipts"] == 16
        assert document["qualification_historical_nonqualifying_receipts"] == 8
        assert document["qualification_historical_nonqualifying_receipts"] == 8
        assert document["qualification_admissible_receipts"] == 8

    def test_the_qualification_keys_are_all_prefixed(self) -> None:
        document = _evaluate([], 0)
        for key in document:
            # Two prefixed blocks since protocol 8: the qualification verdict and the
            # campaign ledger. Both are prefixed for the same reason — a bare key can be
            # overwritten by another block's spread without anyone noticing.
            assert (
                key.startswith("qualification_")
                or key.startswith("campaign_")
                or key
                in {
                    "criteria_results",
                    "eligible_for_human_promotion_review",
                    "evidence_conflicts",
                }
            ), key


# ---------------------------------------------------------------------------
# H3 — invocations, HTTP requests and credits are three different numbers
# ---------------------------------------------------------------------------
class TestTheDocumentedBudgetMatchesTheCode:
    """The protocol said "12 requêtes" for a campaign that issues 16.

    Derived from `LOCAL_BOUNDS` and `STEP_CEILINGS` rather than retyped, so the
    document cannot drift from the harness again.
    """

    def test_the_campaign_shape_is_declared_in_code(self) -> None:
        assert qual.CAMPAIGN_INVOCATIONS == {"discover": 4, "core": 6, "additional": 2}

    def test_the_four_totals_are_what_the_bounds_imply(self) -> None:
        assert qual.campaign_budget() == {
            "cli_invocations": 12,
            "human_authorisations": 12,
            "http_requests": 16,
            "paid_http_requests": 8,
            "contractual_credits": 16,
        }

    def test_the_protocol_document_states_each_total_exactly_once(self) -> None:
        text = Path("docs/provider-validation-protocol.md").read_text(encoding="utf-8")
        budget = qual.campaign_budget()
        for line in (
            f"invocations CLI maximales : **{budget['cli_invocations']}**",
            f"autorisations humaines distinctes : **{budget['human_authorisations']}**",
            f"requêtes HTTP maximales : **{budget['http_requests']}**",
            f"requêtes HTTP payantes : **{budget['paid_http_requests']}**",
            f"crédits contractuels maximaux : **{budget['contractual_credits']}**",
        ):
            assert text.count(line) == 1, line

    def test_the_old_conflation_is_gone(self) -> None:
        text = Path("docs/provider-validation-protocol.md").read_text(encoding="utf-8")
        assert "requêtes maximales : **12**" not in text
        assert "| Étape | Appels |" not in text
