# 自动化深度研究智能体

> 4-Agent 协作的深度研究系统：Planner → Search → Summary → Write
>
> 输入一句话研究问题，自动拆解关键词、多轮搜索、CoT 数据清洗、构建知识图谱、生成 Markdown 报告。
> 本研究体可以辅助用户解决问题的调研与下一步实施方案，同时在项目的进一步发展中追问以得到更准确的报告 

---

## 功能特性

- **多Agent 流水线**：每个 Agent 职责单一，通过 JSON 串联，可独立调试
- **多轮深度搜索**：DuckDuckGo 公开网页搜索，自动生成子查询，URL 去重合并
- **CoT 数据清洗**：利用CoT进行相关性过滤 + 逻辑一致性检查 + 信息去重合并，同时带清洗日志
- **知识图谱**：以关键词为节点，LLM 分析依赖/使能/相关关系为边
- **追问机制**：基于父报告追加章节而非重写，保留完整研究脉络
- **实时进度**：WebSocket 推送每个 Agent 的执行状态和中间数据
- **可视化**：SVG 知识图谱、任务关系树、Agent 流水线高亮
- **多用户**：JWT 认证 + SQLite 持久化，支持任务并发上限控制
- **文档上传与 RAG 问答**：上传 md/txt 文档，自动切片+本地向量嵌入，文档摘要注入 Planner，并支持基于文档的 RAG 问答

---

## 架构设计

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Planner   │ →  │   Search    │ →  │  Summary    │ →  │   Write     │
│  拆解关键词  │    │  多轮搜索    │    │ CoT清洗+图谱 │    │ 生成报告    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       ↓                 ↓                 ↓                 ↓
   PlannerOutput     SearchOutput      SummaryOutput      Markdown文件
   (关键词+TODO)     (来源+摘要)       (节点+边+总结)     (.md持久化)
```

**数据流**：每个 Agent 产出 pydantic 模型，JSON 字符串串联，可断点续传。

**追问模式**：父任务的 summary 作为上下文注入新 Planner，Write 读取父报告生成追加章节。

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 2. 克隆与安装依赖

```bash
git clone <your-repo-url>
cd PythonProject

# 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

### 3. 配置

复制示例配置并填入真实值：

```bash
cp .env .env              # macOS / Linux
# copy .env .env          # Windows cmd
# Copy-Item .env .env     # Windows PowerShell
```

编辑 `.env`，至少填写 `ANTHROPIC_API_KEY`：

```env
# 复制 .env.example 后修改以下关键字段
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://opencode.ai/go
PLANNER_MODEL=DeepSeek V4 Flash
```

其余字段保持默认即可，完整说明见 `.env.example`。

### 4. 运行

**Web 模式（推荐）**：

```bash
python -m api.main
```

浏览器访问 `http://localhost:8000`，注册账号后提交研究问题。

**CLI 模式**：

```bash
# 交互模式
python main.py

# 单次执行
python main.py "我要学习Python基础"

# 逐步确认（每个 Agent 执行前暂停）
python main.py --step

# 禁用深度搜索
python main.py --no-deep "我要学习Python基础"
```

---

## 使用指南

### Web 界面

1. **注册/登录**：`/register` 创建账号，自动签发 JWT
2. **控制台**：`/dashboard` 输入研究问题，实时查看 4 个 Agent 进度
3. **报告页**：`/report?id=<task_id>`
   - 查看渲染后的 Markdown 报告
   - 点击知识图谱节点查看来源
   - 选中报告中的文字 → 弹出"深入研究"按钮 → 一键发起追问
   - 提交追问 → 生成追加章节
   - 下载 Markdown / 删除报告

### CLI 交互

```
你> 我要研究深度研究智能体
[1/4] Planner Agent 处理中...
--- Planner 输出 ---
{ "keywords": [...], "summary": "...", "todos": [...] }

[2/4] Search Agent 搜索中...
  搜索关键词: ...
  深度搜索: ...

[3/4] Summary Agent 归纳总结中...
已持久化至: ./data/summary_xxx.json

[4/4] Write Agent 生成报告中...
报告已保存至: ./reports/report_xxx.md
```

---

## API 接口

