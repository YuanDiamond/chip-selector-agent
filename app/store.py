from __future__ import annotations

from typing import Any
from uuid import uuid4

from .db import (
    ChatMessageRow, ContextEventRow, DebugTraceRow, KnowledgeChunkRow,
    KnowledgeDocumentRow, PartRow, ProjectContextRow, ProjectRow,
    ProjectSelectedPartRow, RecommendationRow, ReservationRow,
    SelectionPlanRow, StockTransactionRow, init_db, session_scope,
)
from .models import (
    InventoryPart, KnowledgeChunk, KnowledgeDocument, Project,
    RecommendationSession, Reservation, StockTransaction,
)


class DatabaseStore:
    def __init__(self) -> None:
        init_db()
        self.seed()

    def seed(self) -> None:
        with session_scope() as session:
            project = session.get(ProjectRow, "p-demo")
            if not project:
                session.add(ProjectRow(
                    id="p-demo",
                    name="采集板原型",
                    category="mixed-signal",
                    description="低噪声传感器采集与 MCU 控制原型板",
                    tags=["ADC", "LDO", "MCU"],
                ))
                session.add(ProjectContextRow(
                    project_id="p-demo",
                    summary="采集板原型，优先使用实验室库存。",
                    preferences={"stock_policy": "lab_inventory_first"},
                    open_requirements=[],
                ))
            else:
                project.name = "采集板原型"
                project.category = "mixed-signal"
                project.description = "低噪声传感器采集与 MCU 控制原型板"
                project.tags = ["ADC", "LDO", "MCU"]
            for part in self._seed_parts():
                if not session.get(PartRow, part.id):
                    session.add(PartRow(**part.model_dump()))

    def _seed_parts(self) -> list[InventoryPart]:
        return [
            InventoryPart(id="lab-ldo-1", mpn="TPS7A2033PDBVR", manufacturer="Texas Instruments", category="ldo", description="Low-noise 300 mA LDO, fixed 3.3 V", package="SOT-23-5", location="A3-02", quantity_total=12, unit_price=0.62, datasheet_url="https://www.ti.com/product/TPS7A20", parameters={"vin_min": 1.6, "vin_max": 6.0, "vout": 3.3, "iout_max": 0.3, "noise_uvrms": 7}),
            InventoryPart(id="lab-ldo-2", mpn="MIC5504-3.3YM5", manufacturer="Microchip", category="ldo", description="300 mA LDO, fixed 3.3 V", package="SOT-23-5", location="A3-04", quantity_total=20, unit_price=0.35, datasheet_url="https://www.microchip.com/", parameters={"vin_min": 2.5, "vin_max": 5.5, "vout": 3.3, "iout_max": 0.3, "noise_uvrms": 60}),
            InventoryPart(id="lab-buck-1", mpn="MP1584EN", manufacturer="Monolithic Power Systems", category="buck", description="3 A step-down regulator", package="SOIC-8E", location="B1-01", quantity_total=8, unit_price=0.48, datasheet_url="https://www.monolithicpower.com/", parameters={"vin_min": 4.5, "vin_max": 28, "vout_min": 0.8, "vout_max": 25, "iout_max": 3.0}),
            InventoryPart(id="lab-mcu-1", mpn="STM32F103C8T6", manufacturer="STMicroelectronics", category="mcu", description="Arm Cortex-M3 MCU, 64 KB Flash", package="LQFP-48", location="C2-01", quantity_total=16, unit_price=1.8, datasheet_url="https://www.st.com/", parameters={"flash_kb": 64, "ram_kb": 20, "gpio": 37, "interfaces": ["i2c", "spi", "uart"], "vin_min": 2.0, "vin_max": 3.6, "core": "Cortex-M3"}),
            InventoryPart(id="lab-adc-1", mpn="ADS1115IDGSR", manufacturer="Texas Instruments", category="adc", description="16-bit, 860 SPS, 4-channel I2C ADC", package="VSSOP-10", location="D1-03", quantity_total=10, unit_price=2.1, datasheet_url="https://www.ti.com/product/ADS1115", parameters={"resolution_bits": 16, "sample_rate_ksps": 0.86, "channels": 4, "interface": "i2c", "vin_min": 2.0, "vin_max": 5.5}),
            InventoryPart(id="lab-adc-2", mpn="MCP3208-CI/SL", manufacturer="Microchip", category="adc", description="12-bit, 100 kSPS, 8-channel SPI ADC", package="SOIC-16", location="D1-05", quantity_total=6, unit_price=2.4, datasheet_url="https://www.microchip.com/", parameters={"resolution_bits": 12, "sample_rate_ksps": 100, "channels": 8, "interface": "spi", "vin_min": 2.7, "vin_max": 5.5}),
            InventoryPart(id="lab-dac-1", mpn="MCP4725A0T-E/CH", manufacturer="Microchip", category="dac", description="12-bit single-channel I2C voltage-output DAC", package="SOT-23-6", location="D2-02", quantity_total=9, unit_price=1.2, datasheet_url="https://www.microchip.com/", parameters={"resolution_bits": 12, "update_rate_ksps": 3.4, "channels": 1, "interface": "i2c", "vin_min": 2.7, "vin_max": 5.5, "output_type": "voltage"}),
            InventoryPart(id="lab-dac-2", mpn="MCP4922-E/SL", manufacturer="Microchip", category="dac", description="12-bit, 2-channel SPI voltage-output DAC", package="SOIC-14", location="D2-05", quantity_total=7, unit_price=2.8, datasheet_url="https://www.microchip.com/", parameters={"resolution_bits": 12, "update_rate_ksps": 4500, "channels": 2, "interface": "spi", "vin_min": 2.7, "vin_max": 5.5, "output_type": "voltage"}),
        ]

    def _project_from_row(self, row: ProjectRow) -> Project:
        return Project(id=row.id, name=row.name, category=row.category, description=row.description, tags=row.tags or [])

    def _part_from_row(self, row: PartRow) -> InventoryPart:
        return InventoryPart(id=row.id, mpn=row.mpn, manufacturer=row.manufacturer, category=row.category, description=row.description, package=row.package, location=row.location, quantity_total=row.quantity_total, quantity_reserved=row.quantity_reserved, unit_price=row.unit_price, datasheet_url=row.datasheet_url, parameters=row.parameters or {})

    def project_exists(self, project_id: str) -> bool:
        with session_scope() as session:
            return session.get(ProjectRow, project_id) is not None

    def list_projects_with_context(self) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = session.query(ProjectRow).order_by(ProjectRow.name).all()
            result = []
            for row in rows:
                context = session.get(ProjectContextRow, row.id)
                result.append(self._project_from_row(row).model_dump() | {"context": context.summary if context else ""})
            return result

    def create_project(self, name: str, category: str = "board", description: str = "") -> Project:
        project = Project(id=f"p-{uuid4().hex[:8]}", name=name, category=category, description=description)
        with session_scope() as session:
            session.add(ProjectRow(**project.model_dump()))
            session.add(ProjectContextRow(project_id=project.id, summary=description, preferences={}, open_requirements=[]))
        return project

    def delete_project(self, project_id: str) -> None:
        with session_scope() as session:
            project = session.get(ProjectRow, project_id)
            if not project:
                raise KeyError(project_id)
            for model in [ChatMessageRow, ContextEventRow, SelectionPlanRow, RecommendationRow, ReservationRow, StockTransactionRow, ProjectContextRow, ProjectSelectedPartRow, DebugTraceRow]:
                session.query(model).filter(getattr(model, "project_id") == project_id).delete(synchronize_session=False)
            session.query(KnowledgeChunkRow).filter(KnowledgeChunkRow.project_id == project_id).delete(synchronize_session=False)
            session.query(KnowledgeDocumentRow).filter(KnowledgeDocumentRow.project_id == project_id).delete(synchronize_session=False)
            session.delete(project)

    def iter_parts(self) -> list[InventoryPart]:
        with session_scope() as session:
            return [self._part_from_row(row) for row in session.query(PartRow).order_by(PartRow.category, PartRow.mpn).all()]

    def get_part(self, part_id: str) -> InventoryPart:
        with session_scope() as session:
            row = session.get(PartRow, part_id)
            if not row:
                raise KeyError(part_id)
            return self._part_from_row(row)

    def part_view(self, part: InventoryPart) -> dict[str, Any]:
        data = part.model_dump()
        data["quantity_available"] = part.quantity_available
        return data

    def list_parts(self) -> list[dict[str, Any]]:
        return [self.part_view(part) for part in self.iter_parts()]

    def add_chat_message(self, project_id: str, role: str, content: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with session_scope() as session:
            last = session.query(ChatMessageRow).filter(ChatMessageRow.project_id == project_id).order_by(ChatMessageRow.sequence.desc()).first()
            row = ChatMessageRow(id=f"msg-{uuid4().hex[:10]}", project_id=project_id, role=role, content=content, payload=payload or {}, sequence=(last.sequence + 1 if last else 1))
            session.add(row)
            return {"id": row.id, "project_id": project_id, "role": role, "content": content, "payload": payload or {}, "sequence": row.sequence}

    def list_chat_messages(self, project_id: str, limit: int = 80) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = session.query(ChatMessageRow).filter(ChatMessageRow.project_id == project_id).order_by(ChatMessageRow.sequence.asc(), ChatMessageRow.id.asc()).limit(limit).all()
            return [{"id": row.id, "project_id": row.project_id, "role": row.role, "content": row.content, "payload": row.payload or {}, "sequence": row.sequence} for row in rows]

    def save_recommendation(self, session_model: RecommendationSession) -> None:
        with session_scope() as session:
            session.add(RecommendationRow(id=session_model.id, project_id=session_model.project_id, requirement=session_model.requirement.model_dump(), candidates=[candidate.model_dump() for candidate in session_model.candidates], summary=session_model.summary))

    def update_project_context(self, project_id: str, user_message: str, summary: str) -> None:
        with session_scope() as session:
            context = session.get(ProjectContextRow, project_id)
            new_summary = f"最近输入：{user_message}\n当前结论：{summary}"
            if context:
                context.summary = new_summary
            else:
                session.add(ProjectContextRow(project_id=project_id, summary=new_summary, preferences={}, open_requirements=[]))
            session.add(ContextEventRow(id=f"ctx-{uuid4().hex[:10]}", project_id=project_id, event_type="agent_turn", payload={"user_message": user_message, "summary": summary}))

    def upsert_selected_parts(self, project_id: str, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with session_scope() as session:
            session.query(ProjectSelectedPartRow).filter(ProjectSelectedPartRow.project_id == project_id).delete(synchronize_session=False)
            output = []
            for item in parts:
                row = ProjectSelectedPartRow(
                    id=item.get("id") or f"selpart-{uuid4().hex[:10]}",
                    project_id=project_id,
                    part_id=item.get("part_id"),
                    mpn=item.get("mpn") or item.get("label") or "",
                    category=item.get("category") or "",
                    quantity=max(0, int(item.get("quantity") or 0)),
                    source=item.get("source") or "",
                    user_modified=1 if item.get("user_modified", True) else 0,
                )
                session.add(row)
                output.append(self._selected_part_row(row))
            return output

    def list_selected_parts(self, project_id: str) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = session.query(ProjectSelectedPartRow).filter(ProjectSelectedPartRow.project_id == project_id).order_by(ProjectSelectedPartRow.id.asc()).all()
            return [self._selected_part_row(row) for row in rows]

    def _selected_part_row(self, row: ProjectSelectedPartRow) -> dict[str, Any]:
        return {"id": row.id, "project_id": row.project_id, "part_id": row.part_id, "mpn": row.mpn, "category": row.category, "quantity": row.quantity, "source": row.source, "user_modified": bool(row.user_modified)}

    def save_debug_trace(self, trace: dict[str, Any]) -> None:
        with session_scope() as session:
            existing = session.get(DebugTraceRow, trace["trace_id"])
            data = {"project_id": trace.get("project_id", ""), "user_message": trace.get("user_message", ""), "system_prompt": trace.get("system_prompt", ""), "user_prompt": trace.get("user_prompt", ""), "llm_output": trace.get("llm_output", ""), "internal_state": trace.get("internal_state", {}), "events": trace.get("events", [])}
            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
            else:
                session.add(DebugTraceRow(trace_id=trace["trace_id"], **data))

    def get_debug_trace(self, trace_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.get(DebugTraceRow, trace_id)
            if not row:
                return None
            return {"trace_id": row.trace_id, "project_id": row.project_id, "user_message": row.user_message, "system_prompt": row.system_prompt, "user_prompt": row.user_prompt, "llm_output": row.llm_output, "internal_state": row.internal_state or {}, "events": row.events or []}

    def save_selection_plan(self, project_id: str, requirement: dict[str, Any], summary: str, status: str = "confirmed") -> dict[str, Any]:
        row = SelectionPlanRow(id=f"sel-{uuid4().hex[:10]}", project_id=project_id, status=status, requirement=requirement, summary=summary)
        with session_scope() as session:
            session.add(row)
        return {"id": row.id, "project_id": project_id, "status": status, "requirement": requirement, "summary": summary}

    def reserve(self, project_id: str, part_id: str, quantity: int) -> Reservation:
        with session_scope() as session:
            part = session.get(PartRow, part_id)
            if not part or not session.get(ProjectRow, project_id):
                raise KeyError(part_id)
            if quantity < 1:
                raise ValueError("Reservation quantity must be positive.")
            if max(0, part.quantity_total - part.quantity_reserved) < quantity:
                raise ValueError("Not enough available inventory.")
            part.quantity_reserved += quantity
            row = ReservationRow(id=f"r-{uuid4().hex[:8]}", project_id=project_id, part_id=part_id, quantity=quantity, status="reserved")
            session.add(row)
            return Reservation(id=row.id, project_id=row.project_id, part_id=row.part_id, quantity=row.quantity, status="reserved")

    def confirm(self, reservation_id: str) -> StockTransaction:
        with session_scope() as session:
            reservation = session.get(ReservationRow, reservation_id)
            if not reservation:
                raise KeyError(reservation_id)
            if reservation.status != "reserved":
                raise ValueError("Reservation is not active.")
            part = session.get(PartRow, reservation.part_id)
            if not part:
                raise KeyError(reservation.part_id)
            part.quantity_reserved -= reservation.quantity
            part.quantity_total -= reservation.quantity
            reservation.status = "confirmed"
            row = StockTransactionRow(id=f"t-{uuid4().hex[:8]}", reservation_id=reservation.id, project_id=reservation.project_id, part_id=reservation.part_id, quantity=reservation.quantity, action="consume")
            session.add(row)
            return StockTransaction(id=row.id, reservation_id=row.reservation_id, project_id=row.project_id, part_id=row.part_id, quantity=row.quantity, action="consume")

    def cancel(self, reservation_id: str) -> Reservation:
        with session_scope() as session:
            reservation = session.get(ReservationRow, reservation_id)
            if not reservation:
                raise KeyError(reservation_id)
            if reservation.status != "reserved":
                raise ValueError("Reservation is not active.")
            part = session.get(PartRow, reservation.part_id)
            if part:
                part.quantity_reserved -= reservation.quantity
            reservation.status = "cancelled"
            return Reservation(id=reservation.id, project_id=reservation.project_id, part_id=reservation.part_id, quantity=reservation.quantity, status="cancelled")

    def list_reservations(self) -> list[Reservation]:
        with session_scope() as session:
            rows = session.query(ReservationRow).order_by(ReservationRow.id.desc()).all()
            return [Reservation(id=row.id, project_id=row.project_id, part_id=row.part_id, quantity=row.quantity, status=row.status) for row in rows]

    def adjust_stock(self, part_id: str, quantity_total: int | None = None, delta: int | None = None, location: str | None = None) -> InventoryPart:
        with session_scope() as session:
            part = session.get(PartRow, part_id)
            if not part:
                raise KeyError(part_id)
            if quantity_total is not None:
                part.quantity_total = max(0, quantity_total)
            if delta is not None:
                part.quantity_total = max(0, part.quantity_total + delta)
            if location is not None:
                part.location = location
            return self._part_from_row(part)

    def add_knowledge_document(self, document: KnowledgeDocument) -> None:
        with session_scope() as session:
            session.add(KnowledgeDocumentRow(**document.model_dump()))

    def add_knowledge_chunk(self, chunk: KnowledgeChunk) -> None:
        with session_scope() as session:
            session.add(KnowledgeChunkRow(**chunk.model_dump()))

    def list_knowledge_documents(self) -> list[KnowledgeDocument]:
        with session_scope() as session:
            rows = session.query(KnowledgeDocumentRow).order_by(KnowledgeDocumentRow.filename).all()
            return [KnowledgeDocument(id=row.id, filename=row.filename, part_id=row.part_id, project_id=row.project_id, pages=row.pages, chunks=row.chunks) for row in rows]

    def iter_knowledge_chunks(self) -> list[KnowledgeChunk]:
        with session_scope() as session:
            rows = session.query(KnowledgeChunkRow).all()
            return [KnowledgeChunk(id=row.id, document_id=row.document_id, part_id=row.part_id, project_id=row.project_id, title=row.title, page=row.page, text=row.text) for row in rows]

    def upsert_part(self, part: InventoryPart) -> InventoryPart:
        with session_scope() as session:
            existing = session.get(PartRow, part.id)
            if existing:
                for key, value in part.model_dump().items():
                    setattr(existing, key, value)
            else:
                session.add(PartRow(**part.model_dump()))
        return part


store = DatabaseStore()
