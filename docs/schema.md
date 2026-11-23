# PostgreSQL schema and migration plan

InsightPilot AI V1 uses six business tables and six application tables on PostgreSQL 17. Alembic tracks the schema revision in `alembic_version`.

## Business tables

Business IDs are positive `BIGINT` values supplied by the synthetic dataset. Quantities are `INTEGER`. Money is finite `NUMERIC(14, 2)` in USD. Timestamps use finite `TIMESTAMPTZ` values. All listed fields are required except `customers.segment`. Business foreign keys restrict deletion of referenced rows.

| Table | Columns and keys | Row constraints |
| --- | --- | --- |
| `customers` | `id` PK, `registered_at`, `segment VARCHAR(80)` | Segment is nonblank when present. |
| `products` | `id` PK, unique `sku VARCHAR(64)`, `name VARCHAR(200)`, `category VARCHAR(100)` | SKU, name, and category are nonblank. |
| `orders` | `id` PK, `customer_id` FK to `customers`, `ordered_at`, `region VARCHAR(100)`, `status` | Region is nonblank. Status is `pending`, `completed`, `fulfilled`, or `canceled`. |
| `order_items` | `id` PK, `order_id` FK to `orders`, `product_id` FK to `products`, `quantity`, `unit_list_price`, `discount_amount`, `unit_cost` | Quantity is positive. Money is nonnegative. Line discount is at most `quantity × unit_list_price`. |
| `returns` | `id` PK, `order_item_id` FK to `order_items`, `quantity`, `refund_amount`, `returned_at`, `status` | Quantity is positive and refund amount is nonnegative. Status is `pending`, `approved`, or `rejected`. |
| `inventory_daily` | Composite PK `(product_id, day)`, `product_id` FK to `products`, `day DATE`, `closing_stock INTEGER` | Day is finite. Closing stock is nonnegative. |

Order-item prices and costs are snapshots taken at sale time. `discount_amount` and `refund_amount` are line totals. The importer parses money as decimal and rejects values with more than two decimal places. PostgreSQL checks exclude numeric `NaN` explicitly.

### Cross-row validation

The controlled importer is the business-data writer. Before it commits, it validates the complete proposed snapshot inside a transaction. Each order must occur on or after the customer registration time and have at least one line item. Each return must occur on or after its original order. Approved returns must refer to items from qualifying orders. For each order item, the sum of approved return quantities must be at most its purchased quantity, and the sum of approved refunds must be at most its discounted merchandise total.

