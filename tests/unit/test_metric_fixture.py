from datetime import UTC, datetime
from pathlib import Path

from app.db.synthetic_snapshot import read_snapshot

# Hand-calculated expectations for this fixture live in docs/metrics.md.
FIXTURE = Path(__file__).parents[1] / "fixtures" / "metrics-v1"


def test_metric_fixture_is_a_valid_snapshot() -> None:
    snapshot = read_snapshot(FIXTURE)

    assert snapshot.counts == {
        "customers": 3,
        "products": 2,
        "orders": 6,
        "order_items": 7,
        "returns": 5,
        "inventory_daily": 4,
    }


def test_metric_fixture_boundary_orders_resolve_to_documented_utc_months() -> None:
    orders = {
        row.values["id"]: row.values["ordered_at"]
        for row in read_snapshot(FIXTURE).rows["orders"]
    }

    # 00:30 at +01:00 on February 1 is still January 31 in UTC.
    assert orders[2] == datetime(2025, 1, 31, 23, 30, tzinfo=UTC)
    # A period start is inclusive, so this order belongs to February.
    assert orders[4] == datetime(2025, 2, 1, tzinfo=UTC)
