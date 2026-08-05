"""scheduler ledger, event identity, uncertainty contract, batches

Additive by design. Existing rows keep their data:

* new tables (``scheduler_jobs``, ``event_source_map``, ``event_schedule_history``,
  ``participant_aliases``, ``collection_batches``, ``model_registry``);
* new nullable columns on existing tables;
* ``candidates.ev_conservative`` becomes NULLABLE, because "no defensible
  uncertainty method exists" now has to be representable (D-019). Widening a
  NOT NULL column cannot lose data; the downgrade narrows it again and will
  fail loudly if any NULL is present, which is the correct behaviour rather
  than silently inventing a value.

``events.canonical_id`` keeps its name and its values. What changed is how new
ids are *derived* — opaque instead of hashed from date and participants — so no
existing row needs rewriting.

Revision ID: 3ce123580afa
Revises: 65c32b5e3f63
Create Date: 2026-08-05 06:20:24.151443
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3ce123580afa"
down_revision: str | None = "65c32b5e3f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What to do with a Challenge whose stored document cannot be interpreted.
#: The default refuses the migration and names the row, because inventing a bank
#: balance for a money-tracking record is not an acceptable failure mode. Set
#: ``BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE=quarantine`` to park those rows in a
#: terminal, zero-bank state instead — a deliberate, logged loss of one
#: progression rather than a silent fabrication.
UNUSABLE_CHALLENGE_POLICY = "BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE"

QUARANTINE_REASON = (
    "Mise en quarantaine par la migration 3ce123580afa : le document historique "
    "de ce Challenge ne permet pas de reconstituer une banque. Aucun montant n'a "
    "été inventé ; reprenez la progression manuellement."
)


class UnusableChallengeDocument(RuntimeError):
    """A challenge row whose bank cannot be reconstructed from what was stored."""


def _bank_cents_from(document_json: str | None, steps: list[str]) -> int:
    """Reconstruct the current bank the way the domain would.

    Precedence, and why: a settled rung *is* the bank's history, so the last
    ``bank_after_cents`` wins. Falling back to the configured initial bank is
    only correct when nothing has been settled yet.
    """
    for raw in reversed(steps):
        try:
            step = json.loads(raw)
        except (TypeError, ValueError):
            continue
        after = step.get("bank_after_cents") if isinstance(step, dict) else None
        if isinstance(after, int):
            return after

    try:
        document = json.loads(document_json or "")
    except (TypeError, ValueError) as exc:
        raise UnusableChallengeDocument("document illisible") from exc
    if not isinstance(document, dict):
        raise UnusableChallengeDocument("document n'est pas un objet")
    config = document.get("config")
    if not isinstance(config, dict) or "initial_bank" not in config:
        raise UnusableChallengeDocument("config.initial_bank absent")
    try:
        initial = float(config["initial_bank"])
    except (TypeError, ValueError) as exc:
        raise UnusableChallengeDocument("config.initial_bank non numérique") from exc
    # Same half-up rounding as betmaxxing.challenge.to_cents.
    return round(initial * 100)


def _add_challenge_columns_safely() -> None:
    """Add ``version`` and ``bank_cents`` to a table that may already have rows.

    ``ADD COLUMN ... NOT NULL`` without a default is rejected outright once the
    table is non-empty, which made this migration impossible to apply to any
    deployment that had ever created a Challenge. The sequence below is the
    standard one: widen, fill, verify, tighten, drop the transitional default.
    """
    connection = op.get_bind()

    with op.batch_alter_table("challenges", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bank_cents", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stop_reason", sa.Text(), nullable=True))

    rows = connection.execute(sa.text("SELECT challenge_id, document FROM challenges")).fetchall()
    policy = os.environ.get(UNUSABLE_CHALLENGE_POLICY, "refuse").strip().lower()

    for challenge_id, document in rows:
        steps = [
            row[0]
            for row in connection.execute(
                sa.text(
                    "SELECT document FROM challenge_steps WHERE challenge_id = :cid"
                    " ORDER BY step_index"
                ),
                {"cid": challenge_id},
            ).fetchall()
        ]
        try:
            bank = _bank_cents_from(document, steps)
        except UnusableChallengeDocument as exc:
            if policy != "quarantine":
                raise RuntimeError(
                    f"Migration refusée : le Challenge {challenge_id!r} ne peut pas être "
                    f"converti ({exc}). Aucune banque n'est inventée. Corrigez la ligne, "
                    f"ou relancez avec {UNUSABLE_CHALLENGE_POLICY}=quarantine pour la "
                    "parquer explicitement."
                ) from exc
            connection.execute(
                sa.text(
                    "UPDATE challenges SET version = 1, bank_cents = 0,"
                    " state = 'quarantined', stop_reason = :reason"
                    " WHERE challenge_id = :cid"
                ),
                {"cid": challenge_id, "reason": QUARANTINE_REASON},
            )
            continue

        connection.execute(
            sa.text(
                "UPDATE challenges SET version = 1, bank_cents = :bank WHERE challenge_id = :cid"
            ),
            {"cid": challenge_id, "bank": bank},
        )

    unfilled = connection.execute(
        sa.text("SELECT COUNT(*) FROM challenges WHERE version IS NULL OR bank_cents IS NULL")
    ).scalar_one()
    if unfilled:
        raise RuntimeError(
            f"Migration refusée : {unfilled} ligne(s) de challenges sans version ou banque "
            "après backfill. Le schéma n'est pas resserré sur des données incomplètes."
        )

    # Only now, with every row carrying a verified value, is NOT NULL honest.
    with op.batch_alter_table("challenges", schema=None) as batch_op:
        batch_op.alter_column("version", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("bank_cents", existing_type=sa.Integer(), nullable=False)


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "collection_batches",
        sa.Column("batch_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("events_seen", sa.Integer(), nullable=False),
        sa.Column("snapshots_seen", sa.Integer(), nullable=False),
        sa.Column("events_persisted", sa.Integer(), nullable=False),
        sa.Column("snapshots_persisted", sa.Integer(), nullable=False),
        sa.Column("coverage_status", sa.String(length=32), nullable=False),
        sa.Column("partial_errors", sa.JSON(), nullable=False),
        sa.Column("quota", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    with op.batch_alter_table("collection_batches", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_collection_batches_collected_at"), ["collected_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_collection_batches_provider"), ["provider"], unique=False
        )

    op.create_table(
        "model_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("sport", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("uncertainty_method", sa.String(length=64), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "version", name="uq_model_version"),
    )
    with op.batch_alter_table("model_registry", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_model_registry_model_id"), ["model_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_model_registry_sport"), ["sport"], unique=False)

    op.create_table(
        "participant_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sport", sa.String(length=32), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("canonical_participant_id", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sport", "alias", name="uq_participant_alias"),
    )
    with op.batch_alter_table("participant_aliases", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_participant_aliases_canonical_participant_id"),
            ["canonical_participant_id"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_participant_aliases_sport"), ["sport"], unique=False)

    op.create_table(
        "scheduler_jobs",
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("scan_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint(
            "job_type", "scheduled_for", "scope_id", name="uq_scheduler_occurrence"
        ),
    )
    with op.batch_alter_table("scheduler_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scheduler_jobs_job_type"), ["job_type"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_scheduler_jobs_scheduled_for"), ["scheduled_for"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_scheduler_jobs_state"), ["state"], unique=False)
        batch_op.create_index("ix_scheduler_state_due", ["state", "scheduled_for"], unique=False)

    op.create_table(
        "event_schedule_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("internal_id", sa.String(length=64), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_start_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["internal_id"],
            ["events.canonical_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("event_schedule_history", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_schedule_history_internal_id"), ["internal_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_schedule_history_recorded_at"), ["recorded_at"], unique=False
        )

    op.create_table(
        "event_source_map",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("internal_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["internal_id"],
            ["events.canonical_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_event_source"),
    )
    with op.batch_alter_table("event_source_map", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_source_map_internal_id"), ["internal_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_source_map_provider"), ["provider"], unique=False
        )

    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_version", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("uncertainty_status", sa.String(length=32), nullable=True))
        batch_op.alter_column("ev_conservative", existing_type=sa.FLOAT(), nullable=True)

    _add_challenge_columns_safely()

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("participant_pair_key", sa.String(length=320), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_events_participant_pair_key"), ["participant_pair_key"], unique=False
        )

    with op.batch_alter_table("odds_snapshots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("line_canonical", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("batch_id", sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f("ix_odds_snapshots_batch_id"), ["batch_id"], unique=False)

    with op.batch_alter_table("scan_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("collection_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("batch_id", sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f("ix_scan_runs_batch_id"), ["batch_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_scan_runs_collection_status"), ["collection_status"], unique=False
        )

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("scan_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scan_runs_collection_status"))
        batch_op.drop_index(batch_op.f("ix_scan_runs_batch_id"))
        batch_op.drop_column("batch_id")
        batch_op.drop_column("collection_status")

    with op.batch_alter_table("odds_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_odds_snapshots_batch_id"))
        batch_op.drop_column("batch_id")
        batch_op.drop_column("line_canonical")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_participant_pair_key"))
        batch_op.drop_column("participant_pair_key")

    with op.batch_alter_table("challenges", schema=None) as batch_op:
        batch_op.drop_column("stop_reason")
        batch_op.drop_column("bank_cents")
        batch_op.drop_column("version")

    with op.batch_alter_table("candidates", schema=None) as batch_op:
        batch_op.alter_column("ev_conservative", existing_type=sa.FLOAT(), nullable=False)
        batch_op.drop_column("uncertainty_status")
        batch_op.drop_column("model_version")

    with op.batch_alter_table("event_source_map", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_source_map_provider"))
        batch_op.drop_index(batch_op.f("ix_event_source_map_internal_id"))

    op.drop_table("event_source_map")
    with op.batch_alter_table("event_schedule_history", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_schedule_history_recorded_at"))
        batch_op.drop_index(batch_op.f("ix_event_schedule_history_internal_id"))

    op.drop_table("event_schedule_history")
    with op.batch_alter_table("scheduler_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_scheduler_state_due")
        batch_op.drop_index(batch_op.f("ix_scheduler_jobs_state"))
        batch_op.drop_index(batch_op.f("ix_scheduler_jobs_scheduled_for"))
        batch_op.drop_index(batch_op.f("ix_scheduler_jobs_job_type"))

    op.drop_table("scheduler_jobs")
    with op.batch_alter_table("participant_aliases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_participant_aliases_sport"))
        batch_op.drop_index(batch_op.f("ix_participant_aliases_canonical_participant_id"))

    op.drop_table("participant_aliases")
    with op.batch_alter_table("model_registry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_registry_sport"))
        batch_op.drop_index(batch_op.f("ix_model_registry_model_id"))

    op.drop_table("model_registry")
    with op.batch_alter_table("collection_batches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_collection_batches_provider"))
        batch_op.drop_index(batch_op.f("ix_collection_batches_collected_at"))

    op.drop_table("collection_batches")
    # ### end Alembic commands ###
