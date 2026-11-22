from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, insert, inspect, select
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, undefer
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.dml import Insert

from app.db.models import (
    AnalysisRun,
    AnonymousSession,
    Conversation,
    Customer,
    InventoryDaily,
    LLMUsage,
    Message,
    Order,
    OrderItem,
    Product,
    Report,
    Return,
)

SOLD_AT = datetime(2026, 1, 31, tzinfo=UTC)
EXPIRY = datetime(2099, 1, 1, tzinfo=UTC)


@pytest.fixture
def migrated_engine(migrated_postgres_url: URL) -> Iterator[Engine]:
    engine = create_engine(
        migrated_postgres_url, poolclass=NullPool, hide_parameters=True
    )
    try:
        yield engine
    finally:
        engine.dispose()


def rejected(connection: Connection, statement: Insert, constraint: str) -> None:
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(statement)
    assert error.value.orig.diag.constraint_name == constraint


def test_initial_revision_round_trip(postgres_url: URL) -> None:
    config = Config("alembic.ini", attributes={"database_url": postgres_url})
    engine = create_engine(postgres_url, poolclass=NullPool, hide_parameters=True)
    tables = {
        "customers",
        "products",
        "orders",
        "order_items",
        "returns",
        "inventory_daily",
        "anonymous_sessions",
        "conversations",
        "analysis_runs",
        "messages",
        "reports",
        "llm_usage",
    }
    try:
        assert inspect(engine).get_table_names() == []
        command.upgrade(config, "head")
        schema = inspect(engine)
        assert set(schema.get_table_names()) == tables | {"alembic_version"}
        assert schema.get_pk_constraint("inventory_daily")["constrained_columns"] == [
            "product_id",
            "day",
        ]
        assert "ix_conversations_session_updated_id" in {
            index["name"] for index in schema.get_indexes("conversations")
        }
        assert "ix_messages_run_conversation" in {
            index["name"] for index in schema.get_indexes("messages")
        }
        command.check(config)

        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == tables | {"alembic_version"}
        command.check(config)
    finally:
        engine.dispose()


def test_business_foreign_keys_unique_and_checks(migrated_engine: Engine) -> None:
    item = {"sku": "SYN-1", "name": "Synthetic item", "category": "Demo"}
    sale = {
        "customer_id": 1,
        "ordered_at": SOLD_AT,
        "region": "West",
        "status": "completed",
    }
    line = {
        "order_id": 1,
        "product_id": 1,
        "quantity": 2,
        "unit_list_price": Decimal("50"),
        "discount_amount": Decimal("10"),
        "unit_cost": Decimal("20"),
    }
    with migrated_engine.begin() as connection:
        rejected(
            connection,
            insert(Order).values(id=1, **sale),
            "fk_orders_customer_id_customers",
        )
        connection.execute(
            insert(Customer).values(id=1, registered_at=SOLD_AT - timedelta(days=1))
        )
        connection.execute(insert(Product).values(id=1, **item))
        rejected(connection, insert(Product).values(id=2, **item), "uq_products_sku")
        rejected(
            connection,
            insert(Product).values(id=2, **(item | {"sku": " \t\n"})),
            "ck_products_sku_nonblank",
        )
        connection.execute(insert(Order).values(id=1, **sale))
        rejected(
            connection,
            insert(Order).values(id=2, **(sale | {"status": "unknown"})),
            "ck_orders_status_valid",
        )
        rejected(
            connection,
            insert(OrderItem).values(
                id=1, **(line | {"quantity": 0, "discount_amount": 0})
            ),
            "ck_order_items_quantity_positive",
        )
        rejected(
            connection,
            insert(OrderItem).values(
                id=1, **(line | {"discount_amount": Decimal("100.01")})
            ),
            "ck_order_items_discount_within_line",
        )
        rejected(
            connection,
            insert(OrderItem).values(id=1, **(line | {"unit_cost": Decimal("NaN")})),
            "ck_order_items_unit_cost_nonnegative",
        )
        connection.execute(insert(OrderItem).values(id=1, **line))
        rejected(
            connection,
            insert(Return).values(
                id=1,
                order_item_id=1,
                quantity=1,
                refund_amount=-1,
                returned_at=SOLD_AT,
                status="approved",
            ),
            "ck_returns_refund_amount_nonnegative",
        )
        stock = insert(InventoryDaily).values(
            product_id=1, day=SOLD_AT.date(), closing_stock=0
        )
        connection.execute(stock)
        rejected(connection, stock, "pk_inventory_daily")


