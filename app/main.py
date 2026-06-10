from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .dialog_agent import build_recommendation_session, confirm_selection, discuss_selection, prepare_discussion_reply
from .event_bus import event_bus
from .knowledge import commit_preview, preview_pdf, search_knowledge
from .llm import llm_client
from .store import store


class ChatRequest(BaseModel):
    project_id: str
    message: str


class ProjectCreateRequest(BaseModel):
    name: str
    category: str = "board"
    description: str = ""


class AcceptRequest(BaseModel):
    project_id: str
    part_id: str
    quantity: int = 1


class SelectionConfirmRequest(BaseModel):
    project_id: str
    requirement: dict[str, Any] = {}
    summary: str = ""
    parts: list[dict[str, Any]] = []
    trace_id: str | None = None


class SelectedPartsRequest(BaseModel):
    parts: list[dict[str, Any]]
    trace_id: str | None = None


class StockAdjustRequest(BaseModel):
    quantity_total: int | None = None
    delta: int | None = None
    location: str | None = None


class KnowledgeCommitRequest(BaseModel):
    token: str
    edited_part: dict[str, Any] | None = None
    edited_document: dict[str, Any] | None = None


app = FastAPI(title="Chip Selector Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    return {"projects": store.list_projects_with_context()}


@app.post("/api/projects")
def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
    project = store.create_project(payload.name, payload.category, payload.description)
    return {"project": project.model_dump()}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    try:
        store.delete_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    event_bus.publish(project_id, f"delete-{uuid4().hex[:8]}", "db_write", {"deleted_project": project_id})
    return {"ok": True}


@app.get("/api/inventory")
def list_inventory() -> dict[str, Any]:
    return {"parts": store.list_parts()}


@app.patch("/api/inventory/{part_id}/stock")
def adjust_inventory_stock(part_id: str, payload: StockAdjustRequest) -> dict[str, Any]:
    try:
        part = store.adjust_stock(part_id, quantity_total=payload.quantity_total, delta=payload.delta, location=payload.location)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Part not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"part": store.part_view(part), "inventory": store.list_parts()}


@app.get("/api/projects/{project_id}/selected-parts")
def get_selected_parts(project_id: str) -> dict[str, Any]:
    if not store.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"parts": store.list_selected_parts(project_id)}


@app.patch("/api/projects/{project_id}/selected-parts")
def patch_selected_parts(project_id: str, payload: SelectedPartsRequest) -> dict[str, Any]:
    if not store.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    parts = store.upsert_selected_parts(project_id, payload.parts)
    trace_id = payload.trace_id or f"manual-{uuid4().hex[:10]}"
    event_bus.publish(project_id, trace_id, "manual_parts_update", {"parts": parts})
    event_bus.publish(project_id, trace_id, "db_write", {"selected_parts": len(parts)})
    return {"parts": parts, "trace_id": trace_id}


@app.get("/api/system/model")
def model_status() -> dict[str, Any]:
    return {"available": llm_client.available, "model": llm_client.model, "base_url": llm_client.base_url}


@app.get("/api/system/model/check")
def model_check() -> dict[str, Any]:
    if not llm_client.available:
        raise HTTPException(status_code=400, detail="LLM key is not configured.")
    try:
        return {"ok": True, "reply": llm_client.health_check()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/agent/messages")
def agent_messages(project_id: str) -> dict[str, Any]:
    if not store.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"messages": store.list_chat_messages(project_id)}


