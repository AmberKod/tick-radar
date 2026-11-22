"""单币种账户、不可删除账本及可重建持仓投影。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None
TIME = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
# 正式MySQL金额列使用DECIMAL；SQLite测试以文本保持十进制精度。
MONEY = sa.String(34).with_variant(sa.Numeric(32, 8), "mysql")


def upgrade():
    op.create_table(
        "t_account",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(64), nullable=False, unique=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.Column("updated_at", TIME, nullable=False),
    )
    op.create_table(
        "t_portfolio_transaction",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("t_account.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("occurred_at", TIME, nullable=False),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("t_security.id")),
        sa.Column("currency", sa.String(3), nullable=False),
        *[
            sa.Column(key, MONEY, nullable=False)
            for key in ("quantity", "price", "amount", "fee", "tax", "gross_amount", "cash_delta")
        ],
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "reversal_of_id",
            sa.String(36),
            sa.ForeignKey("t_portfolio_transaction.id"),
            unique=True,
        ),
        sa.Column("reversed_by_id", sa.String(36)),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column("created_at", TIME, nullable=False),
        sa.UniqueConstraint("account_id", "request_id", name="uq_portfolio_request"),
        sa.UniqueConstraint("account_id", "sequence", name="uq_portfolio_sequence"),
    )
    op.create_index(
        "ix_t_portfolio_transaction_account_id", "t_portfolio_transaction", ["account_id"]
    )
    op.create_table(
        "t_cash_transaction",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("t_account.id"), nullable=False),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("t_portfolio_transaction.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("cash_delta", MONEY, nullable=False),
        sa.Column("created_at", TIME, nullable=False),
    )
    op.create_table(
        "t_portfolio_position",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("t_account.id"), nullable=False),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("t_security.id"), nullable=False),
        *[
            sa.Column(key, MONEY, nullable=False)
            for key in ("quantity", "total_cost", "realized_pnl", "dividend_income")
        ],
        sa.UniqueConstraint("account_id", "security_id", name="uq_portfolio_position"),
    )


def downgrade():
    for name in (
        "t_portfolio_position",
        "t_cash_transaction",
        "t_portfolio_transaction",
        "t_account",
    ):
        op.drop_table(name)