The importer will take a PostgreSQL transaction-level advisory lock before replacing business data in a `READ COMMITTED` transaction. It will use transactional deletes in reverse foreign-key order and inserts in dependency order, then validate the resulting row counts and cross-row rules before commit. A failed import rolls back the replacement. Application and analytics credentials have read-only access to business data. A multi-query investigation can use a single read-only `REPEATABLE READ` snapshot for consistent results during an import. [PostgreSQL constraints](https://www.postgresql.org/docs/17/ddl-constraints.html#DDL-CONSTRAINTS-CHECK-CONSTRAINTS) · [Transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html) · [Advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS)

## Accounting and reporting dates

- Report in UTC calendar dates. Require an explicit offset on imported timestamps and convert to UTC when deriving a reporting date. Use half-open periods with the start inclusive and the end exclusive. A report covering January 1 through January 31 uses `[January 1 00:00 UTC, February 1 00:00 UTC)`. Apply the same boundaries to sales, returns, and comparisons. Inventory days represent UTC closing stock. A missing inventory row represents missing data.
- Count `completed` and `fulfilled` orders. Recognize merchandise sales, discounts, and original cost of goods sold (COGS) on `ordered_at`. Merchandise values exclude shipping and tax. First purchase is the earliest qualifying order across the available dataset.
- Recognize approved refunds and the cost reversal on `returned_at`, the effective return date for an approved record. Use the original order item and order for product and region attribution. The synthetic dataset assumes each approved return reverses the original unit cost in full. Pending and rejected returns contribute zero to refund and cost adjustments.
- Gross sales equal the sum of `quantity × unit_list_price`. Net sales equal gross sales minus line discounts and approved refunds. Adjusted COGS equals original sale cost minus `returned quantity × original unit cost` for approved returns. Gross profit equals net sales minus adjusted COGS. Gross margin uses total gross profit divided by total net sales when net sales are positive.
- Aggregate sale and return events at their own grain before combining totals. This keeps multiple returns from repeating the original sale. A refund-only period can have negative net sales and adjusted COGS.

For example, an order on January 31 includes two units at $50 each, a $10 line discount, and $20 cost per unit. An approved return on February 3 refunds $45 for one unit.

| Period | Gross sales | Discounts | Refunds | Net sales | Adjusted COGS | Gross profit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| January | $100 | $10 | $0 | $90 | $40 | $50 |
| February | $0 | $0 | $45 | −$45 | −$20 | −$25 |
| Combined | $100 | $10 | $45 | $45 | $20 | $25 |

## Application tables

Application IDs are UUIDs generated by the service. Application timestamps use finite `TIMESTAMPTZ` values. `created_at` and the initial `updated_at` default to the database transaction time. Services advance `updated_at` as part of the corresponding write. All fields are required unless marked nullable. Use named `CHECK` constraints for finite numeric values, valid statuses, and nonblank required text.

| Table | Columns and keys | Constraints and storage |
| --- | --- | --- |
| `anonymous_sessions` | `id` PK, unique `token_hash BYTEA`, `created_at`, `expires_at` | Store the 32-byte SHA-256 digest of the opaque cookie token. Expiration must follow creation. |
| `conversations` | `id` PK, `session_id` FK to `anonymous_sessions`, `title VARCHAR(200)`, `created_at`, `updated_at` | Deleting the session cascades to its conversations. Updated time is at least the creation time. |
| `analysis_runs` | `id` PK, `conversation_id` FK to `conversations`, `status`, `request_json JSONB`, nullable `result_json JSONB`, `created_at`, `updated_at` | Delete with the conversation. Unique `(id, conversation_id)` supports the message ownership check. JSON values are objects when present. Updated time is at least the creation time. |
| `messages` | `id` PK, `conversation_id` FK to `conversations`, nullable `analysis_run_id`, `role`, `content TEXT`, `created_at` | Roles are `user` and `assistant`. Composite FK `(analysis_run_id, conversation_id)` references `analysis_runs (id, conversation_id)` to require a linked run to belong to the same conversation. Delete with the conversation or linked run. |
| `reports` | `id` PK, unique `analysis_run_id` FK to `analysis_runs`, `title VARCHAR(200)`, `pdf_data BYTEA`, `checksum_sha256 BYTEA`, `created_at` | Delete with the run. PDF size is 1 to 5,000,000 bytes. Store a 32-byte SHA-256 digest. History queries project metadata and the ORM defers loading the binary. Downloads verify the digest and use `application/pdf`. |
| `llm_usage` | `id` PK, nullable `analysis_run_id` FK to `analysis_runs`, `task_name VARCHAR(100)`, `provider VARCHAR(80)`, `model VARCHAR(160)`, nullable `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_tokens`, `actual_cost_usd`, and `latency_ms`, plus `reserved_cost_usd`, `status`, `usage_details JSONB`, `created_at` | Token counts and latency use nonnegative `BIGINT`. Costs use finite, nonnegative `NUMERIC(18, 8)`. Usage details are a JSON object, defaulting to an empty object. Deleting a run sets its ledger references to null. |

Analysis status values are `QUEUED`, `RUNNING`, `ANSWERED`, `INSUFFICIENT_DATA`, `UNSUPPORTED`, `INTERRUPTED_BUDGET`, `INTERRUPTED_PROVIDER`, `FAILED`, and `CANCELED`. Request and result snapshots have an explicit `schema_version`. The service validates them with Pydantic and limits serialized UTF-8 requests to 16 KiB and results to 1 MiB. Saved results hold verified evidence, findings, visual specifications, and the sanitized execution trace.

Usage status values are `RESERVED`, `SUCCEEDED`, `FAILED`, `AMBIGUOUS`, and `RELEASED`. Each new reservation is tied to a known analysis run. Unavailable provider counts and costs use null. The gateway normalizes token subsets and records whether cost is estimated or confirmed in `usage_details`. Global spend calculations include detached ledger rows, so deleting history preserves spend and pending commitments. The deletion service will coordinate active work before removing a conversation.

The browser receives a cryptographically random opaque token in an `HttpOnly` and `SameSite` cookie, with `Secure` enabled in production. The server resolves ownership from the token digest and an unexpired session. Conversation, run, and report queries traverse that ownership chain. Cookie-authenticated writes use CSRF and origin checks.

## Initial indexes

Primary keys and unique constraints supply their own indexes. Use B-tree indexes for these access paths.

| Table | Index columns | Access path |
| --- | --- | --- |
| `orders` | `(ordered_at, id)`, `(customer_id, ordered_at, id)` | Date windows and first purchase by customer |
| `order_items` | `(order_id)`, `(product_id)` | Join order lines and product lines |
| `returns` | `(order_item_id)`, `(returned_at, id)` | Per-item history and refund periods |
| `inventory_daily` | `(day, product_id)` | Stockout periods across products |
| `anonymous_sessions` | `(expires_at)` | Expiration maintenance |
| `conversations` | `(session_id, updated_at DESC, id DESC)` | Session history with a stable sort order |
| `analysis_runs` | `(conversation_id, created_at, id)`, `(status, updated_at, id)` | Conversation history and worker status |
| `messages` | `(conversation_id, created_at, id)`, `(analysis_run_id, conversation_id)` where `analysis_run_id IS NOT NULL` | Transcript ordering and linked-run foreign key |
| `llm_usage` | `(created_at)`, `(analysis_run_id, created_at)` | Global budget windows and usage by run |

The unique keys on `anonymous_sessions.token_hash`, `products.sku`, and `reports.analysis_run_id` cover their lookup paths. Add further indexes after measuring representative queries against the synthetic dataset.

## Initial migration and verification

1. Implement SQLAlchemy models and generate one reviewed Alembic revision. Name primary keys, foreign keys, unique constraints, checks, and indexes consistently. Create tables in foreign-key dependency order. Use PostgreSQL-native UUID, JSONB, and BYTEA types. The downgrade removes tables in reverse dependency order. [Alembic documentation](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
2. Run `alembic upgrade head` as a dedicated deployment command using environment-provided database settings. Use a schema-owner credential for migrations and scoped credentials for the application, importer, and analytics in deployed environments.
3. Verify on disposable PostgreSQL 17. Confirm the 12 business and application tables and their keys, checks, and indexes. Exercise missing foreign keys, duplicate unique keys, invalid statuses and amounts, cross-conversation message links, cascade deletion, ledger detachment, and oversized or invalid report fields. Run `alembic check`, downgrade to base, then upgrade again. Test the importer's aggregate rules, repeated replacement, and rollback with real data in Phase 3.
4. Use the initial downgrade on disposable databases only. For a deployment with saved data, prefer a forward fix. If a rollback requires removing the schema, restore a verified PostgreSQL backup together with the compatible application version.

## Request transactions

The API opens a pooled SQLAlchemy engine for its lifespan and closes it at shutdown. Each request gets its own database session. Repositories scope queries to the active owner and services control transaction boundaries. Session creation commits before the browser receives its cookie. History reads that span multiple queries use a repeatable-read snapshot. Failed writes roll back before the request returns a safe storage error, and connection resources return to the pool.
