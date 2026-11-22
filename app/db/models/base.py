from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    MetaData,
    Numeric,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


BusinessId = Annotated[
    int, mapped_column(BigInteger, primary_key=True, autoincrement=False)
]
RecordId = Annotated[UUID, mapped_column(Uuid, primary_key=True, default=uuid4)]
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]
RecordedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]
Money = Annotated[Decimal, mapped_column(Numeric(14, 2))]
UsageCost = Annotated[Decimal, mapped_column(Numeric(18, 8))]


def finite(column: str) -> CheckConstraint:
    return CheckConstraint(f"isfinite({column})", name=f"{column}_finite")


def nonblank(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '[^[:space:]]'", name=f"{column}_nonblank")


def nonnegative_money(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} >= 0 AND {column} <> 'NaN'::numeric", name=f"{column}_nonnegative"
    )
