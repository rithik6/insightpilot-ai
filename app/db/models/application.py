from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import (
    Base,
    RecordedAt,
    RecordId,
    Timestamp,
    UsageCost,
    finite,
    nonblank,
    nonnegative_money,
)


class AnonymousSession(Base):
    __tablename__ = "anonymous_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("expires_at > created_at", name="expiration_after_creation"),
        finite("created_at"),
        finite("expires_at"),
        Index("ix_anonymous_sessions_expires_at", "expires_at"),
    )

    id: Mapped[RecordId]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[RecordedAt]
    expires_at: Mapped[Timestamp]


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        nonblank("title"),
        finite("created_at"),
        finite("updated_at"),
        CheckConstraint("updated_at >= created_at", name="update_after_creation"),
        Index(
            "ix_conversations_session_updated_id",
            "session_id",
            text("updated_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[RecordId]
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("anonymous_sessions.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[RecordedAt]
    updated_at: Mapped[RecordedAt]


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "id", "conversation_id", name="uq_analysis_runs_id_conversation_id"
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'ANSWERED', 'INSUFFICIENT_DATA', 'UNSUPPORTED', "
            "'INTERRUPTED_BUDGET', 'INTERRUPTED_PROVIDER', 'FAILED', 'CANCELED')",
            name="status_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(request_json) = 'object'", name="request_json_object"
        ),
        CheckConstraint(
            "jsonb_typeof(result_json) = 'object'", name="result_json_object"
        ),
        finite("created_at"),
        finite("updated_at"),
        CheckConstraint("updated_at >= created_at", name="update_after_creation"),
        Index(
            "ix_analysis_runs_conversation_created_id",
            "conversation_id",
            "created_at",
            "id",
        ),
        Index("ix_analysis_runs_status_updated_id", "status", "updated_at", "id"),
    )

    id: Mapped[RecordId]
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(24))
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[RecordedAt]
    updated_at: Mapped[RecordedAt]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_run_id", "conversation_id"],
            ["analysis_runs.id", "analysis_runs.conversation_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
        nonblank("content"),
        finite("created_at"),
        Index(
            "ix_messages_conversation_created_id", "conversation_id", "created_at", "id"
        ),
        Index(
            "ix_messages_run_conversation",
            "analysis_run_id",
            "conversation_id",
            postgresql_where=text("analysis_run_id IS NOT NULL"),
        ),
    )

    id: Mapped[RecordId]
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    analysis_run_id: Mapped[UUID | None]
    role: Mapped[str] = mapped_column(String(9))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[RecordedAt]


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        nonblank("title"),
        CheckConstraint(
            "octet_length(pdf_data) BETWEEN 1 AND 5000000", name="pdf_size"
        ),
        CheckConstraint("octet_length(checksum_sha256) = 32", name="checksum_length"),
        finite("created_at"),
    )

    id: Mapped[RecordId]
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str] = mapped_column(String(200))
    pdf_data: Mapped[bytes] = mapped_column(
        LargeBinary, deferred=True, deferred_raiseload=True
    )
    checksum_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[RecordedAt]


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        nonblank("task_name"),
        nonblank("provider"),
        nonblank("model"),
        CheckConstraint(
            "status IN ('RESERVED', 'SUCCEEDED', 'FAILED', 'AMBIGUOUS', 'RELEASED')",
            name="status_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(usage_details) = 'object'", name="usage_details_object"
        ),
        *(
            CheckConstraint(f"{column} >= 0", name=f"{column}_nonnegative")
            for column in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_tokens",
                "latency_ms",
            )
        ),
        nonnegative_money("reserved_cost_usd"),
        nonnegative_money("actual_cost_usd"),
        finite("created_at"),
        Index("ix_llm_usage_created_at", "created_at"),
        Index("ix_llm_usage_run_created", "analysis_run_id", "created_at"),
    )

    id: Mapped[RecordId]
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    task_name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(160))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reserved_cost_usd: Mapped[UsageCost]
    actual_cost_usd: Mapped[UsageCost | None]
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12))
    usage_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[RecordedAt]
