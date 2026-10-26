"""User pools: users.pool ('ru' for CSV-imported users, 'world' for the rest).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

users = sa.table(
    "users", sa.column("pool", sa.String), sa.column("external_ratings_id", sa.Integer)
)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("pool", sa.String(length=8), nullable=False, server_default="world")
        )
        batch.create_check_constraint("ck_users_pool", "pool IN ('ru', 'world')")
    op.get_bind().execute(
        sa.update(users).where(users.c.external_ratings_id.is_not(None)).values(pool="ru")
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_pool", type_="check")
        batch.drop_column("pool")
