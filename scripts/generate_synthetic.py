"""Generate the InsightPilot AI V1 synthetic business snapshot as six CSVs."""

import argparse
import csv
from bisect import bisect_right
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import accumulate
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from typing import NamedTuple

START = date(2024, 1, 1)
END = date(2026, 1, 1)
CAMPAIGN_START = date(2025, 7, 1)
CAMPAIGN_END = date(2025, 9, 1)
VOLUME_SPIKE = date(2025, 9, 16)
STOCKOUT_START = date(2025, 8, 11)
STOCKOUT_END = date(2025, 8, 25)
REGIONS = ("East", "North", "South", "West")
QUALIFYING_STATUSES = {"completed", "fulfilled"}
MONTH_WEIGHT = (0.89, 0.84, 0.94, 0.96, 1.02, 0.98, 1.04, 1.05, 1.01, 1.10, 1.68, 1.53)

FIELDS = {
    "customers": ("id", "registered_at", "segment"),
    "products": ("id", "sku", "name", "category"),
    "orders": ("id", "customer_id", "ordered_at", "region", "status"),
    "order_items": (
        "id",
        "order_id",
        "product_id",
        "quantity",
        "unit_list_price",
        "discount_amount",
        "unit_cost",
    ),
    "returns": (
        "id",
        "order_item_id",
        "quantity",
        "refund_amount",
        "returned_at",
        "status",
    ),
    "inventory_daily": ("product_id", "day", "closing_stock"),
}


class Category(NamedTuple):
    name: str
    items: tuple[str, ...]
    minimum_price: int
    maximum_price: int


CATALOG = (
    Category(
        "Audio",
        ("Studio Headphones", "Portable Speaker", "Wireless Earbuds"),
        2_500,
        19_000,
    ),
    Category("Lighting", ("Desk Lamp", "Reading Light", "Floor Lamp"), 1_600, 13_500),
    Category(
        "Travel", ("Travel Organizer", "Weekender Bag", "Packing Cubes"), 1_500, 12_500
    ),
    Category(
        "Home & Kitchen",
        ("Glass Carafe", "Kitchen Scale", "Cookware Set"),
        1_200,
        18_000,
    ),
    Category("Office", ("Desk Mat", "Monitor Stand", "Notebook Set"), 1_100, 9_500),
    Category(
        "Fitness", ("Exercise Mat", "Resistance Bands", "Water Bottle"), 900, 10_500
    ),
    Category(
        "Accessories", ("Cable Organizer", "Laptop Sleeve", "USB Hub"), 750, 8_800
    ),
    Category(
        "Outdoor", ("Camping Lantern", "Daypack", "Insulated Flask"), 1_900, 15_000
    ),
)


@dataclass(frozen=True)
class DatasetSize:
    customers: int = 10_000
    products: int = 200
    orders: int = 100_000

    def __post_init__(self) -> None:
        if min(self.customers, self.products, self.orders) < 1:
            raise ValueError("Customer, product, and order counts must be positive.")


class Customer(NamedTuple):
    id: int
    registered_day: date
    segment: str
    region: str


class Product(NamedTuple):
    id: int
    sku: str
    name: str
    category: str
    base_price: int
    cost_rate: int
    demand: float


def timestamp(day: date, minute: int = 0) -> str:
    return datetime.combine(day, time(*divmod(minute, 60), tzinfo=UTC)).isoformat()


def dollars(cents: int) -> str:
    whole, fractional = divmod(cents, 100)
    return f"{whole}.{fractional:02d}"


def percent(cents: int, rate: int) -> int:
    return (cents * rate + 50) // 100


def generate_customers(rng: Random, count: int) -> list[Customer]:
    # The earliest registrant keeps the first sales day usable for small datasets.
    offsets = [
        -240,
        *(rng.randrange(-239, (END - START).days) for _ in range(count - 1)),
    ]
    return [
        Customer(
            identifier,
            START + timedelta(days=offset),
            rng.choices(("Retail", "Member", "Small business", ""), (60, 25, 11, 4))[0],
            rng.choices(REGIONS, (28, 24, 26, 22))[0],
        )
        for identifier, offset in enumerate(sorted(offsets), 1)
    ]


