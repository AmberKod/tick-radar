"""证券主数据和单用户自选。"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001_system_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "t_security",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(40), nullable=False, unique=True),
        sa.Column("market", sa.String(2), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("security_type", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "t_watchlist_group",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "t_watchlist",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("t_watchlist_group.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("t_security.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.UniqueConstraint("group_id", "security_id", name="uq_watchlist_group_security"),
    )


def downgrade():
    op.drop_table("t_watchlist")
    op.drop_table("t_watchlist_group")
    op.drop_table("t_security")
