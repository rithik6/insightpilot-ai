# Synthetic e-commerce dataset

Generate the review snapshot from the repository root in Ubuntu WSL. The default seed is `42`. The default size is 10,000 customers, 200 products, and 100,000 orders. Orders, returns, and closing stock cover January 1, 2024 through December 31, 2025 UTC. Registration dates can precede the sales window.

```sh
uv run --locked python scripts/generate_synthetic.py --seed 42 --output-dir data/generated/synthetic-v1
```

Use `--customers`, `--products`, and `--orders` for smaller snapshots. Use a new output path for each run. Matching settings on Python 3.12 produce byte-identical CSVs. `data/generated/` is ignored by Git.

## Files and joins

| File | Row meaning | Link |
| --- | --- | --- |
| `customers.csv` | One synthetic registration and optional segment | `orders.customer_id` |
| `products.csv` | One catalog item with a synthetic SKU and category | `order_items.product_id`, `inventory_daily.product_id` |
| `orders.csv` | One purchase attempt with a UTC timestamp, region, and status | `order_items.order_id` |
| `order_items.csv` | One order line with quantity, historical unit price, line discount, and unit cost in USD | `returns.order_item_id` |
| `returns.csv` | One return event with quantity, refund amount in USD, UTC timestamp, and status | `order_items.id` |
| `inventory_daily.csv` | Closing stock for one product on one UTC day | Composite key `(product_id, day)` |

Every row is generated from the seed and built-in fictional catalog labels. Customer records contain synthetic IDs, registration times, and segment labels. The [schema and accounting plan](schema.md) defines how completed and fulfilled orders, discounts, approved returns, and inventory feed reporting.

## Planted scenarios

| Scenario | What the generator changes | What to investigate |
| --- | --- | --- |
| Holiday demand | November and December have higher order sampling weights in both years. | Monthly net sales, revenue growth, and seasonality |
| West campaign | July and August 2025 have more West orders. West line discounts are 18% to 28% before rounding. | Regional growth, discount performance, and gross margin |
| Order spike | September 16, 2025 receives seven times its ordinary daily sampling weight. | Daily revenue anomalies and comparison with surrounding days |
| Headphone returns | The generator draws more return events for `SYN-0001`, Studio Headphones 01. | Product return rate and approved refund losses |
| Desk lamp stockout | `SYN-0002`, Desk Lamp 01, records zero closing stock from August 11 through August 24, 2025. The generator excludes the SKU from new orders during that window. | Consecutive stockout days, units sold, and sales after restocking |
| Travel organizer margin | `SYN-0003`, Travel Organizer 01, starts with a higher unit-cost share than other products. | Lowest-margin products and profit change |
| Customer and return histories | Returning buyers and new registrants overlap. Some order lines have multiple return events, including events recorded in a later reporting period. | First purchase, repeat purchase, cohort retention, and return-date accounting |

The weights describe how the default dataset is generated. Verify observed outcomes against the CSVs, especially after changing the seed or row counts. Smaller catalogs may omit some of the named SKUs.

## Validate and load the snapshot

Run validation from the repository root in Ubuntu WSL. This command reads the six UTF-8 CSVs and reports the counts without connecting to PostgreSQL.

```sh
uv run --locked python -m app.db.import_synthetic data/generated/synthetic-v1
```

Validation requires each file's schema columns exactly once and reports the file, line, and violated rule for malformed records. Blank customer segments become SQL `NULL`. Money must have at most two decimal places, timestamps need an explicit offset, and inventory dates use `YYYY-MM-DD`. A header-only `returns.csv` is valid for a snapshot with no return events. Missing inventory dates stay missing.

To load into an already migrated development database, add `--replace`. The importer uses the project's `INSIGHTPILOT_POSTGRES_*` settings to connect. With the local Compose stack, mount the input directory read-only in a one-off app container.

```sh
docker compose run --rm --build \
  --volume "$PWD/data/generated/synthetic-v1:/synthetic:ro" \
  app python -m app.db.import_synthetic /synthetic --replace
```

`--replace` replaces all six business tables as one snapshot. The importer takes a transaction-scoped PostgreSQL advisory lock, deletes in reverse dependency order, bulk-loads in dependency order, and verifies row counts and cross-row rules before committing. A repeated load produces the same records. Any failure rolls back the replacement. Session, conversation, report, and other application tables are outside the replacement. The command reports only status, row counts, timings, and sanitized errors.

## Initial query checks

The seed `42` snapshot loaded twice into a disposable PostgreSQL 17 database in WSL. Both loads produced 463,073 rows across the six tables. The 24 monthly sales and refund totals reconciled to the CSVs. Using `ANALYZE` followed by `EXPLAIN (ANALYZE, BUFFERS)`, a single local run measured these execution times with the [initial schema indexes](schema.md#initial-indexes).

| Query | Result | Execution time |
| --- | --- | ---: |
| Full-window monthly sales, discounts, approved refunds, and cost adjustments | 24 reconciled monthly rows | 382 ms |
| Completed and fulfilled orders on September 16, 2025 UTC | 919 orders | 0.56 ms |
| August 2025 zero closing-stock days for `SYN-0002` | 14 days | 0.05 ms |

These timings describe the local test run. The monthly query aggregates sale lines by order month and approved returns by return month before joining their totals. The day queries filter `orders.ordered_at` and `inventory_daily.day` directly, using half-open date ranges.
