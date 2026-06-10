#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def _print_block(title: str, value: object, color: str = CYAN) -> None:
    print(f"\n{BOLD}{color}== {title} =={RESET}")
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = str(value)
    print(text if text.strip() else f"{DIM}<empty>{RESET}", flush=True)


def _print_event(event: dict) -> None:
    event_type = event.get("type")
    trace_id = event.get("trace_id")
    project_id = event.get("project_id")
    payload = event.get("payload") or {}
    print(f"\n{BOLD}{GREEN}[{event_type}]{RESET} project={project_id} trace={trace_id}")

    if event_type == "user_message":
        _print_block("用户输入", payload.get("message", ""), YELLOW)
    elif event_type == "prompt_built":
        _print_block("阶段", payload.get("stage", ""), MAGENTA)
        if payload.get("context"):
            _print_block("注入上下文", payload["context"], CYAN)
        _print_block("System Prompt", payload.get("system_prompt", ""), MAGENTA)
        _print_block("User Prompt", payload.get("user_prompt", ""), MAGENTA)
    elif event_type == "llm_delta":
        print(payload.get("text", ""), end="", flush=True)
    elif event_type == "llm_final":
        _print_block("LLM 最终输出", payload.get("text", ""), GREEN)
    elif event_type in {"requirement_parse", "inventory_snapshot", "recommended_parts", "manual_parts_update", "selection_confirmed", "selected_parts_snapshot", "db_write"}:
        _print_block("内部状态", payload, CYAN)
    elif event_type == "error":
        _print_block("错误", payload, RED)
    else:
        _print_block("Payload", payload, CYAN)


def _connect(url: str) -> None:
    print(f"{BOLD}{CYAN}订阅调试事件：{url}{RESET}")
    with urllib.request.urlopen(url, timeout=60) as response:
        buffer = ""
        while True:
            chunk = response.readline()
            if not chunk:
                time.sleep(0.2)
                continue
            line = chunk.decode("utf-8", errors="replace").strip()
            if not line:
                if buffer.startswith("data:"):
                    raw = buffer[5:].strip()
                    try:
                        _print_event(json.loads(raw))
                    except json.JSONDecodeError:
                        print(raw)
                buffer = ""
                continue
            buffer += line


def main() -> None:
    parser = argparse.ArgumentParser(description="Chip Selector Agent 调试端：订阅后端统一事件流")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument("--project-id", default="p-demo")
    parser.add_argument("--start-server", action="store_true", help="先启动 uvicorn，再订阅 SSE")
    args = parser.parse_args()

    server = None
    if args.start_server:
        root = Path(__file__).resolve().parent
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)], cwd=root)
        time.sleep(1.5)

    query = f"?project_id={urllib.parse.quote(args.project_id)}" if args.project_id else ""
    url = f"http://{args.host}:{args.port}/api/debug/events{query}"
    try:
        _connect(url)
    except urllib.error.URLError as exc:
        print(f"{RED}无法连接后端：{exc}{RESET}")
        print(f"{YELLOW}可先运行：python -m uvicorn app.main:app --host {args.host} --port {args.port}{RESET}")
    except KeyboardInterrupt:
        print(f"\n{GREEN}调试端已停止。{RESET}")
    finally:
        if server:
            server.terminate()


if __name__ == "__main__":
    main()
