from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Conversation, Message, Report


def history_records(
    database: Session, owner: UUID
) -> tuple[list[Conversation], list[Report]]:
    conversations = database.scalars(
        select(Conversation)
        .where(Conversation.session_id == owner)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).all()
    reports = database.scalars(
        select(Report)
        .join(AnalysisRun, Report.analysis_run_id == AnalysisRun.id)
        .join(Conversation, AnalysisRun.conversation_id == Conversation.id)
        .where(Conversation.session_id == owner)
        .order_by(Report.created_at.desc(), Report.id.desc())
    ).all()
    return list(conversations), list(reports)


def owned_conversation(
    database: Session, owner: UUID, conversation_id: UUID, *, lock: bool = False
) -> Conversation | None:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.session_id == owner
    )
    if lock:
        query = query.with_for_update()
    return database.scalar(query)


def owned_messages(
    database: Session, owner: UUID, conversation_id: UUID
) -> list[Message]:
    messages = database.scalars(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.conversation_id == conversation_id, Conversation.session_id == owner
        )
        .order_by(Message.created_at, Message.id)
    ).all()
    return list(messages)


def owned_analysis(database: Session, owner: UUID, run_id: UUID) -> AnalysisRun | None:
    return database.scalar(
        select(AnalysisRun)
        .join(Conversation, AnalysisRun.conversation_id == Conversation.id)
        .where(AnalysisRun.id == run_id, Conversation.session_id == owner)
    )


def owned_report_binary(
    database: Session, owner: UUID, report_id: UUID
) -> tuple[bytes, bytes] | None:
    report = database.execute(
        select(Report.pdf_data, Report.checksum_sha256)
        .join(AnalysisRun, Report.analysis_run_id == AnalysisRun.id)
        .join(Conversation, AnalysisRun.conversation_id == Conversation.id)
        .where(Report.id == report_id, Conversation.session_id == owner)
    ).one_or_none()
    return (report.pdf_data, report.checksum_sha256) if report is not None else None


def has_active_analysis(database: Session, conversation_id: UUID) -> bool:
    active_run = database.scalar(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.conversation_id == conversation_id,
            AnalysisRun.status.in_(("QUEUED", "RUNNING")),
        )
        .limit(1)
    )
    return active_run is not None
