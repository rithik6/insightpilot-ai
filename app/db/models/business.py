from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import (
    Base,
    BusinessId,
    Money,
    Timestamp,
    finite,
    nonblank,
    nonnegative_money,
)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        finite("registered_at"),
        nonblank("segment"),
    )

    id: Mapped[BusinessId]
    registered_at: Mapped[Timestamp]
    segment: Mapped[str | None] = mapped_column(String(80))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        nonblank("sku"),
        nonblank("name"),
        nonblank("category"),
    )

    id: Mapped[BusinessId]
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'fulfilled', 'canceled')",
            name="status_valid",
        ),
        finite("ordered_at"),
        nonblank("region"),
        Index("ix_orders_ordered_at_id", "ordered_at", "id"),
        Index("ix_orders_customer_id_ordered_at_id", "customer_id", "ordered_at", "id"),
    )

    id: Mapped[BusinessId]
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT")
    )
    ordered_at: Mapped[Timestamp]
    region: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        nonnegative_money("unit_list_price"),
        nonnegative_money("discount_amount"),
        nonnegative_money("unit_cost"),
        CheckConstraint(
            "discount_amount <= quantity * unit_list_price", name="discount_within_line"
        ),
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_product_id", "product_id"),
    )

    id: Mapped[BusinessId]
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int]
    unit_list_price: Mapped[Money]
    discount_amount: Mapped[Money]
    unit_cost: Mapped[Money]


class Return(Base):
    __tablename__ = "returns"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="status_valid"
        ),
        nonnegative_money("refund_amount"),
        finite("returned_at"),
        Index("ix_returns_order_item_id", "order_item_id"),
        Index("ix_returns_returned_at_id", "returned_at", "id"),
    )

    id: Mapped[BusinessId]
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int]
    refund_amount: Mapped[Money]
    returned_at: Mapped[Timestamp]
    status: Mapped[str] = mapped_column(String(16))


class InventoryDaily(Base):
    __tablename__ = "inventory_daily"
    __table_args__ = (
        finite("day"),
        CheckConstraint("closing_stock >= 0", name="closing_stock_nonnegative"),
        Index("ix_inventory_daily_day_product_id", "day", "product_id"),
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
    closing_stock: Mapped[int]
