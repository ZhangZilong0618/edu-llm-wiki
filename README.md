# Edu-LLM-Wiki

AI驱动的教育知识库系统，支持文档导入、知识图谱构建、智能问答和语义搜索。

## 功能特性

### 核心功能

- **文档导入与解析**: 支持 PDF、DOCX、XLSX、PPTX、Markdown、TXT 等格式
- **知识图谱**: 自动构建知识图谱，可视化概念关系，支持社区检测和图洞察
- **智能问答 (RAG)**: 基于图增强的 RAG 管道，支持流式响应
- **语义搜索**: 结合向量搜索和关键词搜索的混合检索
- **Wiki 管理**: 创建、编辑、删除知识页面，支持 Wikilink 语法
- **多项目支持**: 支持多个独立的知识库项目

### 辅助功能

- 对话历史管理
- 知识图谱洞察（孤立节点、桥接概念、跨类型连接）
- LLM 配置管理（支持 OpenAI、Anthropic、Ollama）
- 文档质量检查 (Lint)

## 技术架构

### 后端架构

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Server                         │
├─────────────────────────────────────────────────────────────┤
│  Routes Layer                                               │
│  ├── /api/wiki      (Wiki CRUD)                            │
│  ├── /api/chat      (RAG Chat)                             │
│  ├── /api/search    (Hybrid Search)                        │
│  ├── /api/graph     (Knowledge Graph)                      │
│  ├── /api/ingest    (Document Ingestion)                   │
│  └── /api/settings  (LLM Configuration)                    │
├─────────────────────────────────────────────────────────────┤
│  Services Layer                                             │
│  ├── llm_client     (OpenAI/Anthropic/Ollama Adapter)      │
│  ├── vector_store   (LanceDB + Sentence-Transformers)      │
│  ├── graph_engine   (NetworkX + Louvain Community)         │
│  ├── search_engine  (Keyword + Vector Hybrid)              │
│  └── ingest_engine  (Document Parser)                      │
├─────────────────────────────────────────────────────────────┤
│  Storage Layer                                              │
│  ├── wiki_store     (Markdown Files with Frontmatter)      │
│  └── LanceDB        (Vector Embeddings)                    │
└─────────────────────────────────────────────────────────────┘
```

### 关键技术组件

| 组件 | 技术栈 | 用途 |
|------|--------|------|
| Web 框架 | FastAPI + Uvicorn | 异步 API 服务 |
| 向量数据库 | LanceDB | 存储和检索文档嵌入 |
| 嵌入模型 | sentence-transformers (all-MiniLM-L6-v2) | 本地文本嵌入，384维 |
| 图数据库 | NetworkX | 知识图谱构建和分析 |
| 社区检测 | Louvain 算法 | 识别知识集群 |
| LLM 集成 | OpenAI/Anthropic SDK | 智能问答生成 |
| 文档解析 | pdfplumber, python-docx, openpyxl | 多格式文档处理 |

### RAG 管道流程

```
用户查询
    ↓
┌─────────────────┐
│ 1. 向量语义搜索  │ → LanceDB 相似度检索
└────────┬────────┘
         ↓
┌─────────────────┐
│ 2. 关键词搜索    │ → 标题和内容匹配
└────────┬────────┘
         ↓
┌─────────────────┐
│ 3. 图扩展 (1跳) │ → 邻居节点扩展
└────────┬────────┘
         ↓
┌─────────────────┐
│ 4. 优先级填充    │ → 预算控制上下文
└────────┬────────┘
         ↓
┌─────────────────┐
│ 5. LLM 生成     │ → 流式响应
└─────────────────┘
```

### 知识图谱边权重计算 (4信号评分)

1. **直接链接** (权重 3.0): Wikilink 双向链接计数
2. **来源重叠** (权重 4.0): 共享参考源数量
3. **公共邻居** (权重 1.5): Adamic-Adar 算法
4. **类型亲和度** (权重 1.0): 跨知识类型关联矩阵

### 前端架构

```
┌─────────────────────────────────────────────────────────────┐
│                    React + TypeScript                        │
├─────────────────────────────────────────────────────────────┤
│  Components                                                 │
│  ├── chat/         (AI 对话界面)                            │
│  ├── graph/        (Sigma.js 知识图谱可视化)                │
│  ├── search/       (搜索结果展示)                           │
│  ├── sources/      (文档管理)                               │
│  ├── settings/     (LLM 配置)                               │
│  └── layout/       (应用布局)                               │
├─────────────────────────────────────────────────────────────┤
│  State Management: Zustand                                  │
│  Styling: Tailwind CSS v4                                   │
│  Graph Rendering: Sigma.js + Graphology                     │
│  Markdown: react-markdown + KaTeX                           │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求

