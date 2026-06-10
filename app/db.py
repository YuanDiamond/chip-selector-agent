from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    default_path = Path(__file__).resolve().parents[1] / "data" / "chip_selector.sqlite3"
    default_path.parent.mkdir(parents=True, exist_ok=True)
    return os.getenv("DATABASE_URL", f"sqlite:///{default_path.as_posix()}")


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, default="board")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class ProjectContextRow(Base):
    __tablename__ = "project_contexts"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    open_requirements: Mapped[list] = mapped_column(JSON, default=list)


class ContextEventRow(Base):
    __tablename__ = "context_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    sequence: Mapped[int] = mapped_column(Integer, default=0, index=True)


class SelectionPlanRow(Base):
    __tablename__ = "selection_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    requirement: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")


class PartRow(Base):
    __tablename__ = "parts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    mpn: Mapped[str] = mapped_column(String, index=True)
    manufacturer: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    package: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    quantity_total: Mapped[int] = mapped_column(Integer, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    datasheet_url: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)


class RecommendationRow(Base):
    __tablename__ = "recommendation_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")


class ReservationRow(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("parts.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="reserved")


class StockTransactionRow(Base):
    __tablename__ = "stock_transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("parts.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String)


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    part_id: Mapped[str | None] = mapped_column(ForeignKey("parts.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    part_id: Mapped[str | None] = mapped_column(ForeignKey("parts.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class SystemPlanRow(Base):
    """存储系统规划记录"""
    __tablename__ = "system_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    system_type: Mapped[str] = mapped_column(String, index=True)
    system_name: Mapped[str] = mapped_column(String, default="")
    user_raw_input: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    critical_missing_info: Mapped[list] = mapped_column(JSON, default=list)
    modules_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    voltage_rails: Mapped[dict] = mapped_column(JSON, default=dict)
    total_estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="draft")


class BOMEntryRow(Base):
    """存储 BOM 行项"""
    __tablename__ = "bom_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("system_plans.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    module_id: Mapped[str] = mapped_column(String)
    module_name: Mapped[str] = mapped_column(String)
    part_mpn: Mapped[str | None] = mapped_column(String, nullable=True)
    part_id: Mapped[str | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String, default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="pending")
    notes: Mapped[str] = mapped_column(Text, default="")


class DebugTraceRow(Base):
    __tablename__ = "debug_traces"

    trace_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_message: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    user_prompt: Mapped[str] = mapped_column(Text, default="")
    llm_output: Mapped[str] = mapped_column(Text, default="")
    internal_state: Mapped[dict] = mapped_column(JSON, default=dict)
    events: Mapped[list] = mapped_column(JSON, default=list)


class ProjectSelectedPartRow(Base):
    __tablename__ = "project_selected_parts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    part_id: Mapped[str | None] = mapped_column(String, nullable=True)
    mpn: Mapped[str] = mapped_column(String, index=True)
    category: Mapped[str] = mapped_column(String, default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String, default="")
    user_modified: Mapped[int] = mapped_column(Integer, default=0)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if _database_url().startswith("sqlite"):
        with engine.begin() as conn:
            columns = [row[1] for row in conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()]
            if "sequence" not in columns:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN sequence INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE chat_messages SET sequence = rowid WHERE sequence IS NULL OR sequence = 0"))


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