def generate_products(rng: Random, count: int) -> list[Product]:
    products = []
    for index in range(count):
        variant, category_index = divmod(index, len(CATALOG))
        category = CATALOG[category_index]
        model, item_index = divmod(variant, len(category.items))
        product_id = index + 1
        products.append(
            Product(
                product_id,
                f"SYN-{product_id:04d}",
                f"{category.items[item_index]} {model + 1:02d}",
                category.name,
                rng.randint(category.minimum_price, category.maximum_price),
                92 if product_id == 3 else rng.randint(38, 72),
                4.5 if product_id <= 3 else 0.5 + 3.5 * rng.random() ** 2,
            )
        )
    return products


def day_weight(day: date) -> float:
    holiday = MONTH_WEIGHT[day.month - 1]
    weekend = 1.15 if day.weekday() >= 5 else 1.0
    growth = 1.17 if day.year == 2025 else 1.0
    spike = 7.0 if day == VOLUME_SPIKE else 1.0
    return holiday * weekend * growth * spike


def choose_products(
    rng: Random, products: list[Product], weights: list[float], count: int
) -> list[Product]:
    selected: dict[int, Product] = {}
    while len(selected) < min(count, len(products)):
        product = rng.choices(products, cum_weights=weights)[0]
        selected[product.id] = product
    return list(selected.values())


def line_returns(
    rng: Random, day: date, product_id: int, quantity: int, paid: int
) -> list[tuple[int, int, str, str]]:
    available_days = (END - day).days - 1
    if available_days < 1 or rng.random() >= (0.32 if product_id == 1 else 0.068):
        return []

    returned_quantity = rng.randint(1, quantity)
    quantities = [returned_quantity]
    if returned_quantity > 1 and available_days >= 2 and rng.random() < 0.45:
        first = rng.randrange(1, returned_quantity)
        quantities = [first, returned_quantity - first]

    dates = sorted(rng.sample(range(1, min(available_days, 45) + 1), len(quantities)))
    returns = []
    cumulative_quantity = 0
    allocated = 0
    for units, delay in zip(quantities, dates, strict=True):
        cumulative_quantity += units
        cumulative_amount = paid * cumulative_quantity // quantity
        refund = cumulative_amount - allocated
        allocated = cumulative_amount
        returned_at = timestamp(day + timedelta(days=delay), rng.randrange(24 * 60))
        status = rng.choices(("approved", "pending", "rejected"), (84, 10, 6))[0]
        returns.append((units, refund, returned_at, status))
    return returns