@app.post("/api/agent/discuss")
def agent_discuss(payload: ChatRequest) -> dict[str, Any]:
    if not store.project_exists(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return discuss_selection(payload.project_id, payload.message)


@app.post("/api/agent/discuss/stream")
def agent_discuss_stream(payload: ChatRequest) -> StreamingResponse:
    if not store.project_exists(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    trace_id = f"trace-{uuid4().hex[:10]}"

    def generate():
        result = prepare_discussion_reply(payload.project_id, payload.message, trace_id)
        text = result["reply"]
        for index in range(0, len(text), 10):
            chunk = text[index:index + 10]
            event_bus.publish(payload.project_id, trace_id, "llm_delta", {"text": chunk})
            yield json.dumps({"type": "delta", "trace_id": trace_id, "text": chunk}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "meta", "trace_id": trace_id, "payload": result["payload"]}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson; charset=utf-8")


@app.post("/api/agent/selection/confirm")
def agent_selection_confirm(payload: SelectionConfirmRequest) -> dict[str, Any]:
    if not store.project_exists(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return confirm_selection(payload.project_id, payload.requirement, payload.summary, payload.parts, payload.trace_id)


@app.post("/api/agent/chat")
def agent_chat(payload: ChatRequest) -> dict[str, Any]:
    if not store.project_exists(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    session = build_recommendation_session(payload.project_id, {"raw_text": payload.message})
    store.save_recommendation(session)
    return session.model_dump()


@app.get("/api/debug/events")
def debug_events(project_id: str | None = None) -> StreamingResponse:
    return StreamingResponse(event_bus.subscribe(project_id), media_type="text/event-stream; charset=utf-8")


@app.get("/api/debug/traces/{trace_id}")
def get_debug_trace(trace_id: str) -> dict[str, Any]:
    trace = store.get_debug_trace(trace_id) or event_bus.trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"trace": trace}


@app.post("/api/knowledge/preview")
async def preview_knowledge(file: UploadFile = File(...), part_id: str | None = Form(default=None), project_id: str | None = Form(default=None)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF datasheets are supported.")
    with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        preview = preview_pdf(tmp_path, filename=file.filename, part_id=part_id or None, project_id=project_id or None)
    finally:
        tmp_path.unlink(missing_ok=True)
    created_part = preview["created_part"]
    return {
        "token": preview["token"],
        "document": preview["document"].model_dump(),
        "created_part": store.part_view(created_part) if created_part else None,
        "editable_part": preview.get("editable_part"),
        "parameters_schema": preview.get("parameters_schema", []),
        "chunks_preview": preview.get("chunks_preview", []),
        "warnings": preview.get("warnings", []),
        "status": "preview_ready",
    }


@app.post("/api/knowledge/commit")
def commit_knowledge(payload: KnowledgeCommitRequest) -> dict[str, Any]:
    try:
        document, created_part = commit_preview(payload.token, edited_part=payload.edited_part, edited_document=payload.edited_document)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Pending import not found or already committed.") from exc
    return {"document": document.model_dump(), "created_part": store.part_view(created_part) if created_part else None, "status": "committed"}


@app.get("/api/knowledge/search")
def knowledge_search(q: str, project_id: str | None = None) -> dict[str, Any]:
    chunks = search_knowledge(q, project_id=project_id, limit=8)
    return {"chunks": [chunk.model_dump() for chunk in chunks]}


@app.get("/api/knowledge/documents")
def list_knowledge_documents() -> dict[str, Any]:
    return {"documents": [document.model_dump() for document in store.list_knowledge_documents()]}


@app.post("/api/reservations")
def create_reservation(payload: AcceptRequest) -> dict[str, Any]:
    try:
        reservation = store.reserve(payload.project_id, payload.part_id, payload.quantity)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Part or project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reservation": reservation.model_dump(), "inventory": store.list_parts()}


@app.post("/api/reservations/{reservation_id}/confirm")
def confirm_reservation(reservation_id: str) -> dict[str, Any]:
    try:
        transaction = store.confirm(reservation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Reservation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"transaction": transaction.model_dump(), "inventory": store.list_parts()}


@app.post("/api/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    try:
        reservation = store.cancel(reservation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Reservation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"reservation": reservation.model_dump(), "inventory": store.list_parts()}


@app.get("/api/reservations")
def list_reservations() -> dict[str, Any]:
    return {"reservations": [reservation.model_dump() for reservation in store.list_reservations()]}
