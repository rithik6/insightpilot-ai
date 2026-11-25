"""Read and validate the six CSVs that make up a synthetic business snapshot."""

import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Numeric, Table

from app.db.models import Customer, InventoryDaily, Order, OrderItem, Product, Return

BUSINESS_TABLES = (
    Customer.__table__,
    Product.__table__,
    Order.__table__,
    OrderItem.__table__,
    Return.__table__,
    InventoryDaily.__table__,
)
QUALIFYING_ORDERS = frozenset(("completed", "fulfilled"))
STATUS_VALUES = {
    "orders": QUALIFYING_ORDERS | {"pending", "canceled"},
    "returns": {"approved", "pending", "rejected"},
}
TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
MONEY = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,2})?")
INTEGER = re.compile(r"[0-9]+")
# Analytics group by these labels, so spellings that differ only by case would
# split one group into several.
GROUPING_LABELS = (
    ("customers", "segment"),
    ("products", "category"),
    ("orders", "region"),
)


class SnapshotError(ValueError):
    """A validation error safe to show without including a CSV field value."""


@dataclass(slots=True)
class SourceRow:
    line: int
    values: dict[str, Any]


@dataclass(slots=True)
class Snapshot:
    rows: dict[str, list[SourceRow]]

    @property
    def counts(self) -> dict[str, int]:
        return {table: len(rows) for table, rows in self.rows.items()}


def parse_field(table: Table, column: Column, raw: str) -> Any:
    name = column.name
    if not raw and column.nullable:
        return None
    if isinstance(column.type, Integer):
        minimum = 0 if name == "closing_stock" else 1
        maximum = 2 ** (63 if isinstance(column.type, BigInteger) else 31) - 1
        if INTEGER.fullmatch(raw):
            digits = raw.lstrip("0") or "0"
            if len(digits) <= len(str(maximum)) and minimum <= int(digits) <= maximum:
                return int(digits)
        raise SnapshotError(
            f"{name} must be a whole number from {minimum} to {maximum}, "
            "written as plain digits without separators or spaces."
        )
    if isinstance(column.type, Numeric):
        if MONEY.fullmatch(raw):
            return Decimal(raw)
        raise SnapshotError(
            f"{name} must be a nonnegative amount with up to 12 whole digits and 2 decimal places, "
            "written as plain digits such as 1200.00 without a currency symbol, "
            "thousands separator, or spaces."
        )
    if isinstance(column.type, DateTime):
        if TIMESTAMP.fullmatch(raw):
            try:
                return datetime.fromisoformat(raw).astimezone(UTC)
            except (ValueError, OverflowError):
                pass
        raise SnapshotError(f"{name} must be a valid ISO timestamp with a UTC offset.")
    if isinstance(column.type, Date):
        if DAY.fullmatch(raw):
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
        raise SnapshotError(f"{name} must be a valid date in YYYY-MM-DD format.")
    if name == "status":
        allowed = STATUS_VALUES[table.name]
        if raw not in allowed:
            raise SnapshotError(f"status must be one of {', '.join(sorted(allowed))}.")
        return raw
    if not raw.strip() or "\0" in raw or len(raw) > column.type.length:
        raise SnapshotError(
            f"{name} must be nonblank text of at most {column.type.length} characters."
        )
    if raw != raw.strip():
        raise SnapshotError(f"{name} must not start or end with spaces.")
    return raw


def read_table(directory: Path, table: Table) -> list[SourceRow]:
    filename = f"{table.name}.csv"
    rows = []
    line = 1
    try:
        with (directory / filename).open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            header = next(reader, [])
            columns = list(table.columns.keys())
            if len(header) != len(columns) or set(header) != set(columns):
                raise SnapshotError(
                    f"Expected these columns once each: {', '.join(columns)}."
                )
            while True:
                line = reader.line_num + 1
                fields = next(reader, None)
                if fields is None:
                    break
                if len(fields) != len(header):
                    raise SnapshotError(f"Expected {len(header)} fields in this row.")
                values = {
                    name: parse_field(table, table.columns[name], raw)
                    for name, raw in zip(header, fields, strict=True)
                }
                rows.append(SourceRow(line, values))
    except SnapshotError as error:
        raise SnapshotError(f"{filename}, line {line}: {error}") from None
    except UnicodeError:
        raise SnapshotError(f"{filename}: expected a UTF-8 CSV file.") from None
    except csv.Error:
        raise SnapshotError(f"{filename}, line {line}: malformed CSV record.") from None
    except OSError:
        raise SnapshotError(f"{filename}: cannot read the required file.") from None
    return rows


