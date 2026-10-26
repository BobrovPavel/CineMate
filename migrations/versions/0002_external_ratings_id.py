"""External ratings ids: movies.external_ratings_id and users.external_ratings_id.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("movies", "users"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("external_ratings_id", sa.Integer(), nullable=True))
            batch.create_unique_constraint(
                f"uq_{table}_external_ratings_id", ["external_ratings_id"]
            )


def downgrade() -> None:
    for table in ("users", "movies"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_external_ratings_id", type_="unique")
            batch.drop_column("external_ratings_id")