- Python >= 3.10
- Node.js >= 18
- npm 或 pnpm

### 1. 克隆项目

```bash
git clone <repository-url>
cd edu-llm-wiki
```

### 2. 启动后端服务

```bash
cd edu-llm-wiki/backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量 (可选)
cp .env.example .env
# 编辑 .env 文件，配置 LLM API Key

# 启动服务
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

后端服务地址: `http://127.0.0.1:8000`

### 3. 启动前端服务

```bash
cd edu-llm-wiki/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端访问地址: `http://localhost:5173`

## 端口配置

| 服务 | 默认端口 | 地址 |
|------|----------|------|
| 后端 API | 8000 | http://127.0.0.1:8000 |
| 前端开发服务器 | 5173 | http://localhost:5173 |
| API 文档 (Swagger) | 8000 | http://127.0.0.1:8000/docs |
| API 文档 (ReDoc) | 8000 | http://127.0.0.1:8000/redoc |

## 环境变量配置

在 `backend/.env` 文件中配置:

```env
# LLM 配置
LLM_PROVIDER=openai          # openai | anthropic | ollama | custom
LLM_API_KEY=sk-xxx           # API Key
LLM_MODEL=gpt-4o-mini        # 模型名称
LLM_BASE_URL=                # 自定义端点 (Ollama: http://localhost:11434/v1)
LLM_MAX_TOKENS=8192          # 最大生成 token 数
LLM_TEMPERATURE=0.3          # 生成温度

# 嵌入模型配置
EMBEDDING_ENABLED=true        # 启用向量搜索
EMBEDDING_MODEL=all-MiniLM-L6-v2  # 本地嵌入模型

# 服务器配置
HOST=127.0.0.1
PORT=8000
API_TOKEN=                   # API 访问令牌 (可选)

# CORS 配置
CORS_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173"]
```

## API 端点

### Wiki 管理
- `GET /api/wiki/pages` - 获取页面列表
- `POST /api/wiki/pages` - 创建页面
- `PUT /api/wiki/pages/{path}` - 更新页面
- `DELETE /api/wiki/pages/{path}` - 删除页面

### 智能问答
- `POST /api/chat` - 普通问答
- `POST /api/chat/stream` - 流式问答 (SSE)

### 搜索
- `GET /api/search?q={query}` - 混合搜索

### 知识图谱
- `GET /api/graph` - 获取完整图谱
- `GET /api/graph/neighborhood/{node_id}` - 获取节点邻居
- `GET /api/graph/insights` - 获取图洞察

### 文档导入
- `POST /api/ingest/upload` - 上传文档
- `POST /api/ingest/run` - 执行导入
- `POST /api/ingest/run-stream` - 流式导入 (SSE)
- `GET /api/ingest/sources` - 列出源文件

### 项目管理
- `GET /api/projects` - 列出项目
- `POST /api/projects` - 创建项目
- `DELETE /api/projects/{id}` - 删除项目

### 设置
- `GET /api/settings/llm` - 获取 LLM 配置
- `PUT /api/settings/llm` - 更新 LLM 配置
- `POST /api/settings/llm/test` - 测试 LLM 连接

## 数据目录结构

```
data/
└── projects/
    ├── default/           # 默认项目
    │   ├── wiki/          # Wiki 页面 (Markdown)
    │   │   ├── concepts/
    │   │   ├── formulas/
    │   │   ├── principles/
    │   │   ├── exercises/
    │   │   ├── sources/
    │   │   ├── purpose.md
    │   │   ├── schema.md
    │   │   └── index.md
    │   └── sources/       # 原始文档
    └── {project-id}/      # 其他项目
        ├── wiki/
        └── sources/
```

## 开发命令

### 后端

```bash
# 代码检查
ruff check .

# 代码格式化
ruff format .

# 类型检查
mypy .

# 运行测试
pytest
```

### 前端

```bash
# 开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview

# 代码检查
npm run lint

# 代码格式化
npm run format

# 类型检查
npm run typecheck
```

## 许可证

MIT License
