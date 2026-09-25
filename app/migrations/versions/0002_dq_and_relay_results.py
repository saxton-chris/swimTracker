"""dq and relay results

Events get a `relay` flag (part of the uniqueness key, so "200 FR LCM" and
"200 FR-R LCM" are different events). Swim times can be a DQ (time optional,
with a reason) and carry a relay leg and split.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25 14:59:41.710413

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("relay", sa.Boolean(), server_default=sa.text("0"), nullable=False))
        batch_op.drop_constraint(batch_op.f("uix_event"), type_="unique")
        batch_op.create_unique_constraint("uix_event", ["distance", "stroke", "course", "relay"])

    with op.batch_alter_table("swim_times", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dq", sa.Boolean(), server_default=sa.text("0"), nullable=False))
        batch_op.add_column(sa.Column("dq_reason", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("relay_leg", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("split_seconds", sa.Float(), nullable=True))
        batch_op.alter_column("time_seconds", existing_type=sa.FLOAT(), nullable=True)
        batch_op.create_check_constraint("ck_swim_time_needs_time_unless_dq", "dq OR time_seconds IS NOT NULL")
        batch_op.create_check_constraint("ck_swim_time_relay_leg", "relay_leg BETWEEN 1 AND 4")


def downgrade() -> None:
    # The old schema can't hold relays or time-less DQs: remove them first, or the
    # NOT NULL / old unique constraint would reject the rebuilt tables.
    op.execute("DELETE FROM swim_times WHERE time_seconds IS NULL")
    op.execute(
        "DELETE FROM swim_times WHERE meet_entry_id IN "
        "(SELECT me.id FROM meet_entries me JOIN events e ON e.id = me.event_id WHERE e.relay)"
    )
    op.execute("DELETE FROM meet_entries WHERE event_id IN (SELECT id FROM events WHERE relay)")
    op.execute("DELETE FROM events WHERE relay")

    with op.batch_alter_table("swim_times", schema=None) as batch_op:
        batch_op.drop_constraint("ck_swim_time_relay_leg", type_="check")
        batch_op.drop_constraint("ck_swim_time_needs_time_unless_dq", type_="check")
        batch_op.alter_column("time_seconds", existing_type=sa.FLOAT(), nullable=False)
        batch_op.drop_column("split_seconds")
        batch_op.drop_column("relay_leg")
        batch_op.drop_column("dq_reason")
        batch_op.drop_column("dq")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_constraint("uix_event", type_="unique")
        batch_op.create_unique_constraint(batch_op.f("uix_event"), ["distance", "stroke", "course"])
        batch_op.drop_column("relay")
