# Chip Selector Agent

Chip Selector Agent 是一个面向电路板研发的器件选型工具。它把自然语言对话、实验室库存、数据手册解析和人工确认流程放在同一个工作台里，帮助工程师更快地从需求走到可落地的器件方案。

这个项目适合用于小型实验室、学生项目、研发样机和内部器件库管理。你可以直接描述板子的目标，例如“我要做一个三音频谱测试板”或“需要一个 16 bit DAC，再用 ADC 采集输出”，系统会结合当前库存给出候选器件，并在你确认后记录到项目方案中。

## 功能

- 对话式选型：用自然语言描述需求，Agent 给出简短的工程建议和候选器件。
- 项目管理：不同项目拥有独立的聊天记录、推荐结果和已采用器件。
- 器件库管理：维护型号、类别、封装、库存数量、库位和关键参数。
- 数据手册导入：上传 PDF 后自动提取器件信息，先预览和编辑，再确认入库。
- 库存同步：用户确认采用器件后，可以继续做预占、补货和出库记录。
- 可视化界面：提供 Agent 对话页和芯片库管理页，适合本地部署使用。

## 技术栈

- FastAPI
- SQLAlchemy
- LangGraph
- OpenAI-compatible SDK
- SQLite
- 原生 HTML / CSS / JavaScript

## 快速开始

克隆项目并进入目录：

```bash
git clone https://github.com/<your-name>/chip-selector-agent.git
cd chip-selector-agent
```

创建虚拟环境并安装依赖：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，填入你的模型配置：

```env
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

启动服务：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

## 使用方式

1. 在项目页新建一个项目，例如“DAC 校准板”。
2. 进入 Agent 页面，直接描述目标或器件需求。
3. 查看右侧推荐器件，按需要修改数量或删除不需要的候选项。
4. 确认采用后，器件会写入当前项目的方案状态。
5. 在芯片库页面维护库存，也可以导入数据手册补充器件知识。

## 数据手册导入

芯片库页面支持上传 PDF 数据手册。系统会先解析型号、厂商、类别、封装、描述和关键参数，并显示一个可编辑预览。只有当你确认“新增芯片知识”后，数据才会写入数据库。

新导入的器件库存默认是 `0`，这样可以避免把“数据库里有这个型号”误认为“实验室里有现货”。

## 本地数据

默认数据库是 SQLite，文件会自动创建在：

```text
data/chip_selector.sqlite3
```

如果你想换成其他数据库，可以在 `.env` 中设置：

```env
DATABASE_URL=sqlite:///data/chip_selector.sqlite3
```

## 密钥安全

真实 API Key 只应该放在本地 `.env` 文件中。仓库里的 `.env.example` 只是模板，`.env`、本地数据库和虚拟环境都已经被 `.gitignore` 排除，不会被提交到 Git。

如果你曾经把真实密钥写进代码，建议立即撤销旧密钥并重新生成。

## 适用范围

这个项目更适合做本地研发辅助和实验室器件库管理，不适合作为未经校验的自动 BOM 决策系统。硬件选型仍然需要工程师确认数据手册、封装、电气指标、供货情况和实际库存。