def add_conversation(connection: Connection, token_hash: bytes) -> tuple[UUID, UUID]:
    session = connection.execute(
        insert(AnonymousSession)
        .values(token_hash=token_hash, expires_at=EXPIRY)
        .returning(AnonymousSession.id)
    ).scalar_one()
    conversation = connection.execute(
        insert(Conversation)
        .values(session_id=session, title="Test analysis")
        .returning(Conversation.id)
    ).scalar_one()
    return session, conversation


def test_application_ownership_and_ledger_deletion(migrated_engine: Engine) -> None:
    run, usage = uuid4(), uuid4()
    with migrated_engine.begin() as connection:
        owner, conversation_a = add_conversation(connection, b"a" * 32)
        _, conversation_b = add_conversation(connection, b"b" * 32)
        connection.execute(
            insert(AnalysisRun).values(
                id=run,
                conversation_id=conversation_a,
                status="QUEUED",
                request_json={"schema_version": 1},
            )
        )
        rejected(
            connection,
            insert(Message).values(
                conversation_id=conversation_b,
                analysis_run_id=run,
                role="assistant",
                content="Cross-session",
            ),
            "fk_messages_analysis_run_id_analysis_runs",
        )
        rejected(
            connection,
            insert(AnalysisRun).values(
                conversation_id=conversation_a, status="QUEUED", request_json=[]
            ),
            "ck_analysis_runs_request_json_object",
        )
        connection.execute(
            insert(Message).values(
                conversation_id=conversation_a,
                analysis_run_id=run,
                role="assistant",
                content="Owned",
            )
        )
        connection.execute(
            insert(LLMUsage).values(
                id=usage,
                analysis_run_id=run,
                task_name="plan",
                provider="test",
                model="test",
                reserved_cost_usd=Decimal("0.00234567"),
                status="RESERVED",
            )
        )

        connection.execute(delete(AnonymousSession).where(AnonymousSession.id == owner))
        assert connection.execute(select(Conversation.id)).scalars().all() == [
            conversation_b
        ]
        assert connection.execute(select(AnalysisRun.id)).first() is None
        assert connection.execute(select(Message.id)).first() is None
        ledger = connection.execute(
            select(LLMUsage.analysis_run_id, LLMUsage.reserved_cost_usd).where(
                LLMUsage.id == usage
            )
        ).one()
        assert tuple(ledger) == (None, Decimal("0.00234567"))


def test_report_constraints_and_deferred_binary(migrated_engine: Engine) -> None:
    pdf = b"%PDF-1.4 synthetic test"
    with migrated_engine.begin() as connection:
        _, conversation = add_conversation(connection, b"s" * 32)
        run = connection.execute(
            insert(AnalysisRun)
            .values(
                conversation_id=conversation,
                status="ANSWERED",
                request_json={"schema_version": 1},
            )
            .returning(AnalysisRun.id)
        ).scalar_one()
        report = {
            "analysis_run_id": run,
            "title": "Result",
            "pdf_data": pdf,
            "checksum_sha256": sha256(pdf).digest(),
        }
        rejected(
            connection,
            insert(Report).values(**(report | {"pdf_data": b"x" * 5_000_001})),
            "ck_reports_pdf_size",
        )
        rejected(
            connection,
            insert(Report).values(**(report | {"checksum_sha256": b"short"})),
            "ck_reports_checksum_length",
        )
        report_id = connection.execute(
            insert(Report).values(**report).returning(Report.id)
        ).scalar_one()
        rejected(
            connection, insert(Report).values(**report), "uq_reports_analysis_run_id"
        )

    with Session(migrated_engine) as session:
        saved = session.get(Report, report_id)
        assert saved is not None and saved.title == "Result"
        with pytest.raises(InvalidRequestError, match="raiseload"):
            _ = saved.pdf_data
        loaded = session.scalars(
            select(Report)
            .where(Report.id == report_id)
            .options(undefer(Report.pdf_data))
        ).one()
        assert loaded.pdf_data == pdf
