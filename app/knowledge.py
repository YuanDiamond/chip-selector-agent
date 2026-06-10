from __future__ import annotations

import math
import re
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from .llm import llm_client
from .models import InventoryPart, KnowledgeChunk, KnowledgeDocument
from .schemas import PART_SCHEMAS
from .store import store

PENDING_IMPORTS: dict[str, dict] = {}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _chunk_text(text: str, *, size: int = 1100, overlap: int = 160) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += max(1, size - overlap)
    return chunks


def _safe_part_id(mpn: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", mpn.strip())[:48].strip("-").lower()
    return f"ds-{clean or uuid4().hex[:8]}"


def _normalize_parameters(parameters: object) -> dict:
    return parameters if isinstance(parameters, dict) else {}


def _part_from_edit(data: dict, fallback: InventoryPart | None = None) -> InventoryPart:
    mpn = (data.get("mpn") or (fallback.mpn if fallback else "") or "UNKNOWN").strip()
    return InventoryPart(
        id=data.get("id") or (fallback.id if fallback else _safe_part_id(mpn)),
        mpn=mpn,
        manufacturer=data.get("manufacturer") if data.get("manufacturer") is not None else (fallback.manufacturer if fallback else ""),
        category=(data.get("category") or (fallback.category if fallback else "unknown")).lower(),
        description=data.get("description") if data.get("description") is not None else (fallback.description if fallback else ""),
        package=data.get("package") if data.get("package") is not None else (fallback.package if fallback else ""),
        location=data.get("location") if data.get("location") is not None else (fallback.location if fallback else "待入库"),
        quantity_total=0,
        quantity_reserved=0,
        unit_price=float(data.get("unit_price") or (fallback.unit_price if fallback else 0) or 0),
        datasheet_url=data.get("datasheet_url") if data.get("datasheet_url") is not None else (fallback.datasheet_url if fallback else ""),
        parameters=_normalize_parameters(data.get("parameters") if "parameters" in data else (fallback.parameters if fallback else {})),
    )


def _extract_part(filename: str, chunks: list[KnowledgeChunk]) -> tuple[InventoryPart | None, list[str]]:
    warnings: list[str] = []
    text = "\n".join(chunk.text for chunk in chunks[:6])[:7000]
    if llm_client.available and text:
        system = (
            "你是电子器件数据手册解析器，只输出 JSON。"
            "字段：mpn, manufacturer, category, description, package, parameters。"
            f"category 必须从 {list(PART_SCHEMAS.keys())} 中选择，无法判断则为 null。"
            "parameters 按器件类别抽取关键数值，数值尽量用数字，不要带单位字符串。"
        )
        try:
            parsed = llm_client.json_complete(system, f"文件名：{filename}\n\n数据手册文本：\n{text}")
            mpn = parsed.get("mpn") or Path(filename).stem
            part = InventoryPart(
                id=_safe_part_id(mpn),
                mpn=mpn,
                manufacturer=parsed.get("manufacturer") or "",
                category=(parsed.get("category") or "unknown").lower(),
                description=parsed.get("description") or f"Imported from datasheet {filename}",
                package=parsed.get("package") or "",
                location="待入库",
                quantity_total=0,
                unit_price=0,
                datasheet_url="",
                parameters=_normalize_parameters(parsed.get("parameters")),
            )
            if part.category not in PART_SCHEMAS:
                warnings.append("未能可靠识别器件类别，请手动确认 category。")
            return part, warnings
        except Exception as exc:
            warnings.append(f"LLM 解析失败，已使用文件名兜底：{exc}")

    stem = Path(filename).stem
    match = re.search(r"[A-Z]{2,}[A-Z0-9_.-]{3,}", stem.upper())
    if not match:
        warnings.append("未从文件名中识别出可靠型号，请手动填写。")
        return None, warnings
    mpn = match.group(0)
    warnings.append("未调用或未完成 LLM 解析，仅从文件名推断型号。")
    return InventoryPart(id=_safe_part_id(mpn), mpn=mpn, manufacturer="", category="unknown", description=f"Imported from datasheet {filename}", package="", location="待入库", quantity_total=0, parameters={}), warnings


def preview_pdf(path: Path, *, filename: str, part_id: str | None = None, project_id: str | None = None) -> dict:
    reader = PdfReader(str(path))
    document_id = f"doc-{uuid4().hex[:8]}"
    chunks: list[KnowledgeChunk] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = _clean_text(page.extract_text() or "")
        for chunk in _chunk_text(text):
            chunks.append(KnowledgeChunk(id=f"k-{uuid4().hex[:10]}", document_id=document_id, part_id=part_id, project_id=project_id, title=filename, page=page_index, text=chunk))

    created_part = None
    warnings: list[str] = []
    if not part_id:
        created_part, warnings = _extract_part(filename, chunks)
        if created_part:
            part_id = created_part.id
            chunks = [chunk.model_copy(update={"part_id": part_id}) for chunk in chunks]

    document = KnowledgeDocument(id=document_id, filename=filename, part_id=part_id, project_id=project_id, pages=len(reader.pages), chunks=len(chunks))
    editable_part = created_part.model_dump() if created_part else None
    token = f"imp-{uuid4().hex[:12]}"
    PENDING_IMPORTS[token] = {"document": document, "chunks": chunks, "created_part": created_part, "bound_part_id": part_id if not created_part else None}
    category = (created_part.category if created_part else None)
    return {
        "token": token,
        "document": document,
        "created_part": created_part,
        "editable_part": editable_part,
        "parameters_schema": PART_SCHEMAS.get(category or "", {}).get("parameters", []),
        "chunks_preview": [chunk.model_dump() for chunk in chunks[:3]],
        "warnings": warnings,
    }


def commit_preview(token: str, edited_part: dict | None = None, edited_document: dict | None = None) -> tuple[KnowledgeDocument, InventoryPart | None]:
    pending = PENDING_IMPORTS.pop(token, None)
    if not pending:
        raise KeyError(token)

    document: KnowledgeDocument = pending["document"]
    if edited_document:
        document = document.model_copy(update={k: v for k, v in edited_document.items() if k in {"filename", "part_id", "project_id"}})

    created_part: InventoryPart | None = pending["created_part"]
    if created_part:
        created_part = _part_from_edit(edited_part or {}, created_part)
        document = document.model_copy(update={"part_id": created_part.id})
        chunks = [chunk.model_copy(update={"part_id": created_part.id}) for chunk in pending["chunks"]]
        store.upsert_part(created_part)
    else:
        chunks = pending["chunks"]

    store.add_knowledge_document(document)
    for chunk in chunks:
        store.add_knowledge_chunk(chunk)
    return document, created_part


def ingest_pdf(path: Path, *, filename: str, part_id: str | None = None, project_id: str | None = None) -> tuple[KnowledgeDocument, InventoryPart | None]:
    preview = preview_pdf(path, filename=filename, part_id=part_id, project_id=project_id)
    return commit_preview(preview["token"])


def search_knowledge(query: str, *, project_id: str | None = None, part_ids: list[str] | None = None, limit: int = 5) -> list[KnowledgeChunk]:
    terms = [term.lower() for term in re.findall(r"[a-zA-Z0-9_.+-]+|[\u4e00-\u9fff]{2,}", query)]
    if not terms:
        return []
    chunks = []
    for chunk in store.iter_knowledge_chunks():
        if project_id and chunk.project_id and chunk.project_id != project_id:
            continue
        if part_ids and chunk.part_id and chunk.part_id not in part_ids:
            continue
        chunks.append(chunk)
    scored = []
    for chunk in chunks:
        text = chunk.text.lower()
        score = sum(text.count(term) * math.log(1 + len(chunks)) for term in terms)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]
