from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from .event_bus import event_bus
from .llm import llm_client
from .models import Candidate, InventoryPart, RecommendationSession, Requirement
from .prompts import AGENT_STATE_PROMPT, ENGINEER_SYSTEM_PROMPT, REQUIREMENT_PARSE_PROMPT
from .schemas import missing_fields, schema_guidance
from .store import store


def _number_before(text: str, unit_pattern: str) -> float | None:
    match = re.search(rf"(\d+(?:\.\d+)?)\s*{unit_pattern}", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def _to_int(value: Any) -> int | None:
    value = _to_float(value)
    return int(value) if value is not None else None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_high_speed_intent(message: str, req: dict[str, Any]) -> bool:
    text = message.lower()
    return any(word in message for word in ["高速", "高采样", "高带宽", "快"]) or any(word in text for word in ["high speed", "fast"])


def _param_number(params: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _to_float(params.get(key))
        if value is not None:
            return value
    return None


def _converter_rate_ksps(params: dict[str, Any], category: str) -> float | None:
    direct = _param_number(params, "sample_rate_ksps", "update_rate_ksps", "sampling_rate_ksps")
    if direct is not None:
        return direct
    settling_us = _param_number(params, "settling_time_us")
    if settling_us is None:
        settling_us = _param_number(params, "settling_time")
    if category == "dac" and settling_us and settling_us > 0:
        return 1000.0 / settling_us
    return None


def _interface_text(params: dict[str, Any]) -> str:
    values = [str(params.get("interface") or "")]
    if params.get("max_spi_clock_mhz") is not None:
        values.append("spi")
    if params.get("i2c_address") is not None:
        values.append("i2c")
    return " ".join(values).lower()


def _rule_parse_requirement(message: str) -> Requirement:
    text = message.lower()
    category = None
    if "ldo" in text or "稳压" in message or "低噪声" in message:
        category = "ldo"
    elif "buck" in text or "dc-dc" in text or "dcdc" in text or "降压" in message:
        category = "buck"
    elif "dac" in text or "数模" in message or "信号源" in message:
        category = "dac"
    elif "adc" in text or "模数" in message or "采样" in message:
        category = "adc"
    elif "mcu" in text or "单片机" in message or "微控制器" in message or "stm32" in text:
        category = "mcu"

    voltages = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*v", text, re.IGNORECASE)]
    current = _number_before(text, r"a\b")
    if current is None:
        ma = _number_before(text, r"ma\b")
        current = ma / 1000 if ma is not None else None
    return Requirement(
        raw_text=message,
        category=category,
        vin=voltages[0] if voltages else None,
        vout=voltages[1] if len(voltages) > 1 else None,
        current=current,
        resolution_bits=_to_int(_number_before(text, r"(?:bit|位)")),
        sample_rate_ksps=_number_before(text, r"(?:ksps|k\s*sps)"),
        channels=_to_int(_number_before(text, r"(?:通道|ch)")),
        interface=next((item for item in ["i2c", "spi", "uart", "usb", "can"] if item in text), None),
        quantity=max(1, int(_number_before(message, r"(?:个|颗|pcs)") or 1)),
        priorities=["lab_inventory"] if ("库存" in message or "现有" in message) else [],
    )


def _history_summary(history: list[dict[str, Any]], limit: int = 8) -> str:
    if not history:
        return "暂无历史。"
    lines = []
    for item in history[-limit:]:
        content = str(item.get("content", "")).replace("\n", " ")
        lines.append(f"{item.get('role')}: {content[:160]}")
    return "\n".join(lines)


def _inventory_brief(limit: int = 32) -> list[dict[str, Any]]:
    return [{
        "part_id": part.id,
        "mpn": part.mpn,
        "category": part.category,
        "package": part.package,
        "available": part.quantity_available,
        "location": part.location,
        "parameters": part.parameters,
    } for part in store.iter_parts()[:limit]]


def _format_inventory(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        params = ", ".join(f"{k}={v}" for k, v in list((item.get("parameters") or {}).items())[:6])
        lines.append(f"{item['mpn']} | {item['category']} | 可用 {item['available']} | {item['package']} | {params}")
    return "\n".join(lines)


def _selected_text(selected: list[dict[str, Any]]) -> str:
    if not selected:
        return "暂无已采用器件。"
    return "\n".join(f"{item['mpn']} | {item['category']} | 数量 {item['quantity']} | {item.get('source') or 'user'}" for item in selected)


def _inventory_by_mpn(inventory: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["mpn"].upper(): item for item in inventory}


def _mentioned_mpns(message: str, inventory: list[dict[str, Any]]) -> list[str]:
    known = _inventory_by_mpn(inventory)
    tokens = [token.upper() for token in re.findall(r"[A-Z]{2,}[A-Z0-9/_.-]{2,}", message, re.IGNORECASE)]
    result = []
    for token in tokens:
        if token in known and token not in result:
            result.append(token)
    return result


def _adoption_intent(message: str) -> bool:
    return any(word in message for word in ["就用", "采用", "选用", "确定用", "用这个", "先用", "定为", "已采用"])


def _infer_named_category(mpn: str, message: str, part: dict[str, Any] | None) -> str:
    category = (part or {}).get("category") or ""
    if category and category != "unknown":
        return category
    text = f"{mpn} {message}".lower()
    if "dac" in text:
        return "dac"
    if "adc" in text:
        return "adc"
    if "mcu" in text or "stm32" in text:
        return "mcu"
    if "ldo" in text:
        return "ldo"
    if "buck" in text:
        return "buck"
    return category or "unknown"


def _manual_selected_updates(message: str, inventory: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _adoption_intent(message):
        return existing
    by_mpn = _inventory_by_mpn(inventory)
    selected_by_mpn = {item["mpn"].upper(): dict(item) for item in existing}
    for mpn_upper in _mentioned_mpns(message, inventory):
        part = by_mpn[mpn_upper]
        category = _infer_named_category(part["mpn"], message, part)
        selected_by_mpn[mpn_upper] = {
            "id": selected_by_mpn.get(mpn_upper, {}).get("id") or f"sel-{part.get('part_id') or part['mpn']}",
            "project_id": selected_by_mpn.get(mpn_upper, {}).get("project_id"),
            "part_id": part.get("part_id"),
            "mpn": part["mpn"],
            "category": category,
            "quantity": max(1, int(selected_by_mpn.get(mpn_upper, {}).get("quantity") or 1)),
            "source": "user_named_unverified" if part.get("category") in {"", "unknown"} or not part.get("parameters") else "user_named_inventory",
            "user_modified": True,
        }
    return list(selected_by_mpn.values())


def _unknown_mpns(text: str, inventory: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[str]:
    allowed = {item["mpn"].upper() for item in inventory} | {item["mpn"].upper() for item in selected}
    tokens = [token.upper() for token in re.findall(r"[A-Z]{2,}[A-Z0-9/_.-]{2,}", text, re.IGNORECASE)]
    return [token for token in tokens if token not in allowed]


def _mpns_outside_visible_state(text: str, recommendations: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[str]:
    allowed = {item["mpn"].upper() for item in recommendations} | {item["mpn"].upper() for item in selected}
    tokens = [token.upper() for token in re.findall(r"[A-Z]{2,}[A-Z0-9/_.-]{2,}", text, re.IGNORECASE)]
    return [token for token in tokens if token not in allowed]


def _extract_requirement(project_id: str, trace_id: str, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    fallback = _rule_parse_requirement(message).model_dump()
    user_prompt = f"历史摘要：\n{_history_summary(history)}\n\n当前用户：{message}"
    event_bus.publish(project_id, trace_id, "prompt_built", {"stage": "requirement_parse", "system_prompt": REQUIREMENT_PARSE_PROMPT, "user_prompt": user_prompt})
    if llm_client.available:
        try:
            parsed = llm_client.json_complete(REQUIREMENT_PARSE_PROMPT, user_prompt)
            for key, value in fallback.items():
                if parsed.get(key) in (None, "", []):
                    parsed[key] = value
            parsed["category"] = str(parsed["category"]).lower() if parsed.get("category") else None
            parsed["interface"] = str(parsed["interface"]).lower() if parsed.get("interface") else None
            for key in ["vin", "vout", "current", "sample_rate_ksps"]:
                parsed[key] = _to_float(parsed.get(key))
            for key in ["resolution_bits", "channels", "quantity"]:
                parsed[key] = _to_int(parsed.get(key)) or (1 if key == "quantity" else None)
            parsed["raw_text"] = message
            parsed["missing_fields"] = missing_fields(parsed)
            event_bus.publish(project_id, trace_id, "requirement_parse", parsed)
            return parsed
        except Exception as exc:
            event_bus.publish(project_id, trace_id, "error", {"stage": "requirement_parse", "message": str(exc)})
    fallback["missing_fields"] = missing_fields(fallback)
    event_bus.publish(project_id, trace_id, "requirement_parse", fallback)
    return fallback


def _matches(part: InventoryPart, req: dict[str, Any], category: str) -> tuple[bool, list[str], list[str], float]:
    params = part.parameters or {}
    reasons = ["库存可用"] if part.quantity_available > 0 else ["库存为 0，仅作知识候选"]
    risks: list[str] = []
    score = 50.0 + (25.0 if part.quantity_available > 0 else 0.0)
    if part.category != category:
        return False, reasons, ["类别不匹配"], 0
    if category in {"adc", "dac"}:
        resolution = _to_int(req.get("resolution_bits"))
        channels = _to_int(req.get("channels"))
        part_resolution = _param_number(params, "resolution_bits", "resolution", "bits") or 0
        if resolution and part_resolution < resolution:
            return False, reasons, ["分辨率不足"], 0
        if channels and params.get("channels", 0) < channels:
            return False, reasons, ["通道数不足"], 0
        iface = _interface_text(params)
        if req.get("interface") and _norm(req["interface"]) not in iface:
            return False, reasons, ["接口不匹配"], 0
        if _has_high_speed_intent(str(req.get("raw_text") or ""), req):
            speed = _converter_rate_ksps(params, category)
            if speed is None or speed < 100:
                return False, reasons, ["高速场景下转换速率不足"], 0
        reasons.append("核心转换参数满足")
        score += 15
    if category in {"ldo", "buck"}:
        vin, vout, current = _to_float(req.get("vin")), _to_float(req.get("vout")), _to_float(req.get("current"))
        if vin is not None and not (params.get("vin_min", -999) <= vin <= params.get("vin_max", 999)):
            return False, reasons, ["输入范围不满足"], 0
        if vout is not None and "vout" in params and abs(float(params["vout"]) - vout) > 0.08:
            return False, reasons, ["输出电压不匹配"], 0
        if current is not None and params.get("iout_max", 0) < current * 1.25:
            return False, reasons, ["电流余量不足"], 0
        reasons.append("电源约束满足")
        score += 15
    if category == "mcu" and req.get("interface"):
        interfaces = [str(item).lower() for item in params.get("interfaces", [])]
        if str(req["interface"]).lower() not in interfaces:
            return False, reasons, ["接口不匹配"], 0
        reasons.append("外设接口满足")
        score += 10
    return True, reasons, risks, min(score, 100)


def _requested_slots(message: str, requirement: dict[str, Any], agent_state: dict[str, Any]) -> list[dict[str, Any]]:
    text = message.lower()
    slots: list[dict[str, Any]] = []
    requested_resolution = _to_int(requirement.get("resolution_bits"))

    if requirement.get("category"):
        slots.append({"category": requirement["category"], "resolution_bits": requested_resolution, "raw_text": message, "quantity": requirement.get("quantity") or 1})

    if ("dac" in text or "数模" in message or "信号源" in message) and not any(slot["category"] == "dac" for slot in slots):
        slots.append({"category": "dac", "resolution_bits": requested_resolution, "raw_text": message, "quantity": 1})
    if ("adc" in text or "采集" in message or "采样" in message or "模数" in message) and not any(slot["category"] == "adc" for slot in slots):
        slots.append({"category": "adc", "resolution_bits": requested_resolution, "raw_text": message, "quantity": 1})

    if not slots:
        for category in _infer_categories(message, requirement, agent_state):
            slots.append({"category": category, "resolution_bits": requested_resolution, "raw_text": message, "quantity": 1})
    return slots


def _slot_score(part: InventoryPart, slot: dict[str, Any], base_score: float) -> tuple[bool, float, list[str], list[str]]:
    params = part.parameters or {}
    reasons: list[str] = []
    risks: list[str] = []
    score = base_score
    requested_resolution = _to_int(slot.get("resolution_bits"))
    part_resolution = _param_number(params, "resolution_bits", "resolution", "bits")

    if requested_resolution and part.category in {"adc", "dac"}:
        if part_resolution is None:
            return False, 0, reasons, ["缺少分辨率参数"]
        if part_resolution < requested_resolution:
            return False, 0, reasons, ["分辨率不足"]
        if part_resolution == requested_resolution:
            score += 50
            reasons.append(f"精确匹配 {requested_resolution} bit")
        else:
            score += max(15, 34 - (part_resolution - requested_resolution) * 8)
            reasons.append(f"{int(part_resolution)} bit 可覆盖 {requested_resolution} bit，但不是精确匹配")

    if part.quantity_available > 0:
        score += 18
        reasons.append(f"库存 {part.quantity_available}")
    else:
        score -= 18
        risks.append("库存为 0，需要补货或仅作指定方案")

    speed = _converter_rate_ksps(params, part.category)
    if _has_high_speed_intent(slot.get("raw_text") or "", slot):
        if speed is None or speed < 100:
            return False, 0, reasons, ["高速场景下转换速率不足"]
        score += min(18, speed / 100)
        reasons.append(f"速率约 {speed:g} kSPS")

    return True, min(score, 100), reasons, risks


def _infer_categories(message: str, requirement: dict[str, Any], agent_state: dict[str, Any]) -> list[str]:
    categories = []
    if requirement.get("category"):
        categories.append(requirement["category"])
    text = message.lower()
    mapping = {
        "adc": ["adc", "采样", "频谱", "模数", "测试"],
        "dac": ["dac", "激励", "信号源", "三音", "数模"],
        "mcu": ["mcu", "控制", "单片机", "usb", "通信"],
        "ldo": ["低噪声", "模拟电源", "稳压", "参考"],
        "buck": ["输入电源", "降压", "dc-dc", "供电"],
    }
    for category, words in mapping.items():
        if any(word in text or word in message for word in words) and category not in categories:
            categories.append(category)
    for item in agent_state.get("recommended_parts", []) or []:
        category = item.get("category")
        if category and category not in categories:
            categories.append(category)
    return categories or ["adc", "dac", "mcu", "ldo"]


def _stock_recommendations(requirement: dict[str, Any], message: str, selected: list[dict[str, Any]], agent_state: dict[str, Any]) -> list[dict[str, Any]]:
    selected_mpns = {item["mpn"] for item in selected}
    selected_categories = {item.get("category") for item in selected if item.get("category") and item.get("category") != "unknown"}
    replacement_intent = any(word in message for word in ["替换", "换掉", "改用", "不用"])
    output = []
    for slot in _requested_slots(message, requirement, agent_state):
        category = slot["category"]
        if category in selected_categories and not replacement_intent:
            continue
        candidates = []
        for part in store.iter_parts():
            if part.mpn in selected_mpns:
                continue
            ok, reasons, risks, score = _matches(part, requirement, category)
            if ok:
                slot_ok, slot_score, slot_reasons, slot_risks = _slot_score(part, slot, 0 if category in {"adc", "dac"} else score)
                if slot_ok:
                    candidates.append(Candidate(source="lab", part=part, reasons=slot_reasons or reasons, risks=slot_risks or risks, score=slot_score))
        candidates.sort(key=lambda item: item.score, reverse=True)
        for candidate in candidates[:2]:
            output.append({
                "id": f"rec-{candidate.part.id}",
                "part_id": candidate.part.id,
                "mpn": candidate.part.mpn,
                "category": candidate.part.category,
                "slot": category,
                "quantity": 0,
                "source": "model_recommendation",
                "score": round(candidate.score),
                "reasons": candidate.reasons,
                "risks": candidate.risks,
                "part": store.part_view(candidate.part),
            })
    return output[:10]


def _agent_state(project_id: str, trace_id: str, message: str, history: list[dict[str, Any]], requirement: dict[str, Any], inventory: list[dict[str, Any]], selected: list[dict[str, Any]], previous_recommended: list[dict[str, Any]]) -> dict[str, Any]:
    mpns = [item["mpn"] for item in inventory]
    user_prompt = (
        f"项目 ID：{project_id}\n"
        f"历史摘要：\n{_history_summary(history)}\n\n"
        f"库存型号白名单：{', '.join(mpns)}\n"
        f"库存摘要：\n{_format_inventory(inventory)}\n\n"
        f"已采用器件：\n{_selected_text(selected)}\n\n"
        f"当前候选器件：{json.dumps(previous_recommended, ensure_ascii=False)}\n"
        f"结构化需求：{json.dumps(requirement, ensure_ascii=False)}\n"
        f"用户最新输入：{message}\n\n"
        "只更新状态。reply 不要复读用户输入，不要说空话。"
    )
    event_bus.publish(project_id, trace_id, "prompt_built", {"stage": "agent_state", "system_prompt": AGENT_STATE_PROMPT, "user_prompt": user_prompt})
    fallback = {
        "project_goal": message[:120],
        "requirements_delta": requirement,
        "recommended_parts": [],
        "selected_parts_update": [],
        "open_questions": [],
        "next_action": "继续细化关键指标",
        "reply": "",
    }
    if llm_client.available:
        try:
            parsed = llm_client.json_complete(AGENT_STATE_PROMPT, user_prompt)
            if isinstance(parsed, dict):
                return fallback | parsed
        except Exception as exc:
            event_bus.publish(project_id, trace_id, "error", {"stage": "agent_state", "message": str(exc)})
    return fallback


def _merge_recommendations(stock_items: list[dict[str, Any]], llm_items: list[dict[str, Any]], inventory: list[dict[str, Any]], selected: list[dict[str, Any]], requirement: dict[str, Any]) -> list[dict[str, Any]]:
    by_mpn = {item["mpn"]: item for item in stock_items}
    inventory_by_mpn = {item["mpn"]: item for item in inventory}
    selected_mpns = {item["mpn"] for item in selected}
    for item in llm_items or []:
        mpn = item.get("mpn")
        if not mpn or mpn in selected_mpns or mpn not in inventory_by_mpn:
            continue
        category = item.get("category") or inventory_by_mpn[mpn].get("category", "")
        if not category or category == "unknown":
            continue
        try:
            part_model = store.get_part(inventory_by_mpn[mpn]["part_id"])
        except KeyError:
            continue
        ok, _, _, _ = _matches(part_model, requirement, category)
        if not ok:
            continue
        base = by_mpn.get(mpn, {
            "id": f"rec-{inventory_by_mpn[mpn]['part_id']}",
            "part_id": inventory_by_mpn[mpn]["part_id"],
            "mpn": mpn,
            "category": category,
            "quantity": 0,
            "source": "model_recommendation",
            "score": 70,
            "reasons": [],
            "risks": [],
            "part": inventory_by_mpn[mpn],
        })
        if item.get("reason"):
            base["reasons"] = [item["reason"]] + base.get("reasons", [])
        by_mpn[mpn] = base
    return list(by_mpn.values())[:10]


def _engineer_reply(project_id: str, trace_id: str, message: str, history: list[dict[str, Any]], requirement: dict[str, Any], inventory: list[dict[str, Any]], selected: list[dict[str, Any]], recommendations: list[dict[str, Any]], agent_state: dict[str, Any]) -> str:
    if not selected and ("三音" in message or "频谱" in message or "板子" in message or "板" in message):
        signal_part = next((item["mpn"] for item in recommendations if item.get("category") in {"dac", "adc"}), None)
        top = signal_part or (recommendations[0]["mpn"] if recommendations else "现有库存器件")
        return f"这个板子先按信号源、模拟前端、采样、控制、电源五块走。库存里先拿 {top} 做第一版候选；关键问题是目标频率范围和幅度范围。"
    top = recommendations[0]["mpn"] if recommendations else "现有库存器件"
    if selected:
        unverified = [item for item in selected if item.get("source") == "user_named_unverified" or item.get("category") == "unknown"]
        if unverified:
            names = "、".join(f"{item['mpn']}({item.get('category') or 'unknown'})" for item in unverified)
            adc = next((item["mpn"] for item in recommendations if item.get("category") == "adc"), None)
            suffix = f" ADC 候选先看 {adc}。" if adc else ""
            return f"已按你的决定把 {names} 保留为已采用件，但库内参数还不完整。下一步先补它的分辨率、更新率和接口数据；高速采集链路再按采样率定 ADC。{suffix}"
        chosen = "、".join(f"{item['mpn']}x{item['quantity']}" for item in selected)
        adc = next((item["mpn"] for item in recommendations if item.get("category") == "adc"), None)
        return f"{chosen} 已作为当前方案件保留。{('采集端先看 ' + adc + '，') if adc else ''}下一步只需要确认接口时序、参考电压和目标更新/采样率。"
    if recommendations:
        by_slot: dict[str, list[dict[str, Any]]] = {}
        for item in recommendations:
            by_slot.setdefault(item.get("slot") or item.get("category") or "器件", []).append(item)
        fragments = []
        for slot, items in by_slot.items():
            primary = items[0]
            reason = "、".join(primary.get("reasons", [])[:2])
            alt = f"，备选 {items[1]['mpn']}" if len(items) > 1 else ""
            fragments.append(f"{slot.upper()} 槽位先看 {primary['mpn']}（{reason}）{alt}")
        question = "下一步确认 DAC 更新率和 ADC 采样率，这会决定是否要保留高速件。"
        return "；".join(fragments[:3]) + "。" + question
    category = requirement.get("category")
    return f"库存里暂时没有稳妥候选。先补一个关键条件：{schema_guidance(category)}"


def _sanitize_inventory_claims(text: str, inventory_mpns: list[str]) -> str:
    known = set(inventory_mpns)
    sentences = re.split(r"([。！？\n])", text)
    output = []
    for index in range(0, len(sentences), 2):
        sentence = sentences[index]
        punct = sentences[index + 1] if index + 1 < len(sentences) else ""
        tokens = set(re.findall(r"[A-Z]{2,}[A-Z0-9/_.-]{2,}", sentence))
        if any(token not in known for token in tokens) and "库存" in sentence:
            sentence = sentence.replace("库存现成", "外购待确认").replace("库存可用", "外购待确认").replace("库存", "外购待确认")
        output.append(sentence + punct)
    return "".join(output)


def prepare_discussion_reply(project_id: str, message: str, trace_id: str | None = None) -> dict[str, Any]:
    trace_id = trace_id or f"trace-{uuid4().hex[:10]}"
    history = store.list_chat_messages(project_id)
    store.add_chat_message(project_id, "user", message)
    event_bus.publish(project_id, trace_id, "user_message", {"message": message})
    inventory = _inventory_brief()
    selected = store.list_selected_parts(project_id)
    previous_recommended = []
    for item in reversed(history):
        payload = item.get("payload") or {}
        if payload.get("recommended_parts"):
            previous_recommended = payload["recommended_parts"]
            break
    event_bus.publish(project_id, trace_id, "inventory_snapshot", {"parts": inventory})
    event_bus.publish(project_id, trace_id, "selected_parts_snapshot", {"parts": selected})
    requirement = _extract_requirement(project_id, trace_id, message, history)
    updated_selected = _manual_selected_updates(message, inventory, selected)
    if updated_selected != selected:
        selected = store.upsert_selected_parts(project_id, updated_selected)
        event_bus.publish(project_id, trace_id, "manual_parts_update", {"parts": selected, "reason": "explicit_mpn_adoption"})
        event_bus.publish(project_id, trace_id, "selected_parts_snapshot", {"parts": selected})
    state_json = _agent_state(project_id, trace_id, message, history, requirement, inventory, selected, previous_recommended)
    stock_recs = _stock_recommendations(requirement, message, selected, state_json)
    recommendations = stock_recs
    reply = _engineer_reply(project_id, trace_id, message, history, requirement, inventory, selected, recommendations, state_json)
    reply = _sanitize_inventory_claims(re.sub(r"\n{3,}", "\n\n", reply), [item["mpn"] for item in inventory])[:700]

    payload = {
        "mode": "engineering_discussion",
        "project_goal": state_json.get("project_goal"),
        "requirements_delta": state_json.get("requirements_delta"),
        "open_questions": state_json.get("open_questions", []),
        "next_action": state_json.get("next_action"),
        "requirement": requirement,
        "recommended_parts": recommendations,
        "selected_parts_snapshot": selected,
        "pending_selection": {"summary": reply, "requirement": requirement, "recommended_parts": recommendations, "selected_parts": selected},
    }
    event_bus.publish(project_id, trace_id, "recommended_parts", {"parts": recommendations})
    event_bus.publish(project_id, trace_id, "llm_final", {"text": reply, "internal_json": state_json})
    store.add_chat_message(project_id, "assistant", reply, payload)
    store.update_project_context(project_id, message, reply)
    event_bus.publish(project_id, trace_id, "db_write", {"chat_messages": 2, "debug_trace": True})
    trace = {
        "trace_id": trace_id,
        "project_id": project_id,
        "user_message": message,
        "system_prompt": AGENT_STATE_PROMPT,
        "user_prompt": json.dumps({"history": _history_summary(history), "requirement": requirement, "selected": selected, "recommendations": recommendations}, ensure_ascii=False),
        "llm_output": reply,
        "internal_state": payload | {"agent_state_json": state_json},
        "events": (event_bus.trace(trace_id) or {}).get("events", []),
    }
    store.save_debug_trace(trace)
    return {"trace_id": trace_id, "reply": reply, "payload": payload}


def discuss_selection(project_id: str, message: str) -> dict[str, Any]:
    result = prepare_discussion_reply(project_id, message)
    return {"trace_id": result["trace_id"], "messages": store.list_chat_messages(project_id), "payload": result["payload"]}


def confirm_selection(project_id: str, requirement: dict[str, Any], summary: str, parts: list[dict[str, Any]] | None = None, trace_id: str | None = None) -> dict[str, Any]:
    trace_id = trace_id or f"manual-{uuid4().hex[:10]}"
    selected = store.upsert_selected_parts(project_id, parts or store.list_selected_parts(project_id))
    selection = store.save_selection_plan(project_id, requirement, summary)
    event_bus.publish(project_id, trace_id, "selection_confirmed", {"selection": selection, "selected_parts": selected})
    event_bus.publish(project_id, trace_id, "db_write", {"selection_plan": selection["id"], "selected_parts": len(selected)})
    store.add_chat_message(project_id, "assistant", "已确认采用，右侧器件状态已写入数据库。", {"selection": selection, "selected_parts": selected})
    return {"selection": selection, "selected_parts": selected}


def build_recommendation_session(project_id: str, requirement: dict[str, Any]) -> RecommendationSession:
    recommendations = _stock_recommendations(requirement, requirement.get("raw_text", ""), [], {})
    candidates = []
    for item in recommendations:
        if item.get("part_id"):
            candidates.append(Candidate(source="lab", part=store.get_part(item["part_id"]), score=float(item.get("score", 0)), reasons=item.get("reasons", []), risks=item.get("risks", [])))
    req = Requirement(**({"raw_text": requirement.get("raw_text", "")} | requirement))
    return RecommendationSession(id=f"rec-{uuid4().hex[:10]}", project_id=project_id, requirement=req, candidates=candidates, summary="; ".join(item["mpn"] for item in recommendations[:3]))