def write_dataset(directory: Path, size: DatasetSize, seed: int) -> dict[str, int]:
    rng = Random(seed)
    customers = generate_customers(rng, size.customers)
    registered = [record.registered_day for record in customers]
    products = generate_products(rng, size.products)
    available_during_stockout = [product for product in products if product.id != 2]
    weights = list(accumulate(product.demand for product in products))
    stockout_weights = list(
        accumulate(product.demand for product in available_during_stockout)
    )
    days = [START + timedelta(days=offset) for offset in range((END - START).days)]
    dates = sorted(
        (day, rng.randrange(24 * 60))
        for day in rng.choices(
            days, weights=[day_weight(day) for day in days], k=size.orders
        )
    )
    counts: Counter[str] = Counter()
    units_sold: Counter[tuple[int, date]] = Counter()
    buyers: list[Customer] = []
    buyer_ids: set[int] = set()

    with ExitStack() as stack:
        writers = {
            table: csv.writer(
                stack.enter_context(
                    (directory / f"{table}.csv").open("w", encoding="utf-8", newline="")
                ),
                lineterminator="\n",
            )
            for table in FIELDS
        }
        for table, columns in FIELDS.items():
            writers[table].writerow(columns)
        writers["customers"].writerows(
            (row.id, timestamp(row.registered_day), row.segment) for row in customers
        )
        writers["products"].writerows(
            (row.id, row.sku, row.name, row.category) for row in products
        )
        counts.update(
            customers=size.customers, products=size.products, orders=size.orders
        )

        for order_id, (day, minute) in enumerate(dates, 1):
            customer = (
                rng.choice(buyers)
                if buyers and rng.random() < 0.36
                else customers[rng.randrange(bisect_right(registered, day))]
            )
            region = customer.region if rng.random() < 0.88 else rng.choice(REGIONS)
            if CAMPAIGN_START <= day < CAMPAIGN_END and rng.random() < 0.43:
                region = "West"
            status = rng.choices(
                ("completed", "fulfilled", "canceled", "pending"), (62, 31, 5, 2)
            )[0]
            eligible = status in QUALIFYING_STATUSES
            writers["orders"].writerow(
                (order_id, customer.id, timestamp(day, minute), region, status)
            )
            if eligible and customer.id not in buyer_ids:
                buyers.append(customer)
                buyer_ids.add(customer.id)

            pool, pool_weights = (
                (available_during_stockout, stockout_weights)
                if STOCKOUT_START <= day < STOCKOUT_END
                else (products, weights)
            )
            lines = rng.choices((1, 2, 3, 4), (38, 37, 19, 6))[0]
            for product in choose_products(rng, pool, pool_weights, lines):
                quantity = rng.choices((1, 2, 3, 4), (72, 19, 7, 2))[0]
                if customer.segment == "Small business" and rng.random() < 0.21:
                    quantity += rng.randint(1, 3)
                price = percent(product.base_price, rng.randint(94, 108))
                discount_rate = rng.choices((0, 5, 10, 15, 20), (49, 14, 18, 15, 4))[0]
                if region == "West" and CAMPAIGN_START <= day < CAMPAIGN_END:
                    discount_rate = rng.randint(18, 28)
                elif day.month in (11, 12) and rng.random() < 0.36:
                    discount_rate = rng.randint(12, 25)
                discount = percent(price * quantity, discount_rate)
                cost = percent(
                    product.base_price,
                    product.cost_rate + (3 if day.year == 2025 else 0),
                )
                counts["order_items"] += 1
                line_id = counts["order_items"]
                writers["order_items"].writerow(
                    (
                        line_id,
                        order_id,
                        product.id,
                        quantity,
                        dollars(price),
                        dollars(discount),
                        dollars(cost),
                    )
                )
                if not eligible:
                    continue

                units_sold[product.id, day] += quantity
                for units, refund, returned_at, state in line_returns(
                    rng, day, product.id, quantity, price * quantity - discount
                ):
                    counts["returns"] += 1
                    writers["returns"].writerow(
                        (
                            counts["returns"],
                            line_id,
                            units,
                            dollars(refund),
                            returned_at,
                            state,
                        )
                    )

        for product in products:
            replenishment = int(8 + product.demand * 6)
            stock = replenishment
            for day in days:
                sold = units_sold[product.id, day]
                if product.id == 2 and STOCKOUT_START <= day < STOCKOUT_END:
                    stock = 0
                else:
                    if day.weekday() == product.id % 7 or stock < sold:
                        stock = max(stock, replenishment, sold)
                    stock -= sold
                    if product.id == 2 and stock == 0:
                        stock = replenishment
                writers["inventory_daily"].writerow(
                    (product.id, day.isoformat(), stock)
                )
        counts["inventory_daily"] = len(products) * len(days)

    return {table: counts[table] for table in FIELDS}


def generate_dataset(output: Path, size: DatasetSize, seed: int) -> dict[str, int]:
    if output.exists():
        raise FileExistsError(
            f"Choose a new output directory. This path already exists: {output}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".synthetic-", dir=output.parent) as staging:
        staging_path = Path(staging)
        counts = write_dataset(staging_path, size, seed)
        staging_path.rename(output)
    return counts


def main() -> None:
    defaults = DatasetSize()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/generated/synthetic-v1")
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--customers", type=int, default=defaults.customers)
    parser.add_argument("--products", type=int, default=defaults.products)
    parser.add_argument("--orders", type=int, default=defaults.orders)
    args = parser.parse_args()
    try:
        counts = generate_dataset(
            args.output_dir,
            DatasetSize(args.customers, args.products, args.orders),
            args.seed,
        )
    except (ValueError, OSError) as error:
        parser.exit(1, f"Generation failed: {error}\n")
    for table, rows in counts.items():
        print(f"{table}.csv {rows:,} rows")


if __name__ == "__main__":
    main()
