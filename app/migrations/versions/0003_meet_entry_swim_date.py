"""meet entry swim date

Meet entries get an optional `swim_date`: the day of a multi-day meet the
event was swum (the routers keep it within the meet's dates).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16 17:23:36.906663

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("meet_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("swim_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("meet_entries", schema=None) as batch_op:
        batch_op.drop_column("swim_date")
