from hashlib import sha256
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Conversation, Message, Report
from app.db.repositories.history import (
    has_active_analysis,
    history_records,
    owned_analysis,
    owned_conversation,
    owned_messages,
    owned_report_binary,
)


class ConversationInUseError(Exception):
    pass


def list_history(
    database: Session, owner: UUID
) -> tuple[list[Conversation], list[Report]]:
    with database.begin():
        database.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        return history_records(database, owner)


def conversation_history(
    database: Session, owner: UUID, conversation_id: UUID
) -> tuple[Conversation, list[Message]] | None:
    with database.begin():
        database.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        conversation = owned_conversation(database, owner, conversation_id)
        if conversation is None:
            return None
        return conversation, owned_messages(database, owner, conversation_id)


def find_analysis(database: Session, owner: UUID, run_id: UUID) -> AnalysisRun | None:
    with database.begin():
        return owned_analysis(database, owner, run_id)


def load_report_pdf(database: Session, owner: UUID, report_id: UUID) -> bytes | None:
    with database.begin():
        report = owned_report_binary(database, owner, report_id)
    if report is None:
        return None

    pdf, checksum = report
    if sha256(pdf).digest() != checksum:
        raise ValueError("Saved report checksum mismatch.")
    return pdf


def remove_conversation(database: Session, owner: UUID, conversation_id: UUID) -> bool:
    with database.begin():
        conversation = owned_conversation(database, owner, conversation_id, lock=True)
        if conversation is None:
            return False
        if has_active_analysis(database, conversation.id):
            raise ConversationInUseError

        database.delete(conversation)
    return True
