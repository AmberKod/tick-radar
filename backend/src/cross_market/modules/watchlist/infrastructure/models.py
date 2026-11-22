from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cross_market.shared.database import Base


class WatchlistGroup(Base):
    __tablename__ = "t_watchlist_group"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    position: Mapped[int] = mapped_column(Integer)


class WatchlistItem(Base):
    __tablename__ = "t_watchlist"
    __table_args__ = (
        UniqueConstraint("group_id", "security_id", name="uq_watchlist_group_security"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("t_watchlist_group.id", ondelete="CASCADE")
    )
    security_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("t_security.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(500), default="")
