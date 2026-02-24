# CommandCraft — Minecraft 基岩版 AI 命令生成器

> 用自然语言描述你的需求，AI 帮你生成精确的基岩版命令。

基于云端大语言模型的 Minecraft 基岩版命令智能生成工具。通过 **Parallel TaskAgent 架构**，将自然语言需求拆解为多个并行任务，每个任务独立检索知识库、生成命令、校验结果，最终汇总输出。

## 功能特性

- **自然语言输入** — 用中文描述需求，AI 自动生成基岩版命令
- **多任务并行** — 复杂需求自动拆解为多个子任务，按依赖关系分层并行执行
- **RAG 知识库** — 内置 138 条命令文档 + 12 类 ID 索引，ChromaDB 向量检索
- **智能追问** — 参数不完整时 AI 主动追问，提供选项引导
- **项目规划** — 自动拆解复杂项目为命令方块方案，生成三维布局
- **命令校验** — 规则引擎自动校验语法、ID、参数范围
- **多格式导出** — 支持 `.mcfunction` 和 `.mcstructure` (NBT) 文件导出
- **流式输出** — SSE 实时展示思维链推理过程和任务进度
- **多模型支持** — 兼容 DeepSeek、通义千问、GLM、Kimi、豆包、ChatGPT、Gemini 等

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+ / pnpm
- 任一云端 LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com)）

### 1. 克隆项目

```bash
git clone https://github.com/xuanfeng233-coder/CommandCraft.git
cd CommandCraft
```

### 2. 启动后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload --port 8000
```

首次启动会自动构建 RAG 向量索引（约 1-2 分钟），后续启动秒速加载。

### 3. 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

浏览器访问 `http://localhost:5173`，在设置面板中配置 LLM 提供商和 API Key 即可使用。

### Docker 部署

```bash
docker-compose up -d
```

## 使用示例

| 输入 | 效果 |
|------|------|
| 给我一把锋利5的钻石剑 | 生成 `/give` 命令 + 附魔参数 |
| 传送所有僵尸到我这里 | 生成 `/tp` + `@e[type=zombie]` 选择器 |
| 做一个击杀计分板系统 | 项目规划 → 多个命令方块 + 三维布局 |
| 每5秒在玩家周围生成僵尸 | 循环命令方块方案 + execute 链 |

## 架构概览

```
用户输入
  │
  ▼
Main Agent (decompose) ── 拆解为 TaskDefinition[]
  │
  ▼
TaskManager (分层并行执行)
  ├── Tier 0: [Task A, Task B]  ── 并行
  ├── Tier 1: [Task C]          ── 依赖 Tier 0
  └── ...
  │
  ▼ 每个 TaskAgent 独立执行:
  RAG 检索 → LLM 生成 → 命令校验 → (追问/完成)
  │
  ▼
Main Agent (summarize) ── 汇总多任务结果
  │
  ▼
后处理: 命令方块布局 + 校验 + 格式化 → SSE 输出
```

## 项目结构

```
├── backend/                  # FastAPI 后端
│   ├── agents/               # Main Agent + TaskAgent
│   ├── orchestrator/         # 编排器 (分层并行调度)
│   ├── rag/                  # RAG 子系统 (ChromaDB + bge-m3)
│   ├── skills/               # 规则型工具 (校验/布局/格式化)
│   ├── subscription/         # 订阅服务
│   ├── api/                  # REST API 端点
│   ├── export/               # .mcfunction / .mcstructure 导出
│   ├── knowledge/            # 知识库加载器
│   ├── utils/                # LLM 客户端 / 设置管理
│   └── models/               # 数据模型 + SQLite
├── frontend/                 # Vue 3 + TypeScript
│   └── src/
│       ├── views/            # 页面
│       ├── components/       # MC 风格 UI 组件
│       ├── stores/           # Pinia 状态管理
│       └── api/              # API 客户端
├── knowledge_base/           # 命令文档 + ID 索引
│   ├── commands/             # 138 条命令 JSON
│   ├── ids/                  # 12 类 ID 索引
│   ├── few_shot/             # Few-shot 示例
│   └── intent_map.json       # 意图映射
├── scripts/                  # 工具脚本
├── docker-compose.yml        # Docker 一键部署
└── Dockerfile.backend        # 后端镜像
```

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue 3 + TypeScript + Minecraft 风格 UI + Vite |
| 后端 | FastAPI + Python |
| LLM | OpenAI SDK (兼容 DeepSeek / Qwen / GLM / Kimi / 豆包 / ChatGPT / Gemini) |
| 向量检索 | ChromaDB + sentence-transformers (BAAI/bge-m3) |
| 数据库 | SQLite (aiosqlite, WAL) |
| 通信 | HTTP + SSE (Server-Sent Events) |
| 部署 | Docker + docker-compose |

## 导出格式

- **.mcfunction** — 可直接放入行为包的命令文件
- **.mcstructure** — 命令方块布局 NBT 文件，游戏内用 `/structure load` 加载

## 配置说明

启动后在前端设置面板中配置：

| 配置项 | 说明 |
|--------|------|
| LLM 提供商 | 选择 API 服务商 (DeepSeek / Qwen / GLM 等) |
| API Key | 对应服务商的 API 密钥 |
| 模型 | 具体模型名称 (如 `deepseek-chat`) |

配置保存在浏览器 localStorage 中，后端不持久化 API Key。

## 许可证

[AGPL License](LICENSE)
