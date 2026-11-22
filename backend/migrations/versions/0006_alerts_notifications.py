"""观察告警、事务发件箱与站内通知。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
TIME = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


def upgrade():
    op.create_table(
        "t_alert_rule",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("t_security.id"), nullable=False),
        sa.Column("rule_type", sa.String(24), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("threshold", sa.String(34), nullable=False),
        sa.Column("reset_threshold", sa.String(34), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.Column("updated_at", TIME, nullable=False),
    )
    op.create_index("ix_t_alert_rule_security_id", "t_alert_rule", ["security_id"])
    op.create_table(
        "t_alert_rule_state",
        sa.Column("rule_id", sa.String(36), sa.ForeignKey("t_alert_rule.id"), primary_key=True),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("last_value", sa.String(128)),
        sa.Column("last_sample_key", sa.String(64)),
        sa.Column("last_received_at", TIME),
        sa.Column("last_triggered_at", TIME),
        sa.Column("last_reset_at", TIME),
        sa.Column("evaluation_status", sa.String(32), nullable=False),
        sa.Column("evaluation_reason", sa.Text(), nullable=False),
        sa.Column("checked_at", TIME),
        sa.Column("trigger_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "t_alert_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_id", sa.String(36), sa.ForeignKey("t_alert_rule.id"), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("trigger_number", sa.Integer(), nullable=False),
        sa.Column("rule_name", sa.String(80), nullable=False),
        sa.Column("security_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("rule_type", sa.String(24), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("threshold", sa.String(34), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sample_key", sa.String(64), nullable=False),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("quote", sa.JSON(), nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.Column("outbox_id", sa.String(36)),
        sa.UniqueConstraint(
            "rule_id", "trigger_number", name="uq_alert_log_rule_trigger"
        ),
    )
    op.create_index("ix_t_alert_log_rule_id", "t_alert_log", ["rule_id"])
    op.create_table(
        "t_alert_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", TIME, nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.Column("sent_at", TIME),
        sa.Column("last_error", sa.String(160)),
    )
    op.create_index("ix_alert_outbox_due", "t_alert_outbox", ["status", "next_attempt_at"])
    op.create_table(
        "t_alert_delivery",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("outbox_id", sa.String(36), sa.ForeignKey("t_alert_outbox.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(160)),
        sa.Column("created_at", TIME, nullable=False),
        sa.UniqueConstraint("outbox_id", "attempt", name="uq_alert_delivery_attempt"),
    )
    op.create_table(
        "t_notification_inbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "outbox_id",
            sa.String(36),
            sa.ForeignKey("t_alert_outbox.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", TIME),
        sa.Column("created_at", TIME, nullable=False),
    )
    op.create_index("ix_notification_inbox_created", "t_notification_inbox", ["created_at", "id"])


def downgrade():
    for name in (
        "t_notification_inbox",
        "t_alert_delivery",
        "t_alert_outbox",
        "t_alert_log",
        "t_alert_rule_state",
        "t_alert_rule",
    ):
        op.drop_table(name)