def row_error(table: str, row: SourceRow, message: str) -> SnapshotError:
    return SnapshotError(f"{table}.csv, line {row.line}: {message}")


def validate_keys(snapshot: Snapshot) -> dict[str, dict[tuple, SourceRow]]:
    indexes = {}
    product_skus = set()
    for table in BUSINESS_TABLES:
        index = {}
        for row in snapshot.rows[table.name]:
            key = tuple(row.values[column.name] for column in table.primary_key)
            if key in index:
                raise row_error(table.name, row, "Duplicate primary key.")
            index[key] = row
            if table.name == "products":
                sku = row.values["sku"]
                if sku in product_skus:
                    raise row_error(table.name, row, "Duplicate SKU.")
                product_skus.add(sku)
            for foreign_key in table.foreign_keys:
                name = foreign_key.parent.name
                related_table = foreign_key.column.table.name
                if (row.values[name],) not in indexes[related_table]:
                    raise row_error(
                        table.name, row, f"{name} has no match in {related_table}.csv."
                    )
        indexes[table.name] = index
    return indexes


def validate_labels(snapshot: Snapshot) -> None:
    for table, column in GROUPING_LABELS:
        spellings: dict[str, tuple[str, int]] = {}
        for row in snapshot.rows[table]:
            label = row.values[column]
            if label is None:
                continue
            spelling, line = spellings.setdefault(label.casefold(), (label, row.line))
            if spelling != label:
                raise row_error(
                    table,
                    row,
                    f"{column} differs only by letter case from the value on line {line}.",
                )


def validate_business_rules(
    snapshot: Snapshot, indexes: dict[str, dict[tuple, SourceRow]]
) -> None:
    orders_with_lines = set()
    for row in snapshot.rows["order_items"]:
        item = row.values
        orders_with_lines.add(item["order_id"])
        if item["discount_amount"] > item["quantity"] * item["unit_list_price"]:
            raise row_error(
                "order_items", row, "Line discount exceeds its merchandise value."
            )

    for row in snapshot.rows["orders"]:
        order = row.values
        customer = indexes["customers"][order["customer_id"],].values
        if order["ordered_at"] < customer["registered_at"]:
            raise row_error("orders", row, "Order predates customer registration.")
        if order["id"] not in orders_with_lines:
            raise row_error("orders", row, "Order has no line item in order_items.csv.")

    approved_units = Counter()
    approved_refunds = Counter()
    for row in snapshot.rows["returns"]:
        event = row.values
        item_key = (event["order_item_id"],)
        item = indexes["order_items"][item_key].values
        order = indexes["orders"][item["order_id"],].values
        if event["returned_at"] < order["ordered_at"]:
            raise row_error("returns", row, "Return predates its order.")
        if event["status"] != "approved":
            continue
        if order["status"] not in QUALIFYING_ORDERS:
            raise row_error(
                "returns",
                row,
                "Approved return requires a completed or fulfilled order.",
            )
        approved_units[item_key] += event["quantity"]
        approved_refunds[item_key] += event["refund_amount"]
        if approved_units[item_key] > item["quantity"]:
            raise row_error(
                "returns",
                row,
                "Approved return quantities exceed the purchased quantity.",
            )
        paid = item["quantity"] * item["unit_list_price"] - item["discount_amount"]
        if approved_refunds[item_key] > paid:
            raise row_error(
                "returns",
                row,
                "Approved refunds exceed the line's discounted merchandise value.",
            )


def read_snapshot(directory: Path) -> Snapshot:
    snapshot = Snapshot(
        {table.name: read_table(directory, table) for table in BUSINESS_TABLES}
    )
    indexes = validate_keys(snapshot)
    validate_labels(snapshot)
    validate_business_rules(snapshot, indexes)
    return snapshot
