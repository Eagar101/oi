# 自动化深度研究智能体

> 4-Agent 协作的深度研究系统：Planner → Search → Summary → Write
>
> 输入一句话研究问题，自动拆解关键词、多轮搜索、CoT 数据清洗、构建知识图谱、生成 Markdown 报告。

---

## 功能特性

- **4 Agent 流水线**：每个 Agent 职责单一，通过 JSON 串联，可独立调试
- **多轮深度搜索**：DuckDuckGo 公开网页搜索，自动生成子查询，URL 去重合并
- **CoT 数据清洗**：相关性过滤 + 逻辑一致性检查 + 信息去重合并，带清洗日志
- **知识图谱**：关键词为节点，LLM 分析依赖/使能/相关关系为边
- **追问机制**：基于父报告追加章节而非重写，保留完整研究脉络
- **实时进度**：WebSocket 推送每个 Agent 的执行状态和中间数据
- **可视化**：SVG 知识图谱、任务关系树、Agent 流水线高亮
- **多用户**：JWT 认证 + SQLite 持久化，支持任务并发上限控制

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

### 2. 安装依赖

```bash
cd C:\Users\liu\PycharmProjects\PythonProject
.\.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

### 3. 配置

在项目根目录创建 `.env`：

```env
# Anthropic 兼容 API 配置
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://opencode.ai/go

# 模型配置
PLANNER_MODEL=DeepSeek V4 Flash
PLANNER_TEMPERATURE=0.3
PLANNER_MAX_TOKENS=2048

# 可选：搜索与持久化
SEARCH_MAX_RESULTS=5
SEARCH_DEEP_SEARCH=true
SEARCH_MAX_ROUNDS=3
SUMMARY_PERSIST_DIR=./data
WRITE_OUTPUT_DIR=./reports

# 可选：Web 服务
JWT_SECRET=change-me-in-production
MAX_CONCURRENT_PER_USER=2
MAX_CONCURRENT_TOTAL=10
```

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

---

## 目录结构

```
PythonProject/
├── main.py                  # CLI 入口
├── requirements.txt
├── .env                     # 配置（需自建）
├── research.db              # SQLite 数据库（自动生成）
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

## License

MIT
