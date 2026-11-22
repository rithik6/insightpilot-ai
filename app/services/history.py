from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Conversation, Message, Report


class ConversationInUseError(Exception):
    pass


def list_history(
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


def conversation_history(
    database: Session, owner: UUID, conversation_id: UUID
) -> tuple[Conversation, list[Message]] | None:
    conversation = database.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.session_id == owner
        )
    )
    if conversation is None:
        return None
    messages = database.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    return conversation, list(messages)


def find_analysis(database: Session, owner: UUID, run_id: UUID) -> AnalysisRun | None:
    return database.scalar(
        select(AnalysisRun)
        .join(Conversation, AnalysisRun.conversation_id == Conversation.id)
        .where(AnalysisRun.id == run_id, Conversation.session_id == owner)
    )


def load_report_pdf(database: Session, owner: UUID, report_id: UUID) -> bytes | None:
    report = database.execute(
        select(Report.pdf_data, Report.checksum_sha256)
        .join(AnalysisRun, Report.analysis_run_id == AnalysisRun.id)
        .join(Conversation, AnalysisRun.conversation_id == Conversation.id)
        .where(Report.id == report_id, Conversation.session_id == owner)
    ).one_or_none()
    if report is None:
        return None

    pdf, checksum = report
    if sha256(pdf).digest() != checksum:
        raise ValueError("Saved report checksum mismatch.")

    return pdf


def remove_conversation(database: Session, owner: UUID, conversation_id: UUID) -> bool:
    with database.begin():
        conversation = database.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.session_id == owner)
            .with_for_update()
        )
        if conversation is None:
            return False
        active_run = database.scalar(
            select(AnalysisRun.id)
            .where(
                AnalysisRun.conversation_id == conversation.id,
                AnalysisRun.status.in_(("QUEUED", "RUNNING")),
            )
            .limit(1)
        )
        if active_run is not None:
            raise ConversationInUseError

        database.delete(conversation)
    return True
