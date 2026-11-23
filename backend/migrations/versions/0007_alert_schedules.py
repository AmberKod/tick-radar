"""定时提醒及执行记录。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
TIME = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


def upgrade():
    op.create_table(
        "t_alert_schedule",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.Column("times", sa.JSON(), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("grace_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.Column("updated_at", TIME, nullable=False),
    )
    op.create_table(
        "t_alert_schedule_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "schedule_id", sa.String(36), sa.ForeignKey("t_alert_schedule.id"), nullable=False
        ),
        sa.Column("schedule_name", sa.String(80), nullable=False),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False),
        sa.Column("scheduled_at", TIME, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("calendar", sa.JSON(), nullable=False),
        sa.Column("outbox_id", sa.String(36)),
        sa.Column("created_at", TIME, nullable=False),
        sa.UniqueConstraint(
            "schedule_id", "session_date", "local_time", name="uq_alert_schedule_run_slot"
        ),
    )
    op.create_index("ix_t_alert_schedule_run_schedule_id", "t_alert_schedule_run", ["schedule_id"])


def downgrade():
    op.drop_index("ix_t_alert_schedule_run_schedule_id", table_name="t_alert_schedule_run")
    op.drop_table("t_alert_schedule_run")
    op.drop_table("t_alert_schedule")
