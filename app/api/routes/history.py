from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import (
    ActiveSession,
    DatabaseSession,
    WriteSession,
    require_trusted_origin,
)
from app.services.history import (
    ConversationInUseError,
    conversation_history,
    find_analysis,
    list_history,
    load_report_pdf,
    remove_conversation,
)


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_response)])


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID | None
    role: str
    content: str
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageDetail]


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID
    title: str
    created_at: datetime


class HistoryResponse(BaseModel):
    conversations: list[ConversationSummary]
    reports: list[ReportSummary]


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    result_json: dict[str, Any] | None


@router.get("/history")
def history(database: DatabaseSession, owner: ActiveSession) -> HistoryResponse:
    conversations, reports = list_history(database, owner)
    return HistoryResponse(
        conversations=[
            ConversationSummary.model_validate(row) for row in conversations
        ],
        reports=[ReportSummary.model_validate(row) for row in reports],
    )


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: UUID, database: DatabaseSession, owner: ActiveSession
) -> ConversationDetail:
    saved = conversation_history(database, owner, conversation_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    record, messages = saved
    return ConversationDetail(
        **ConversationSummary.model_validate(record).model_dump(),
        messages=[MessageDetail.model_validate(message) for message in messages],
    )


@router.get("/analyses/{analysis_id}")
def analysis(
    analysis_id: UUID, database: DatabaseSession, owner: ActiveSession
) -> AnalysisResponse:
    run = find_analysis(database, owner, analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return AnalysisResponse.model_validate(run)


@router.get("/reports/{report_id}/download", response_class=Response)
def download_report(
    report_id: UUID, database: DatabaseSession, owner: ActiveSession
) -> Response:
    pdf = load_report_pdf(database, owner, report_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="insightpilot-report.pdf"',
        },
    )


@router.delete(
    "/history/{conversation_id}",
    status_code=204,
    dependencies=[Depends(require_trusted_origin)],
)
def delete_history(
    conversation_id: UUID, database: DatabaseSession, owner: WriteSession
) -> None:
    try:
        removed = remove_conversation(database, owner, conversation_id)
    except ConversationInUseError:
        raise HTTPException(
            status_code=409, detail="Conversation has an active analysis."
        ) from None
    if not removed:
        raise HTTPException(status_code=404, detail="Conversation not found.")
