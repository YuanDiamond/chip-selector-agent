# Chip Selector Agent

面向电路板研发的芯片与器件选型 Agent。系统把自然语言需求、实验室库存、数据手册知识和人工确认流程串起来，用于辅助工程师完成板级方案讨论、候选器件推荐、库存管理和出库记录。

## 核心能力

- Agent 对话页：用户用自然语言描述板子目标或器件需求，系统给出工程建议并同步右侧候选器件。
- 芯片库管理页：维护器件型号、类别、库存数量、库位、参数和数据手册知识。
- LangGraph 选型流程：将需求解析、上下文管理、库存过滤、知识检索、推荐生成拆成可调试节点。
- 多项目隔离：每个项目独立保存聊天记录、项目摘要、已采用器件、推荐状态和调试 trace。
- 数据手册知识化：上传 PDF 后先生成可编辑预览，人工确认后再写入芯片库和知识片段。
- 统一调试事件流：网页端交互时，调试端可实时看到用户输入、prompt、LLM 输出、内部 JSON 和数据库写入。

## 技术栈

- 后端：FastAPI、SQLAlchemy、Pydantic
- Agent：LangGraph、自定义上下文管理、OpenAI-compatible LLM SDK
- 数据库：默认 SQLite，可通过 `DATABASE_URL` 切换到 SQLAlchemy 支持的其他数据库
- 前端：原生 HTML/CSS/JavaScript，NDJSON 流式输出
- 文档解析：pypdf + LLM 参数抽取 + 人工确认入库

## 快速启动

```powershell
cd F:\code\chip-selector-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，填入真实模型配置：

```env
OPENAI_API_KEY=your-real-api-key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

启动服务：

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 调试端

调试端订阅后端 SSE 事件流，不再 monkey patch LLM。网页端发送消息后，调试端会看到同一轮对话的 `trace_id`、用户输入、提示词、模型输出、推荐器件和数据库写入状态。

```powershell
python debug.py --project-id p-demo
```

如果需要让调试端顺手启动服务：

```powershell
python debug.py --start-server --project-id p-demo
```

## 数据与密钥

真实 API Key 只放在本地 `.env` 中，仓库只提交 `.env.example`。`.gitignore` 已忽略 `.env`、虚拟环境、SQLite 运行库、缓存和生成文档，避免把密钥或本地数据上传到 GitHub。

数据库默认路径为：

```text
data/chip_selector.sqlite3
```

如需切换数据库，可在 `.env` 中设置：

```env
DATABASE_URL=sqlite:///F:/code/chip-selector-agent/data/chip_selector.sqlite3
```

## GitHub 上传准备

```powershell
git status
git add .
git commit -m "Initial chip selector agent"
git remote add origin https://github.com/<your-name>/<your-repo>.git
git push -u origin main
```

提交前建议再运行一次：

```powershell
python -m compileall app debug.py
git status --ignored
```
