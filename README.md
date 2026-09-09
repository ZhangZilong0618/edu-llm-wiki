# edu-llm-wiki

> **v3 — PhD-thesis-grade learning graph.**
>
> AI 驱动的教育知识库系统，把"看完维基百科 + 做几道题"变成"知道自己现在到底懂不懂、还差什么、下一步该干什么"。
> RAG Wiki 后端 + LLM 驱动的知识图谱 + 一整套有教育学理论支撑的学习状态机。

---

## 目录

- [这是什么](#这是什么)
- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [教育学理论支柱](#教育学理论支柱)
- [数据流](#数据流)
- [API 速查](#api-速查)
- [前端组件](#前端组件)
- [本地开发](#本地开发)
- [测试](#测试)
- [风险登记](#风险登记)
- [参考文献](#参考文献)

---

## 这是什么

`edu-llm-wiki` 是一个面向**学习**的维基系统，目标用户是教材作者、教师、自学者。

核心思路：

1. **写 markdown 笔记**（wiki 页面）
2. **后端在每条页面落地时调用 LLM** 抽取出*概念 / 关系 / 父子层级 / Bloom 层级 / 难度*，存进 SQLite 知识图谱
3. **用户在聊天/测试/复习里产生行为**，每一题、每一次暴露、每一条自评都被 BKT + SM-2 + 错因模型记录
4. **前端把这一切画出来**：可视化图谱、8 维学习画像、SM-2 复习队列、6 类教学信号

v3 的关键变化：**学习模型从 FSM 升级到 BKT**，每条教学信号都能引到具体的认知科学文献。

---

## 快速开始

```bash
# 后端
cd edu-llm-wiki/backend
pip install -r requirements.txt
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000

# 前端（新 shell）
cd edu-llm-wiki/frontend
npm install
npm run dev
```

打开 http://localhost:5173/ ，后端在 http://127.0.0.1:8000/docs。

依赖（v3 起新增）：

```bash
pip install pytest      # 跑学习理论单测
```

---

## 系统架构

```
┌────────────────────────────────────────────────────────┐
│                 Frontend (Vite + React)                │
│  graph-view / learning-panel / review-session / ...    │
└────────────────────────────────────────────────────────┘
                          │ REST + SSE
┌────────────────────────────────────────────────────────┐
│                    FastAPI 后端                         │
│                                                        │
│  routes/  ─► services/  ─►  storage/ + graph_store     │
│  ── chat / tests / ingest / projects / graph / ...     │
│                                                        │
│  services/learning/   纯函数:BKT / SM-2 / Error / ...  │
│  services/mastery.py  IO + 8 维画像计算                 │
│  services/graph_engine/  parsers / scoring /            │
│                          communities / insights / paths│
└────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼────────────────┐
        │                 │                │
   wiki .md  ───►  ingest  ───►  graph.sqlite (per project)
   chat  ─────►  search_engine
   tests  ─────►  mastery BKT
   review  ────►  SM-2 scheduler
```

### 材料科学领域图谱流水线

`backend/services/materials_graph.py` 提供一条面向材料科学教学的四阶段领域图谱抽取流程：

1. **Course profile**：识别课程、主题、章节、先修课程与核心能力；
2. **Knowledge atoms**：抽取 `material / composition / processing / structure / property / mechanism / instrument / algorithm / descriptor / dataset / failure_mode / case / safety_rule` 等领域节点；
3. **Typed relations**：抽取 `composition → processing → structure → property → performance → failure → diagnosis` 以及 `measured_by / characterized_by / modeled_by / predicted_by` 等领域边；
4. **Pedagogical attributes**：为每个节点补充难度、Bloom 层级、前置知识、常见误解、学习目标、预计学习时长和跨课程关联。

该流水线通过 DeepSeek/OpenAI-compatible API 调用 `deepseek-v4-flash`，并暴露两个端点：

- `POST /api/materials-graph/extract`：从原始课程文本抽取领域图谱；
- `POST /api/materials-graph/from-page`：从已有 Wiki 页面抽取领域图谱。

相关单测位于 `backend/tests/materials_graph/`，覆盖本体归一化、四阶段编排、无效边过滤和 JSON 修复重试。

### 后端目录树

```
backend/
├── main.py                  FastAPI 入口
├── config.py                路径 / 项目 / LLM 客户端配置
├── models/                  Pydantic 模型
├── routes/                  HTTP 端点（chat / tests / ingest / graph / projects / conversations / exercises / tests）
├── services/
│   ├── graph_engine/        图谱引擎包(parsers / scoring / communities / insights / paths / events)
│   ├── learning/            BKT / SM-2 / 错因 / 迁移 — 纯函数 + 单测
│   ├── mastery.py           FSM + 8 维画像 + BKT/SR/Error 三 observer
│   ├── search_engine.py     RAG 检索 + 图谱扩散 + exposure 上报
│   ├── ingest_engine.py     LLM 抽取 → 入库
│   ├── llm_client.py        统一 LLM 调用
│   ├── graph_store.py       每项目 graph.sqlite (7 张 v3 表)
│   └── ...
├── storage/                 文件级存储（wiki 页面、测试会话等）
└── tests/learning/          14 个认知科学原语单测
```

### 数据模型

**v3 在 v2 基础上新增 7 张表**（`graph_store.py`）：

| 表 | 用途 | 字段 |
|---|---|---|
| `bkt_params` | 每用户每 KC 的 BKT 4 参后验 | p_known, p_t, p_g, p_s |
| `sr_schedule` | SM-2 复习队列 | ease_factor, interval, reps, due_at |
| `misconception_taxonomy` | 错因标签字典 | tag, description |
| `misconception_traces` | 每次错答记录 | (ts, kc_id, tag) |
| `attempts_raw` | 行级答题流 | (ts, kc_id, correct, latency) |
| `confidence_log` | 自评信心 1-5 | (ts, kc_id, confidence, correct) |
| `learning_state` | 8 维画像快照 | p_known_avg, decay_risk, ... |

---

## 教育学理论支柱

**每个原语都在文件 docstring 里 cite 了来源**。

| 模块 | 算法 | 文献 |
|---|---|---|
| `services/learning/bkt.py` | 4-参贝叶斯知识追踪 | Corb & Sandberg (1992) *Knowledge tracing and modeling the student* |
| `services/learning/spaced_repetition.py` | SM-2 改进 + 1h floor | Wozniak (1985) *Optimization of repetition spacing* |
| `services/learning/error_model.py` | 关键词错因分类 | Brown & Burton (1978) *Diagnostic models for procedural bugs* |
| `services/learning/transfer.py` | paired t-test + scipy fallback | Perkins & Salomon (1989) *Are cognitive skills context-bound?* |
| `services/mastery.py:learner_state_summary` | overconfidence_gap | Karpicke & Roediger (2008) *The critical importance of retrieval for learning* |
| `services/mastery.py:readiness` | prereq ≥ 0.85 | Vygotsky (1978) *Mind in Society* (ZPD) |
| `services/graph_engine/insights.py:generate_learner_insights` | 6 类教学信号 + min_score=1.5 过滤 | 综合 Bloom (1956) / VanLehn (1996) / Koedinger (2015) |

### BKT 4 参默认

- P(L₀) = 0.10（学习前掌握概率）
- P(T)  = 0.20（每次学习后的迁移概率）
- P(G)  = 0.20（不会却答对的猜中率）
- P(S)  = 0.10（会却答错的失误率）

与 Yudelson (2013) 的标定经验一致。

### 6 类教学信号

| insight_type | 触发条件 | 教学意义 |
|---|---|---|
| `frontier` | 节点 prereq 全绿、自身未打开 | 推进到 Vygotsky ZPD 的"最近发展区" |
| `stale` | 节点 mtime 变化、用户 last_seen 旧 | Ebbinghaus 遗忘曲线提醒复习 |
| `misconception_cluster` | 同 tag ≥ 3 次 | Brown & Burton 的错误诊断 |
| `readiness` | prereq 整体 p_known < 0.5 | ZPD 尚未到达 |
| `transfer_window` | A > 0.85, B < 0.3, A→B 边 | Perkins & Salomon 迁移机会 |
| `overconfidence` | 连续 3 次 confidence − correctness > 0.2 | Karpicke & Roediger 校准偏差 |

### 8 维学习画像 (`learner_state_summary`)

```json
{
  "p_known_avg": 0.72,
  "weak_kcs": [{"kc_id": "..."}],
  "misconception_clusters": [{"tag": "off_by_one", "count": 4}],
  "transfer_windows": [{"from": "a", "to": "b"}],
  "overconfidence_gap": 0.13,
  "readiness": 0.83,
  "sr_due_today": ["kc_x", "kc_y"],
  "decay_risk": 0.27,
  "n_kcs_tracked": 47
}
```

---

## 数据流

### 1. Wiki 录入
```
.md 文件
  → storage/wiki_store 读取
  → ingest_engine.ingest_page
  → LLM 抽 concept / relationship / parent / bloom / difficulty
  → services.mastery + services.graph_store 落库
```

### 2. 用户答题
```
POST /api/tests/.../submit
  → 对每题拆 KC (question.concepts[])
  → 写 bkt_params.update (BKT observe)
  → 写 sr_schedule.update (SM-2)
  → 写 misconception_traces (error_model.classify)
  → 写 confidence_log
  → 写 node_mastery (FSM 审计)
  → publish "state_changed" 事件 (SSE)
```

### 3. 复习
```
GET /api/learning/schedule
  → SR 队列, due_at <= now
POST /api/learning/review
  → 与 submit_test 同样的 observer 链
```

### 4. RAG 检索
```
chat / search
  → embedding + bm25 hybrid
  → graph_expand (BFS 邻接, 1-2 跳)
  → 每次"读到"都 call mastery.record_exposure
  → 拼上下文给 LLM
```

---

## API 速查

### 知识图谱
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/graph` | 全图（节点 + 边 + 社区 + 结构 insight） |
| GET | `/api/graph/neighborhood/{node_id}` | 邻域子图 |
| GET | `/api/graph/insights` | v2 结构信号 |
| GET | `/api/graph/learning/path?target=X` | 学习路径（沿 prereq 边反向） |
| GET | `/api/graph/events` | SSE 事件流 |

### 学习（v3）
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/graph/learning/state?user_id=` | 8 维画像 |
| GET | `/api/graph/learning/schedule?user_id=&limit=` | SM-2 复习队列 |
| GET | `/api/graph/learning/insights?user_id=` | 6 类教学信号 |
| POST | `/api/graph/learning/review` | 提交复习答卷 |
| POST | `/api/graph/mastery/{id}/attempt` | 记录一次 attempt |
| POST | `/api/graph/mastery/{id}/exposure` | 记录一次 exposure |

### Wiki / Ingest
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/wiki/pages` | 列出所有 wiki 页面 |
| GET | `/api/wiki/page?path=` | 读单页 |
| POST | `/api/ingest` | 把一段文本走 LLM 抽取并入库 |

### 聊天 / 测试
| Method | Path | 说明 |
|---|---|---|
| POST | `/api/chat/...` | RAG 聊天 |
| POST | `/api/tests` | 创建测试 |
| POST | `/api/tests/{id}/submit` | 提交测试,触发 BKT/SR/Error 写入 |

---

## 前端组件

```
frontend/src/components/
├── graph/                       知识图谱视图 (v2 拆 7 模块)
│   ├── graph-view.tsx           orchestrator
│   ├── graph-canvas.tsx         Sigma + graphology 渲染
│   ├── graph-filter-panel.tsx   类型过滤 / 弱链 / 搜索
│   ├── graph-mastery-badge.tsx  节点 mastery chip
│   ├── use-graph-data.ts        graph + mastery 拉取
│   ├── use-graph-events.ts      SSE 订阅
│   ├── constants.ts / utils.ts  常量 + 纯函数
├── learning/                    v3 学习面板
│   ├── learn-view.tsx           学习总览页
│   ├── learning-panel.tsx       8 维画像 + 信号流
│   ├── review-session.tsx       SR 复习小测
│   ├── confidence-slider.tsx    1-5 信心滑杆
│   └── posterior-bar.tsx        BKT p_known 可视化
├── tests/                       测试模块
├── layout/                      布局
└── ...
```

---

## 本地开发

### 路径配置
默认数据在 `edu-llm-wiki/data/projects/<project_id>/`，配置在 `backend/config.py` 的 `settings`：
- `projects_dir` — 维基 + 测试 + graph.sqlite
- `wiki_dir_template` — `{projects_dir}/{project_id}/wiki/`
- `test_dir_template` — `{projects_dir}/{project_id}/tests/`

### LLM 配置
`backend/config.py` 的 `llm` 段：
- 默认走 OpenAI 兼容协议（`openai/gpt-4o-mini` 或同价模型）
- 重抽取图谱和测试生成可以选用更强模型（`openai/gpt-4o`）
- 通过环境变量 `EDU_LLM_API_KEY`、`EDU_LLM_BASE_URL` 覆盖

### 第一次启动
```bash
# 1) 启动后端
cd edu-llm-wiki/backend && python3 -m uvicorn main:app --host 127.0.0.1 --port 8000

# 2) 启动前端
cd edu-llm-wiki/frontend && npm run dev

# 3) 在 UI 上传 1 份 markdown（v3 支持直接拖入 .md），后端会触发 ingest
# 4) 打开图谱页 / 学习页看效果
```

### 调整 BKT 参数
`backend/services/learning/bkt.py:default_params()` —— 修改 default 之后在 learner_state_summary 会被使用。

---

## 测试

```bash
cd edu-llm-wiki/backend
python3 -m pytest tests/learning -q     # 14/14 pass
```

- `test_bkt.py` — 4 参观察 + MLE 拟合 + 不变量
- `test_sr.py` — SM-2 5/0/4 三种质量的 EF / interval 变化
- `test_error_model.py` — 同义错答 / 完全错 / 空答
- `test_transfer.py` — paired t-test + window 找出 unmastered neighbour

每条测试都对应一条文献 invariant，不是为了覆盖率凑数。

---

## 风险登记（必须承认的工程局限）

| 编号 | 等级 | 内容 | 状态 |
|---|---|---|---|
| R1 | 高 | `graph_store.py` 末尾 v2 实施时曾有重复定义 | v3 修复 |
| R2 | 中 | `overconfidence_gap` 在 confidence 滑杆未上线时恒为 0 | 滑杆已实装 |
| R3 | 中 | `transfer.py` scipy 缺则 fallback 到 `statistics.stdev` | 已处理 |
| R4 | 中 | SM-2 quality=0 时 interval 复位 → 新人 1 小时内反复触发 | 已加 1h floor |
| R5 | 中 | LLM 短答评分漏提 misconception tag | Phase E 修 |
| R6 | 中 | 迁移脚本必须在 schema v2 之后跑 | CLI 前置检查 |
| R7 | 低 | 小图谱下 learner_insights 易噪音 | min_score=1.5 过滤 |
| R8 | 低 | v1 `graph_mastery` 与 v2 `node_mastery` 共存 | 保持不动（回滚用）|
| R9 | 低 | `TestAttempt.confidence` 默认 `None` | 兼容老 API |

---

## 路线图

- **v3.x** — PyTorch IRT 全项目校准,补 attack 全平台
- **v4**   — DKT 神经网络知识追踪（需要训练数据）
- **v4.1** — 真实 SIR 个体化推荐
- **v5**   — 多用户 cohort 分析 / 班级视图

---

## 参考文献

- Corbett, A. T. & Sandberg, A. C. (1992). *Knowledge tracing and modeling the student.* In the *Handbook of Intelligent Tutoring Systems*.
- Vygotsky, L. S. (1978). *Mind in Society.*
- Karpicke, J. D. & Roediger, H. L. (2008). *The critical importance of retrieval for learning.* Science.
- Ebbinghaus, H. (1885). *Über das Gedächtnis.*
- Brown, J. S. & Burton, R. R. (1978). *Diagnostic models for procedural bugs.* Cognitive Science.
- Wozniak, P. (1985). *Optimization of repetition spacing in the practice of learning.* Acta Neurobiologiae Experimentalis.
- Perkins, D. N. & Salomon, G. (1989). *Are cognitive skills context-bound?* Educational Researcher.
- Yudelson, M. V. et al. (2013). *Individualized Bayesian knowledge tracing models.* AIED.
- Bloom, B. S. (1956). *Taxonomy of Educational Objectives.*
- VanLehn, K. (1996). *Student modeling.* Foundations of Intelligent Tutoring Systems.
- Koedinger, K. R. et al. (2015). *A Computational Account of How Learning Transfer Arises from Practice.*

---

## License

MIT
