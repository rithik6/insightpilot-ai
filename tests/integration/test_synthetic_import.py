import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.engine import URL, Engine

from app.db.import_synthetic import main, replace_snapshot
from app.db.synthetic_snapshot import SnapshotError, read_snapshot


@pytest.fixture
def csv_snapshot(tmp_path: Path) -> Path:
    files = {
        "customers": "id,registered_at,segment\n1,2024-01-01T00:00:00Z,\n",
        "products": "id,sku,name,category\n1,SYN-0001,Lamp,Lighting\n",
        "orders": "id,customer_id,ordered_at,region,status\n1,1,2024-02-01T01:00:00+01:00,North,completed\n",
        "order_items": "id,order_id,product_id,quantity,unit_list_price,discount_amount,unit_cost\n1,1,1,2,10.00,2.00,4.00\n",
        "returns": (
            "id,order_item_id,quantity,refund_amount,returned_at,status\n"
            "1,1,1,9.00,2024-02-05T00:00:00Z,approved\n"
            "2,1,1,9.00,2024-03-05T00:00:00Z,approved\n"
            "3,1,1,9.00,2024-03-06T00:00:00Z,rejected\n"
        ),
        "inventory_daily": "product_id,day,closing_stock\n1,2024-02-01,0\n",
    }
    for table, content in files.items():
        (tmp_path / f"{table}.csv").write_text(content, encoding="utf-8")
    return tmp_path


def change_csv(directory: Path, name: str, old: str, new: str) -> None:
    path = directory / f"{name}.csv"
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def test_validate_only_uses_utc_and_accepts_nullable_segments(
    csv_snapshot: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSIGHTPILOT_ENVIRONMENT", "bad-setting")
    # A BOM and a different column order are valid CSV exports.
    change_csv(
        csv_snapshot,
        "products",
        "id,sku,name,category\n1,SYN-0001,Lamp,Lighting",
        "\ufeffsku,id,category,name\nSYN-0001,1,Lighting,Lamp",
    )
    snapshot = read_snapshot(csv_snapshot)
    assert snapshot.rows["customers"][0].values["segment"] is None
    assert snapshot.rows["orders"][0].values["ordered_at"] == datetime(
        2024, 2, 1, tzinfo=UTC
    )
    assert snapshot.rows["returns"][0].values["refund_amount"] == Decimal("9.00")
    assert main([str(csv_snapshot)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "validated"
    assert output["rows"] == snapshot.counts


@pytest.mark.parametrize(
    ("table", "old", "new", "line", "message"),
    [
        (
            "products",
            "id,sku,name,category",
            "id,sku,sku,category",
            1,
            "Expected these columns",
        ),
        (
            "products",
            "1,SYN-0001,Lamp,Lighting",
            '1,SYN-0001,"Lamp,Lighting',
            2,
            "malformed CSV",
        ),
        ("orders", "completed", "PrivateFieldValue", 2, "status must be one of"),
        ("orders", "1,1,2024", "1,2,2024", 2, "customer_id has no match"),
        (
            "orders",
            "2024-02-01T01:00:00+01:00",
            "2024-02-01T01:00:00",
            2,
            "valid ISO timestamp",
        ),
        (
            "orders",
            "2024-02-01T01:00:00+01:00",
            "2024-01-01T00:30:00+01:00",
            2,
            "predates customer registration",
        ),
        ("order_items", "10.00,2.00", "10.00,20.01", 2, "Line discount exceeds"),
        ("order_items", "10.00,2.00", "10.001,2.00", 2, "2 decimal places"),
        ("inventory_daily", "2024-02-01,0", "2023-02-29,0", 2, "valid date"),
        ("inventory_daily", "2024-02-01,0", "2024-02-01,2147483648", 2, "whole number"),
        (
            "inventory_daily",
            "2024-02-01,0",
            "2024-02-01,0\n1,2024-02-01,1",
            3,
            "Duplicate primary key",
        ),
        (
            "products",
            "SYN-0001,Lamp,Lighting",
            "SYN-0001,Lamp,Lighting\n2,SYN-0001,Lamp,Lighting",
            3,
            "Duplicate SKU",
        ),
        (
            "returns",
            "2024-02-05T00:00:00Z",
            "2024-01-31T23:59:59Z",
            2,
            "Return predates",
        ),
        ("returns", "2,1,1,9.00", "2,1,2,9.00", 3, "Approved return quantities exceed"),
        ("returns", "2,1,1,9.00", "2,1,1,9.01", 3, "Approved refunds exceed"),
        ("orders", "completed", "canceled", 2, "Approved return requires"),
    ],
)
def test_invalid_files_fail_with_a_safe_location(
    csv_snapshot: Path,
    capsys: pytest.CaptureFixture[str],
    table: str,
    old: str,
    new: str,
    line: int,
    message: str,
) -> None:
    change_csv(csv_snapshot, table, old, new)
    assert main([str(csv_snapshot), "--replace"]) == 1
    error = capsys.readouterr().err
    assert f".csv, line {line}:" in error
    assert message in error
    assert "PrivateFieldValue" not in error


def test_missing_required_file(csv_snapshot: Path) -> None:
    (csv_snapshot / "returns.csv").unlink()
    with pytest.raises(
        SnapshotError, match=r"returns\.csv: cannot read the required file"
    ):
        read_snapshot(csv_snapshot)


def test_order_must_have_a_line_item(csv_snapshot: Path) -> None:
    for table in ("returns", "order_items"):
        path = csv_snapshot / f"{table}.csv"
        header = path.read_text(encoding="utf-8").splitlines()[0]
        path.write_text(f"{header}\n", encoding="utf-8")
    with pytest.raises(
        SnapshotError, match=r"orders\.csv, line 2: Order has no line item"
    ):
        read_snapshot(csv_snapshot)


def test_snapshot_replacement_is_repeatable_and_rolls_back_after_copy(
    csv_snapshot: Path, migrated_postgres_url: URL, postgres_engine: Engine
) -> None:
    snapshot = read_snapshot(csv_snapshot)
    replace_snapshot(migrated_postgres_url, snapshot)
    with postgres_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO products VALUES (2, 'stale', 'Stale', 'Test')"
        )

    replace_snapshot(migrated_postgres_url, snapshot)
    with postgres_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "SELECT id FROM products"
        ).scalars().all() == [1]
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM returns").scalar_one() == 3
        )
        assert (
            connection.exec_driver_sql("SELECT segment FROM customers").scalar_one()
            is None
        )
        connection.exec_driver_sql("""
            CREATE FUNCTION skip_inventory_row() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RETURN NULL; END;
            $$
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER skip_inventory_row BEFORE INSERT ON inventory_daily
            FOR EACH ROW EXECUTE FUNCTION skip_inventory_row()
        """)

    change_csv(csv_snapshot, "orders", "North", "South")
    replacement = read_snapshot(csv_snapshot)
    with pytest.raises(SnapshotError, match="row count mismatch in inventory_daily"):
        replace_snapshot(migrated_postgres_url, replacement)

    with postgres_engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT region FROM orders").scalar_one()
            == "North"
        )
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM returns").scalar_one() == 3
        )
        assert (
            connection.exec_driver_sql(
                "SELECT closing_stock FROM inventory_daily"
            ).scalar_one()
            == 0
        )
