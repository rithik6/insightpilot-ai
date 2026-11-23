"""Validate or replace the synthetic business snapshot from six local CSV files."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import IsolationLevel, errors, sql
from pydantic import ValidationError
from sqlalchemy.engine import URL

from app.core.config import Settings
from app.db.config import database_url
from app.db.synthetic_snapshot import (
    BUSINESS_TABLES,
    Snapshot,
    SnapshotError,
    read_snapshot,
)

# Shared by every importer transaction so concurrent replacements run serially.
SNAPSHOT_LOCK = int.from_bytes(b"IPAIseed", byteorder="big")
DATABASE_CHECKS = (
    (
        "order registration dates and line items",
        """
        SELECT 1 FROM orders o JOIN customers c ON c.id = o.customer_id
        WHERE o.ordered_at < c.registered_at OR NOT EXISTS (
            SELECT 1 FROM order_items i WHERE i.order_id = o.id
        ) LIMIT 1
        """,
    ),
    (
        "return dates and qualifying order status",
        """
        SELECT 1 FROM returns r
        JOIN order_items i ON i.id = r.order_item_id
        JOIN orders o ON o.id = i.order_id
        WHERE r.returned_at < o.ordered_at
           OR (r.status = 'approved' AND o.status NOT IN ('completed', 'fulfilled'))
        LIMIT 1
        """,
    ),
    (
        "approved return totals",
        """
        SELECT 1 FROM returns r JOIN order_items i ON i.id = r.order_item_id
        WHERE r.status = 'approved'
        GROUP BY i.id
        HAVING sum(r.quantity) > i.quantity
            OR sum(r.refund_amount) > i.quantity * i.unit_list_price - i.discount_amount
        LIMIT 1
        """,
    ),
)


def replace_snapshot(url: URL, snapshot: Snapshot) -> None:
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(conninfo, connect_timeout=5) as connection:
        connection.isolation_level = IsolationLevel.READ_COMMITTED
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (SNAPSHOT_LOCK,))
            for table in reversed(BUSINESS_TABLES):
                cursor.execute(
                    sql.SQL("DELETE FROM {}").format(sql.Identifier(table.name))
                )

            for table in BUSINESS_TABLES:
                columns = list(table.columns.keys())
                statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
                    sql.Identifier(table.name),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                )
                with cursor.copy(statement) as copy:
                    for row in snapshot.rows[table.name]:
                        copy.write_row(tuple(row.values[column] for column in columns))

            for name, expected in snapshot.counts.items():
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))
                )
                if cursor.fetchone() != (expected,):
                    raise SnapshotError(f"PostgreSQL row count mismatch in {name}.")

            for rule, query in DATABASE_CHECKS:
                cursor.execute(query)
                if cursor.fetchone() is not None:
                    raise SnapshotError(f"PostgreSQL verification failed for {rule}.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_dir", type=Path, help="Directory containing the six synthetic CSV files."
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace all six business tables in the configured PostgreSQL database. Without it, only validate the files.",
    )
    args = parser.parse_args(argv)
    try:
        started = perf_counter()
        snapshot = read_snapshot(args.input_dir)
        validated = perf_counter()
        result = {
            "status": "validated",
            "rows": snapshot.counts,
            "validation_seconds": round(validated - started, 3),
        }
        if args.replace:
            url = database_url(Settings())
            replace_snapshot(url, snapshot)
            result["status"] = "loaded"
            result["load_seconds"] = round(perf_counter() - validated, 3)
    except SnapshotError as error:
        print(f"Snapshot failed: {error}", file=sys.stderr)
        return 1
    except ValidationError:
        print("Import failed: check the local InsightPilot settings.", file=sys.stderr)
        return 1
    except ValueError:
        print(
            "Import failed: configure INSIGHTPILOT_POSTGRES_HOST and INSIGHTPILOT_POSTGRES_PASSWORD.",
            file=sys.stderr,
        )
        return 1
    except (errors.UndefinedTable, errors.UndefinedColumn):
        print(
            "Import failed: apply the project's Alembic migrations to the target database.",
            file=sys.stderr,
        )
        return 1
    except errors.InsufficientPrivilege:
        print(
            "Import failed: the configured PostgreSQL role needs read and write access to the business tables.",
            file=sys.stderr,
        )
        return 1
    except psycopg.Error as error:
        state = f" (SQLSTATE {error.sqlstate})" if error.sqlstate else ""
        print(
            f"Import failed: PostgreSQL could not complete the load{state}.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
