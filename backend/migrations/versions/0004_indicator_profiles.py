"""持久化指标配置与乐观锁版本。"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "t_indicator_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(3), nullable=False),
        sa.Column("price_adjustment", sa.String(20), nullable=False),
        sa.Column("market_scope", sa.String(3), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name_key", name="uq_indicator_profile_name_key"),
        sa.CheckConstraint("version >= 1", name="ck_indicator_profile_version"),
    )


def downgrade():
    op.drop_table("t_indicator_profile")
