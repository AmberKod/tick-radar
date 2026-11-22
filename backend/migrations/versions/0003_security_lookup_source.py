"""扩充公开报价资料来源标识长度，不保存市场价格。"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("t_security") as batch:
        batch.alter_column(
            "source", existing_type=sa.String(10), type_=sa.String(24), existing_nullable=False
        )


def downgrade():
    op.execute("UPDATE t_security SET source='MANUAL' WHERE source='TENCENT_LOOKUP'")
    with op.batch_alter_table("t_security") as batch:
        batch.alter_column(
            "source", existing_type=sa.String(24), type_=sa.String(10), existing_nullable=False
        )
