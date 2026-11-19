"""meet entry event number

Meet entries get an optional `event_number`: the meet's number for the event
("Event 12" in the heat sheet and results).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18 19:13:01.088840

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("meet_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("meet_entries", schema=None) as batch_op:
        batch_op.drop_column("event_number")
