"""跨账户原币划转、实际金额换汇及双端审计关联。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
TIME = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
MONEY = sa.String(34).with_variant(sa.Numeric(32, 8), "mysql")


def upgrade():
    op.create_table(
        "t_portfolio_transfer",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), unique=True, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column(
            "source_account_id", sa.String(36), sa.ForeignKey("t_account.id"), nullable=False
        ),
        sa.Column(
            "target_account_id", sa.String(36), sa.ForeignKey("t_account.id"), nullable=False
        ),
        sa.Column("source_account_name", sa.String(80), nullable=False),
        sa.Column("target_account_name", sa.String(80), nullable=False),
        sa.Column("source_currency", sa.String(3), nullable=False),
        sa.Column("target_currency", sa.String(3), nullable=False),
        sa.Column("source_amount", MONEY, nullable=False),
        sa.Column("target_amount", MONEY, nullable=False),
        sa.Column("source_fee", MONEY, nullable=False),
        sa.Column("implied_rate", sa.String(64), nullable=False),
        sa.Column("rate_basis", sa.String(24), nullable=False),
        sa.Column("occurred_at", TIME, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("source_entry_id", sa.String(36), unique=True, nullable=False),
        sa.Column("target_entry_id", sa.String(36), unique=True, nullable=False),
        sa.Column("source_reversal_entry_id", sa.String(36), unique=True),
        sa.Column("target_reversal_entry_id", sa.String(36), unique=True),
        sa.Column("reversal_request_id", sa.String(36), unique=True),
        sa.Column("reversal_request_hash", sa.String(64)),
        sa.Column("reversal_reason", sa.String(500)),
        sa.Column("reversed_at", TIME),
        sa.Column("created_at", TIME, nullable=False),
    )
    op.create_index(
        "ix_t_portfolio_transfer_source_account_id", "t_portfolio_transfer", ["source_account_id"]
    )
    op.create_index(
        "ix_t_portfolio_transfer_target_account_id", "t_portfolio_transfer", ["target_account_id"]
    )
    with op.batch_alter_table("t_portfolio_transaction") as batch:
        batch.add_column(sa.Column("transfer_id", sa.String(36)))
        batch.create_foreign_key(
            "fk_portfolio_transaction_transfer", "t_portfolio_transfer", ["transfer_id"], ["id"]
        )
        batch.create_index("ix_t_portfolio_transaction_transfer_id", ["transfer_id"])


def downgrade():
    with op.batch_alter_table("t_portfolio_transaction") as batch:
        batch.drop_index("ix_t_portfolio_transaction_transfer_id")
        batch.drop_constraint("fk_portfolio_transaction_transfer", type_="foreignkey")
        batch.drop_column("transfer_id")
    op.drop_index("ix_t_portfolio_transfer_target_account_id", table_name="t_portfolio_transfer")
    op.drop_index("ix_t_portfolio_transfer_source_account_id", table_name="t_portfolio_transfer")
    op.drop_table("t_portfolio_transfer")
