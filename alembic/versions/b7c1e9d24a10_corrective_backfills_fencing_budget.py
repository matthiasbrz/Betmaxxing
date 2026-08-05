"""corrective backfills, scheduler fencing, ambiguity queue, budget ledger

Why this is a separate revision rather than an edit of ``3ce123580afa``:

* a deployment that already applied ``3ce123580afa`` (commit ``f901d6e``) will
  never re-run it, so any backfill placed there would skip exactly the databases
  that need it. Only the ``challenges`` NOT NULL sequence had to be corrected in
  place, because without it that revision could not be applied at all;
* everything else here is genuinely new schema plus data repair, and both must
  reach old and new databases alike.

What it repairs
---------------
* ``events.participant_pair_key`` — matching key for rows created before it existed;
* ``event_source_map`` — one row per usable ``events.source_ids`` entry, idempotent,
  refusing rather than overwriting a collision;
* ``odds_snapshots.line_canonical`` — computed with the domain's own ``canonical_line``
  so ``2.5``, ``2.50`` and ``2.500`` converge; a value that cannot be represented
  stops the migration instead of receiving an invented key.

What it adds
------------
* ``scheduler_jobs.claim_token`` / ``next_attempt_at`` — lease fencing and retry backoff;
* ``event_mapping_reviews`` — the quarantine an ambiguous resolution goes to;
* ``provider_budget_ledger`` — durable credit reservations, so a per-process counter
  is no longer the only thing standing between a retry loop and the daily quota;
* ``events.season`` — a matching signal that was described but never stored;
* ``participant_aliases`` unique key widened to ``(sport, source, alias)`` so one
  provider's alias cannot evict another's.

Downgrade drops what it added, clears ``line_canonical`` /
``participant_pair_key``, and **folds every ``event_source_map`` row back into
``events.source_ids``** before the parent revision drops that table. Those rows
are the only link between a stored price and the fixture it was quoted for, so
losing them on the way down is data loss, not a tidy-up. A provider id already
present in the column with a conflicting value stops the downgrade by name rather
than being overwritten.

Revision ID: b7c1e9d24a10
Revises: 3ce123580afa
Create Date: 2026-08-05 09:10:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from betmaxxing.domain.ids import normalize_participant
from betmaxxing.domain.models import canonical_line

revision: str = "b7c1e9d24a10"
down_revision: str | None = "3ce123580afa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Backfills
# ---------------------------------------------------------------------------
def _backfill_participant_pair_key(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT canonical_id, sport, home_name, away_name FROM events"
            " WHERE participant_pair_key IS NULL"
        )
    ).fetchall()
    for canonical_id, sport, home, away in rows:
        key = f"{sport}|{normalize_participant(home)}|{normalize_participant(away)}"
        connection.execute(
            sa.text("UPDATE events SET participant_pair_key = :key WHERE canonical_id = :cid"),
            {"key": key, "cid": canonical_id},
        )


def _backfill_event_source_map(connection: sa.Connection) -> None:
    """Turn every usable ``events.source_ids`` entry into a mapping row.

    Idempotent: a pair already mapped to the same internal id is skipped. A pair
    mapped to a *different* internal id is a genuine ambiguity in the legacy
    data — the migration stops and names it rather than picking a winner.
    """
    existing: dict[tuple[str, str], str] = {
        (provider, provider_event_id): internal_id
        for provider, provider_event_id, internal_id in connection.execute(
            sa.text("SELECT provider, provider_event_id, internal_id FROM event_source_map")
        ).fetchall()
    }

    for canonical_id, raw in connection.execute(
        sa.text("SELECT canonical_id, source_ids FROM events")
    ).fetchall():
        try:
            source_ids = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            continue
        if not isinstance(source_ids, dict):
            continue

        for provider, provider_event_id in source_ids.items():
            if not provider or not provider_event_id:
                continue
            key = (str(provider), str(provider_event_id))
            owner = existing.get(key)
            if owner == canonical_id:
                continue
            if owner is not None:
                raise RuntimeError(
                    f"Migration refusée : ({provider}, {provider_event_id}) est revendiqué "
                    f"par {owner!r} et par {canonical_id!r}. Aucune source n'est écrasée ; "
                    "corrigez events.source_ids avant de migrer."
                )
            connection.execute(
                sa.text(
                    "INSERT INTO event_source_map (provider, provider_event_id, internal_id)"
                    " VALUES (:provider, :provider_event_id, :internal_id)"
                ),
                {
                    "provider": key[0],
                    "provider_event_id": key[1],
                    "internal_id": canonical_id,
                },
            )
            existing[key] = canonical_id


def _backfill_line_canonical(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT fingerprint, line FROM odds_snapshots"
            " WHERE line IS NOT NULL AND line_canonical IS NULL"
        )
    ).fetchall()
    for fingerprint, line in rows:
        try:
            value = canonical_line(repr(float(line)))
        except (ValueError, TypeError, OverflowError) as exc:
            raise RuntimeError(
                f"Migration refusée : le snapshot {fingerprint!r} porte une ligne "
                f"inexploitable ({line!r} — {exc}). Aucune clé de marché n'est inventée."
            ) from exc
        connection.execute(
            sa.text("UPDATE odds_snapshots SET line_canonical = :value WHERE fingerprint = :fp"),
            {"value": value, "fp": fingerprint},
        )


def _fold_mappings_back_into_source_ids(connection: sa.Connection) -> None:
    """Downgrade direction: write every mapping back into ``events.source_ids``.

    This revision's parent drops ``event_source_map``, so anything recorded only
    there would be lost on the way down — and those rows are the only link
    between a stored price and the fixture it was quoted for. Folding them into
    the JSON column first makes the round trip lossless in both directions
    (D-041); the upgrade rebuilds the table from the same column.

    A provider id already present in the column with a *different* value is a
    genuine contradiction. The downgrade refuses rather than choosing, because
    picking one silently is how source attribution gets rewritten.
    """
    mappings: dict[str, dict[str, str]] = {}
    for provider, provider_event_id, internal_id in connection.execute(
        sa.text("SELECT provider, provider_event_id, internal_id FROM event_source_map")
    ).fetchall():
        mappings.setdefault(str(internal_id), {})[str(provider)] = str(provider_event_id)

    for internal_id, discovered in mappings.items():
        raw = connection.execute(
            sa.text("SELECT source_ids FROM events WHERE canonical_id = :cid"),
            {"cid": internal_id},
        ).scalar()
        try:
            existing = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}

        merged = dict(existing)
        for provider, provider_event_id in discovered.items():
            current = merged.get(provider)
            if current is not None and str(current) != provider_event_id:
                raise RuntimeError(
                    f"Downgrade refusé : l'événement {internal_id!r} porte "
                    f"source_ids[{provider!r}]={current!r} alors que event_source_map "
                    f"indique {provider_event_id!r}. Aucune attribution n'est "
                    "réécrite au hasard ; tranchez avant de redescendre."
                )
            merged[provider] = provider_event_id

        if merged != existing:
            connection.execute(
                sa.text("UPDATE events SET source_ids = :ids WHERE canonical_id = :cid"),
                {"ids": json.dumps(merged), "cid": internal_id},
            )


# ---------------------------------------------------------------------------
def upgrade() -> None:
    connection = op.get_bind()

    _backfill_participant_pair_key(connection)
    _backfill_event_source_map(connection)
    _backfill_line_canonical(connection)

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("season", sa.String(length=32), nullable=True))

    with op.batch_alter_table("scheduler_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("claim_token", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            "ix_scheduler_claimable", ["state", "scheduled_for", "next_attempt_at"], unique=False
        )

    # A (sport, alias) key let one provider's spelling evict another's. Identity
    # matching now reads aliases per source, so the source belongs in the key.
    with op.batch_alter_table(
        "participant_aliases",
        schema=None,
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_N_name)s"},
    ) as batch_op:
        batch_op.drop_constraint("uq_participant_alias", type_="unique")
        batch_op.create_unique_constraint(
            "uq_participant_alias_source", ["sport", "source", "alias"]
        )

    op.create_table(
        "event_mapping_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("sport", sa.String(length=32), nullable=False),
        sa.Column("competition", sa.String(length=160), nullable=False),
        sa.Column("home_name", sa.String(length=160), nullable=False),
        sa.Column("away_name", sa.String(length=160), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_internal_ids", sa.JSON(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_mapping_review"),
    )
    with op.batch_alter_table("event_mapping_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_mapping_reviews_provider"), ["provider"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_mapping_reviews_resolved"), ["resolved"], unique=False
        )

    op.create_table(
        "provider_budget_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("day_utc", sa.String(length=10), nullable=False),
        sa.Column("request", sa.String(length=200), nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column("reserved_cost", sa.Integer(), nullable=False),
        sa.Column("observed_cost", sa.Integer(), nullable=True),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("provider_budget_ledger", schema=None) as batch_op:
        batch_op.create_index("ix_budget_provider_day", ["provider", "day_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_provider_budget_ledger_batch_id"), ["batch_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_budget_ledger", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_provider_budget_ledger_batch_id"))
        batch_op.drop_index("ix_budget_provider_day")
    op.drop_table("provider_budget_ledger")

    with op.batch_alter_table("event_mapping_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_mapping_reviews_resolved"))
        batch_op.drop_index(batch_op.f("ix_event_mapping_reviews_provider"))
    op.drop_table("event_mapping_reviews")

    with op.batch_alter_table(
        "participant_aliases",
        schema=None,
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_N_name)s"},
    ) as batch_op:
        batch_op.drop_constraint("uq_participant_alias_source", type_="unique")
        batch_op.create_unique_constraint("uq_participant_alias", ["sport", "alias"])

    with op.batch_alter_table("scheduler_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_scheduler_claimable")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("claim_token")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_column("season")

    # `line_canonical` and `participant_pair_key` are derived values; clearing
    # them restores the previous revision's state exactly.
    connection = op.get_bind()
    _fold_mappings_back_into_source_ids(connection)
    connection.execute(sa.text("UPDATE odds_snapshots SET line_canonical = NULL"))
    connection.execute(sa.text("UPDATE events SET participant_pair_key = NULL"))
