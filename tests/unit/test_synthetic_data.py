import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.generate_synthetic import DatasetSize, generate_dataset


def rows(directory: Path, table: str) -> list[dict[str, str]]:
    with (directory / f"{table}.csv").open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def test_generator_produces_the_same_six_files_for_the_same_seed(
    tmp_path: Path,
) -> None:
    size = DatasetSize(customers=25, products=7, orders=400)
    first, second, different = (
        tmp_path / name for name in ("first", "second", "different")
    )
    counts = generate_dataset(first, size, 42)
    assert counts == generate_dataset(second, size, 42)
    assert set(counts) == {
        "customers",
        "products",
        "orders",
        "order_items",
        "returns",
        "inventory_daily",
    }
    assert counts["customers"] == 25
    assert counts["products"] == 7
    assert counts["orders"] == 400
    assert counts["inventory_daily"] == 7 * 731
    for table, count in counts.items():
        assert len(rows(first, table)) == count
        assert (first / f"{table}.csv").read_bytes() == (
            second / f"{table}.csv"
        ).read_bytes()

    generate_dataset(different, size, 43)
    assert (first / "orders.csv").read_bytes() != (
        different / "orders.csv"
    ).read_bytes()


def test_generated_records_respect_date_relationships_and_refund_caps(
    tmp_path: Path,
) -> None:
    output = tmp_path / "snapshot"
    generate_dataset(output, DatasetSize(customers=80, products=12, orders=1_200), 42)
    customers = {row["id"]: row for row in rows(output, "customers")}
    products = {row["id"]: row for row in rows(output, "products")}
    orders = {row["id"]: row for row in rows(output, "orders")}
    lines = {row["id"]: row for row in rows(output, "order_items")}
    refunds = rows(output, "returns")

    assert len({row["sku"] for row in products.values()}) == len(products)
    assert {"pending", "canceled", "completed", "fulfilled"} == {
        row["status"] for row in orders.values()
    }
    assert {"approved", "rejected", "pending"} == {row["status"] for row in refunds}
    assert all(
        customers[row["customer_id"]]["registered_at"] <= row["ordered_at"]
        for row in orders.values()
    )

    paid = {}
    for line_id, line in lines.items():
        assert line["order_id"] in orders and line["product_id"] in products
        quantity = int(line["quantity"])
        discount = Decimal(line["discount_amount"])
        gross = Decimal(line["unit_list_price"]) * quantity
        assert (
            quantity > 0 and Decimal(line["unit_cost"]) >= 0 and 0 <= discount <= gross
        )
        paid[line_id] = gross - discount

    refunded_units: Counter[str] = Counter()
    refunded_amounts: dict[str, Decimal] = {}
    event_counts: Counter[str] = Counter()
    for refund in refunds:
        line_id = refund["order_item_id"]
        order = orders[lines[line_id]["order_id"]]
        assert order["ordered_at"] < refund["returned_at"] < "2026-01-01"
        assert order["status"] in {"completed", "fulfilled"}
        assert int(refund["quantity"]) > 0 and Decimal(refund["refund_amount"]) >= 0
        event_counts[line_id] += 1
        if refund["status"] == "approved":
            refunded_units[line_id] += int(refund["quantity"])
            refunded_amounts[line_id] = refunded_amounts.get(
                line_id, Decimal(0)
            ) + Decimal(refund["refund_amount"])
    assert any(count > 1 for count in event_counts.values())
    assert all(
        total <= int(lines[key]["quantity"]) for key, total in refunded_units.items()
    )
    assert all(total <= paid[key] for key, total in refunded_amounts.items())

    inventory = rows(output, "inventory_daily")
    assert len({(row["product_id"], row["day"]) for row in inventory}) == len(inventory)
    assert all(
        int(row["closing_stock"]) >= 0 and row["product_id"] in products
        for row in inventory
    )
    lamp_zero_days = [
        row["day"]
        for row in inventory
        if row["product_id"] == "2" and row["closing_stock"] == "0"
    ]
    assert lamp_zero_days == [f"2025-08-{day:02}" for day in range(11, 25)]
    assert all(
        orders[row["order_id"]]["ordered_at"][:10] not in lamp_zero_days
        for row in lines.values()
        if row["product_id"] == "2"
    )


def test_generator_keeps_an_existing_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "orders.csv"
    sentinel.write_text("existing content", encoding="utf-8")

    with pytest.raises(FileExistsError):
        generate_dataset(output, DatasetSize(customers=1, products=1, orders=1), 42)

    assert sentinel.read_text(encoding="utf-8") == "existing content"
