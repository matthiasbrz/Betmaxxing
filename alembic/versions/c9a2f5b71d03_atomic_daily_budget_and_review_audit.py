"""atomic daily budget bucket, review audit trail, notification outbox

Three additions, each closing an anomaly the audit of ``5d2109f`` confirmed.

``provider_budget_days``
    One row per ``(provider, UTC day)``, updated with a single conditional
    statement. The previous design summed the detail table and then inserted,
    which is only atomic on SQLite by accident — PostgreSQL in ``READ COMMITTED``
    lets two transactions read the same total and both insert, so two
    reservations that each fit under the ceiling together exceed it (D-040).
    Existing detail rows are summed once, here, so a database that already spent
    credits today keeps that spend.

``event_mapping_reviews`` audit columns
    ``resolved_at``, ``resolved_by`` and ``resolved_internal_id``: who decided,
    when, and what they decided. A review queue with no record of the decision is
    not an audit trail (D-042).

``notification_outbox``
    ``(job_id, alert_key, channel)`` unique. A fencing token stops a worker that
    lost its lease from *acknowledging*; it cannot unsend a message that was
    already delivered. The outbox makes the send itself at-most-once, so a job
    re-executed after a lease loss cannot notify twice (D-043).

All three are additive. Downgrade drops them and restores the previous nullable
shape; no existing column changes type or nullability.

Revision ID: c9a2f5b71d03
Revises: b7c1e9d24a10
Create Date: 2026-08-05 12:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a2f5b71d03"
down_revision: str | None = "b7c1e9d24a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_day_buckets(connection: sa.Connection) -> None:
    """Seed the counter from the detail rows that already exist.

    Starting every bucket at zero would hand back a full day's budget to any
    deployment that had already spent it — the exact overspend this revision is
    supposed to prevent. Released rows count as zero, and an unknown cost counts
    as its estimate, matching the runtime rule.
    """
    rows = connection.execute(
        sa.text(
            "SELECT provider, day_utc,"
            "       COALESCE(SUM(CASE WHEN released THEN 0"
            "                         ELSE COALESCE(observed_cost, reserved_cost) END), 0)"
            "         AS reserved,"
            "       COALESCE(SUM(CASE WHEN released THEN 0"
            "                         ELSE COALESCE(observed_cost, 0) END), 0)"
            "         AS observed,"
            "       MAX(created_at) AS last_seen"
            "  FROM provider_budget_ledger"
            " GROUP BY provider, day_utc"
        )
    ).fetchall()

    for provider, day_utc, reserved, observed, last_seen in rows:
        connection.execute(
            sa.text(
                "INSERT INTO provider_budget_days"
                " (provider, day_utc, reserved_total, observed_total, updated_at)"
                " VALUES (:provider, :day, :reserved, :observed, :updated)"
            ),
            {
                "provider": provider,
                "day": day_utc,
                "reserved": int(reserved or 0),
                "observed": int(observed or 0),
                "updated": last_seen,
            },
        )


def upgrade() -> None:
    op.create_table(
        "provider_budget_days",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("day_utc", sa.String(length=10), nullable=False),
        sa.Column("reserved_total", sa.Integer(), nullable=False),
        sa.Column("observed_total", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider", "day_utc"),
    )
    _backfill_day_buckets(op.get_bind())

    with op.batch_alter_table("event_mapping_reviews", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("resolved_by", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("resolved_internal_id", sa.String(length=64), nullable=True))

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("alert_key", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "alert_key", "channel", name="uq_notification_effect"),
    )
    with op.batch_alter_table("notification_outbox", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_outbox_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notification_outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_outbox_job_id"))
    op.drop_table("notification_outbox")

    with op.batch_alter_table("event_mapping_reviews", schema=None) as batch_op:
        batch_op.drop_column("resolved_internal_id")
        batch_op.drop_column("resolved_by")
        batch_op.drop_column("resolved_at")

    # The detail table survives, so the counter can be rebuilt from it on the way
    # back up. Nothing is lost by dropping the bucket.
    op.drop_table("provider_budget_days")
