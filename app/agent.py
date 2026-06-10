from __future__ import annotations

import re
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from .models import Candidate, RecommendationSession, Requirement
from .store import store


class SelectorState(TypedDict, total=False):
    project_id: str
    user_message: str
    requirement: Requirement
    candidates: list[Candidate]
    summary: str


def _number_before(text: str, unit_pattern: str) -> float | None:
    match = re.search(rf"(\d+(?:\.\d+)?)\s*{unit_pattern}", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def parse_requirement(state: SelectorState) -> SelectorState:
    message = state["user_message"]
    text = message.lower()
    category = None
    if "ldo" in text or "稳压" in message:
        category = "ldo"
    elif "buck" in text or "降压" in message or "dc-dc" in text:
        category = "buck"
    elif "dac" in text or "数模" in message:
        category = "dac"
    elif "adc" in text or "模数" in message or "采样" in message:
        category = "adc"
    elif "mcu" in text or "单片机" in message or "stm32" in text:
        category = "mcu"
    voltages = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*v", text)]
    current = _number_before(text, r"a\b")
    if current is None:
        ma = _number_before(text, r"ma\b")
        current = ma / 1000 if ma is not None else None
    state["requirement"] = Requirement(
        raw_text=message,
        category=category,
        vin=voltages[0] if voltages else None,
        vout=voltages[1] if len(voltages) > 1 else None,
        current=current,
        resolution_bits=int(_number_before(text, r"(?:bit|位)") or 0) or None,
        sample_rate_ksps=_number_before(text, r"(?:ksps|k\s*sps)"),
        channels=int(_number_before(text, r"(?:通道|ch)") or 0) or None,
        interface=next((item for item in ["i2c", "spi", "uart", "usb", "can"] if item in text), None),
        quantity=int(_number_before(message, r"(?:个|颗|pcs)") or 1),
        priorities=["lab_inventory"],
    )
    return state


def search_inventory(state: SelectorState) -> SelectorState:
    req = state["requirement"]
    candidates: list[Candidate] = []
    for part in store.iter_parts():
        if req.category and part.category != req.category:
            continue
        if part.quantity_available <= 0:
            continue
        score = 60.0
        reasons = ["实验室库存可用"]
        params = part.parameters or {}
        if req.resolution_bits and params.get("resolution_bits", 0) >= req.resolution_bits:
            score += 10
            reasons.append("分辨率满足")
        if req.channels and params.get("channels", 0) >= req.channels:
            score += 10
            reasons.append("通道数满足")
        if req.interface and str(params.get("interface", "")).lower() == req.interface:
            score += 10
            reasons.append("接口匹配")
        candidates.append(Candidate(source="lab", part=part, score=min(score, 100), reasons=reasons))
    candidates.sort(key=lambda item: item.score, reverse=True)
    state["candidates"] = candidates[:5]
    return state


def summarize(state: SelectorState) -> SelectorState:
    candidates = state.get("candidates", [])
    if candidates:
        top = candidates[0]
        state["summary"] = f"首选 {top.part.mpn}，因为 {'、'.join(top.reasons)}。"
    else:
        state["summary"] = "当前库存没有稳定匹配项，需要补充参数或新增器件知识。"
    return state


workflow = StateGraph(SelectorState)
workflow.add_node("parse_requirement", parse_requirement)
workflow.add_node("search_inventory", search_inventory)
workflow.add_node("summarize", summarize)
workflow.set_entry_point("parse_requirement")
workflow.add_edge("parse_requirement", "search_inventory")
workflow.add_edge("search_inventory", "summarize")
workflow.add_edge("summarize", END)
graph = workflow.compile()


def run_agent(project_id: str, message: str) -> RecommendationSession:
    result = graph.invoke({"project_id": project_id, "user_message": message})
    return RecommendationSession(
        id=f"rec-{uuid4().hex[:10]}",
        project_id=project_id,
        requirement=result["requirement"],
        candidates=result.get("candidates", []),
        summary=result.get("summary", ""),
    )