所有接口前缀 `/api/v1`，需在 Header 携带 `Authorization: Bearer <token>`（除注册/登录）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册，返回 JWT |
| POST | `/auth/login` | 登录，返回 JWT |
| POST | `/tasks` | 提交研究任务，支持 `parent_task_id` 发起追问 |
| GET | `/tasks` | 列出历史任务，支持 `parent_only=true` |
| GET | `/tasks/{id}` | 查询任务状态 |
| GET | `/tasks/{id}/tree` | 获取任务树（父+所有追问） |
| GET | `/tasks/{id}/report` | 下载 Markdown 报告 |
| GET | `/tasks/{id}/summary` | 获取 Summary JSON（含知识图谱） |
| DELETE | `/tasks/{id}` | 删除任务及关联文件 |
| WS | `/ws/tasks/{id}` | WebSocket 推送进度 |

**WebSocket 消息类型**：`status` / `step` / `search_round` / `data` / `complete` / `error`

### 文档上传与 RAG 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/documents/upload` | 上传 md/txt（multipart `file`），解析→切片→嵌入，返回 `doc_id` |
| GET | `/documents` | 列出当前用户文档 |
| DELETE | `/documents/{id}` | 删除文档及其切片 |
| POST | `/chat` | RAG 问答，body `{question, document_ids?}` |

---

## 目录结构

```
PythonProject/
├── main.py                  # CLI 入口
├── requirements.txt
├── .env.example             # 示例配置（提交到仓库）
├── .env                     # 真实配置（需自建）
├── .gitignore
├── research.db              # SQLite 数据库（运行时自动生成）
│
├── planner_agent/           # Planner Agent：拆解关键词+TODO
│   ├── agent.py
│   ├── schema.py
│   ├── config.py
│   └── cli.py
│
├── search_agent/            # Search Agent：多轮搜索+去重
│   ├── agent.py
│   ├── searcher.py          # DuckDuckGo 封装
│   ├── schema.py
│   └── config.py
│
├── summary_agent/           # Summary Agent：CoT清洗+知识图谱
│   ├── agent.py
│   ├── persist.py           # JSON 持久化
│   ├── schema.py
│   └── config.py
│
├── write_agent/             # Write Agent：生成 Markdown 报告
│   ├── agent.py             # 支持追问追加章节
│   ├── schema.py
│   └── config.py
│
├── rag_agent/               # RAG Agent：文档摄入+向量检索+问答
│   ├── agent.py             # ingest/摘要/build_doc_context/answer
│   ├── parser.py            # md/txt 解析
│   ├── chunker.py           # 递归文本切片
│   ├── embedder.py          # fastembed 嵌入单例
│   ├── schema.py
│   └── config.py
│
├── api/                     # FastAPI Web 后端
│   ├── main.py              # 应用入口
│   ├── routes.py            # REST + WebSocket 路由
│   ├── runner.py            # 后台任务执行器
│   ├── auth.py              # JWT 认证
│   ├── db.py                # SQLite 数据访问
│   ├── ws.py                # WebSocket 连接管理
│   ├── templates/           # Jinja2 模板
│   └── static/              # 前端 JS + CSS
│
├── data/                    # Summary JSON 持久化目录
└── reports/                 # Markdown 报告输出目录
```

---

## Agent 详细说明

### Planner Agent
- 输入：用户长句
- 输出：3-8 个关键词、一句话总结、TODO 列表（带 high/medium/low 优先级）
- 严格 JSON 输出，pydantic 校验

### Search Agent
- 输入：PlannerOutput
- 流程：
  1. 每个关键词单独搜索（基础轮）
  2. 组合查询补充
  3. LLM 评估充分性，生成最多 2 个子查询（深度轮）
  4. 循环至信息充分或达到 `max_rounds` 上限
- URL 去重，LLM 生成综合摘要

### Summary Agent
- 输入：SearchOutput
- 4 次 LLM 调用：
  1. **CoT 数据清洗**：相关性过滤 + 逻辑一致性检查 + 去重合并，输出 `FilteringLog`
  2. **批量关键词摘要**：一次调用生成所有关键词的 200 字摘要
  3. **构建图谱边**：LLM 分析关键词间关系（depends_on / enables / relates_to / precedes）
  4. **全局总结**：300 字内综合所有关键词要点
- 持久化为 `data/summary_<query>_<timestamp>.json`

### Write Agent
- 输入：Planner + Search 摘要 + Summary
- 输出：3-5 页 Markdown 报告（执行摘要、背景、关键发现、行动项、关系分析、附录）
- **追问模式**：读取父报告，生成 `## 追加研究：...` 章节拼接到末尾，不重写

