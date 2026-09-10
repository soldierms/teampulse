import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class MetricRollup(Base):
    """Aggregated metric values. One row per (scope, grain, period, metric).

    Team-level rows carry team_id with user_id NULL; person-level rows carry both.
    """

    __tablename__ = "metric_rollups"
    __table_args__ = (
        # NULLS NOT DISTINCT so ON CONFLICT still matches rows where user_id is
        # NULL — without it every team-level recompute would insert a duplicate.
        UniqueConstraint(
            "org_id",
            "team_id",
            "user_id",
            "grain",
            "period_start",
            "metric_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_metric_rollups_lookup", "org_id", "team_id", "metric_key", "period_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    grain: Mapped[str] = mapped_column(String(10))
    period_start: Mapped[date] = mapped_column(Date)
    metric_key: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