### RAG Agent（`rag_agent/`）
- **文档摄入** `ingest()`：解析 md/txt → 递归切片（默认 500 字/100 重叠）→ 本地 fastembed 嵌入（bge-small-zh-v1.5）→ SQLite 存向量；同内容哈希去重
- **文档摘要** `summarize_document()`：LLM 生成约 600 字摘要并缓存到 documents 表，用于注入 Planner
- **Planner 注入** `build_doc_context()`：把勾选文档的摘要拼成 `[用户上传文档摘要]` 块，附加到 Planner 输入后，让研究规划参考自有文档
- **RAG 问答** `answer()`：问题嵌入 → SQLite 余弦相似度检索 top_k → 拼接片段 prompt → LLM 生成回答，带来源片段和相似度分数

---

## 常见问题

**Q: 启动 Web 后访问 `http://0.0.0.0:8000` 失败？**
A: `0.0.0.0` 是监听地址，浏览器请访问 `http://localhost:8000` 或 `http://127.0.0.1:8000`。

**Q: Windows 终端中文乱码？**
A: `main.py` 已自动重设 stdout/stderr 为 UTF-8，PowerShell 执行 `chcp 65001` 可进一步保险。

**Q: DuckDuckGo 搜索失败？**
A: 网络环境问题，可配置代理或重试。搜索失败会返回空列表，不影响流水线继续。

**Q: LLM 触发速率限制？**
A: 内置 3 次重试 + 递增等待（15/30/60 秒），仍失败则任务标记为 `failed`。

**Q: 如何切换模型？**
A: 修改 `.env` 的 `PLANNER_MODEL`。4 个 Agent 共享同一套 API 配置。

**Q: 首次上传文档 / 问答很慢？**
A: 首次调用嵌入会下载 ~100MB 的 `bge-small-zh-v1.5` 模型到本地缓存，之后离线运行，不再等待。

**Q: RAG 问答只基于上传文档吗？**
A: 默认是。勾选文档限定检索范围，留空则检索该用户全部文档；不会联网。

---

## 技术栈

- **LLM 调用**：anthropic SDK（兼容任意 Anthropic 协议网关）
- **搜索**：ddgs（DuckDuckGo）
- **Web**：FastAPI + Uvicorn + Jinja2
- **实时通信**：WebSocket
- **数据校验**：pydantic v2
- **数据库**：SQLite（标准库 sqlite3）
- **前端**：原生 JS + SVG（无框架）
- **持久化**：JSON 文件（Summary）+ Markdown 文件（报告）+ SQLite（任务记录）

---

## 更新记录

### 2026-07 本次改动

- **搜索直奔意图，废除逐词搜索**：Search Agent 首轮直接用 Planner 的 summary（完整意图）搜索，不再逐个关键词弯弯绕；并新增「合乎逻辑的组合词搜索」轮（意图 × `最佳实践 案例`、`对比 优劣 2026`），扩大深度搜索覆盖面。后续 SUFFICIENCY 自动子查询循环逻辑不变。
- **CoT 清洗加严，剔除泛泛而谈**：Summary Agent 的 CoT prompt 以「用户意图」为首要基准重新判定相关性，明确三类归类标准——`几乎完全无关`（含 404/广告/导航/排行榜）/ `泛泛而谈`（套话、模板化文字）/ `高度相关`（须有具体事实/数据/步骤/对比/案例之一），并给出具体类别标签。同时增强 JSON 解析：返回被思考文本包裹时抽取 `{...}` 片段再解析，避免无谓回退。清洗后为空仍回退原始数据。
- **修复报告截断**：Write Agent 的 `WRITE_MAX_TOKENS` 由 4096 提至 8192，并在 prompt 加入「接近上限主动压缩、务必完整收尾、绝不中途截断」的要求，附优先保核心章节、附录可精简的详略控制。
- **修复追问崩溃**：追问追加章节的 prompt 里 `{追问问题简述}` 被误当作 Python 变量求值，导致 `name '追问问题简述' is not defined`。改为自然语言由模型自行概括，消除占位符歧义。
- **修复任务树跳转**：报告页任务树子任务/追问的「查看」按钮此前调用未定义的 `openReport`（仅存在于 dashboard），点击无反应。已在 `report.js` 补齐该函数，正确跳转到 `/report?id=<子任务>`。

---

## License

MIT
