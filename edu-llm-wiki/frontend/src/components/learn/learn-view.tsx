/**
 * 学习路径视图(重设计)——拓扑分层 + BKT 掌握度。
 *
 * 左栏 PathBoard:Kahn 分层轨道,每层一排并列知识点卡片;
 * 右栏 PointDetail:页面内容 + 出题练习(材料 = 本点 + 直接先修),
 * 做题走现有 tests 管线,判分后 BKT 更新,只刷新该点状态。
 *
 * 路径 = f(图,掌握度) 纯函数(后端 services/learning/path.py):
 * 本体 prerequisiteOf 优先、启发式 prerequisite 增量入图,
 * 方向冲突进观察区(edge_conflicts)。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronRight,
  Circle,
  GitFork,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { api, type LearningPathData, type LearningPathNode, type TestSession } from "@/lib/api";
import { useUserStore } from "@/stores/user-store";
import { PAGE_TYPE_CONFIG, type PageType } from "@/lib/page-type";
import { Markdown } from "@/components/markdown";
import { toast } from "@/components/ui/toast";
import type { WikiPage } from "@/types/wiki";

/** 每次出题的题量(拍板:3–5 取 5)。 */
const QUESTION_COUNT = 5;

type Status = LearningPathNode["status"];

function typeColor(nodeType: string): string {
  return PAGE_TYPE_CONFIG[nodeType as PageType]?.hex || "#9ca3af";
}

function typeLabel(nodeType: string): string {
  return PAGE_TYPE_CONFIG[nodeType as PageType]?.label || nodeType;
}

/** 掌握度环(SVG)。compact = 树形行的迷你环。 */
function MasteryRing({ value, status, compact = false }: { value: number; status: Status; compact?: boolean }) {
  const pct = Math.max(0, Math.min(1, value));
  const color =
    status === "mastered" ? "#16a34a" : status === "ready" ? "#2563eb" : status === "upcoming" ? "#94a3b8" : "#d97706";
  const size = compact ? 22 : 38;
  const r = compact ? 8 : 15;
  const c = 2 * Math.PI * r;
  const stroke = compact ? 3 : 4;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeDasharray={`${(c * pct).toFixed(1)} ${c.toFixed(1)}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray 0.5s ease" }}
      />
      {!compact && (
        <text x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central" fontSize={9} fill="#475569">
          {status === "mastered" ? "✓" : `${Math.round(pct * 100)}`}
        </text>
      )}
    </svg>
  );
}

// ---- n 叉树图形布局 ----
// 顶行 = 全部树根(无先修 = 最先学),子节点向下扇出;
// 叶子按列排布,父节点居中于子节点之上(简化 tidy-tree)。
const NODE_W = 150;
const NODE_H = 46;
const COL_GAP = 26;
const ROW_GAP = 74;
const CANVAS_PAD = 24;

interface LaidNode {
  node: LearningPathNode;
  x: number; // 左上角
  y: number;
  depth: number;
}

interface TreeLayout {
  nodes: LaidNode[];
  edges: { from: LaidNode; to: LaidNode }[];
  width: number;
  height: number;
  focusPos: { x: number; y: number } | null;
}

function subtreeSize(node: LearningPathNode): number {
  return 1 + (node.children ?? []).reduce((sum, c) => sum + subtreeSize(c), 0);
}

function containsId(node: LearningPathNode, id: string): boolean {
  if (node.id === id) return true;
  return (node.children ?? []).some((c) => containsId(c, id));
}

function layoutForest(
  roots: LearningPathNode[],
  collapsed: Set<string>,
  focusId: string | null,
): TreeLayout {
  const COL_W = NODE_W + COL_GAP;
  const ROW_H = NODE_H + ROW_GAP;
  // 根排序:含焦点的树最左(先看到),其次子树大的主干在前
  const ordered = [...roots].sort((a, b) => {
    const fa = focusId ? (containsId(a, focusId) ? 0 : 1) : 1;
    const fb = focusId ? (containsId(b, focusId) ? 0 : 1) : 1;
    if (fa !== fb) return fa - fb;
    return subtreeSize(b) - subtreeSize(a) || a.label.localeCompare(b.label, "zh-Hans-CN");
  });

  const nodes: LaidNode[] = [];
  const edges: { from: LaidNode; to: LaidNode }[] = [];
  let col = 0;
  let maxDepth = 0;
  let focusPos: { x: number; y: number } | null = null;

  const place = (node: LearningPathNode, depth: number): number => {
    maxDepth = Math.max(maxDepth, depth);
    const kids = collapsed.has(node.id) ? [] : node.children ?? [];
    let x: number;
    if (kids.length === 0) {
      x = col * COL_W;
      col += 1;
    } else {
      const childXs = kids.map((k) => place(k, depth + 1));
      x = (Math.min(...childXs) + Math.max(...childXs)) / 2;
    }
    const laid: LaidNode = { node, x, y: depth * ROW_H, depth };
    nodes.push(laid);
    if (node.id === focusId) focusPos = { x, y: depth * ROW_H };
    kids.forEach((k, i) => {
      const child = nodes.find((n) => n.node.id === k.id);
      if (child) edges.push({ from: laid, to: child });
    });
    return x;
  };
  ordered.forEach((r) => place(r, 0));

  return {
    nodes,
    edges,
    width: Math.max(col, 1) * COL_W - COL_GAP + CANVAS_PAD * 2,
    height: (maxDepth + 1) * ROW_H - ROW_GAP + NODE_H + CANVAS_PAD * 2,
    focusPos,
  };
}

/** 肘形连线:父底中 → 垂直 → 水平 → 子顶中。 */
function edgePath(from: LaidNode, to: LaidNode): string {
  const x1 = from.x + NODE_W / 2 + CANVAS_PAD;
  const y1 = from.y + NODE_H + CANVAS_PAD;
  const x2 = to.x + NODE_W / 2 + CANVAS_PAD;
  const y2 = to.y + CANVAS_PAD;
  const midY = (y1 + y2) / 2;
  return `M ${x1} ${y1} V ${midY} H ${x2} V ${y2}`;
}

/** n 叉树图形:顶行=最先学(树根),向下扇出;可折叠分支,点击进详情。 */
function TreeDiagram({
  path,
  selectedId,
  collapsed,
  onToggle,
  onSelect,
}: {
  path: LearningPathData;
  selectedId: string | null;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const layout = useMemo(
    () => layoutForest(path.tree, collapsed, path.focus_id),
    [path.tree, collapsed, path.focus_id],
  );

  // 布局/焦点变化时滚到焦点附近
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !layout.focusPos) return;
    el.scrollTo({
      left: Math.max(0, layout.focusPos.x + CANVAS_PAD - el.clientWidth / 2 + NODE_W / 2),
      top: Math.max(0, layout.focusPos.y + CANVAS_PAD - el.clientHeight / 2),
      behavior: "smooth",
    });
  }, [layout]);

  return (
    <div ref={containerRef} className="min-h-0 flex-1 overflow-auto">
      <div className="relative" style={{ width: layout.width, height: layout.height }}>
        <svg
          className="pointer-events-none absolute inset-0"
          width={layout.width}
          height={layout.height}
        >
          {layout.edges.map((e, i) => {
            const highlighted = e.to.node.id === selectedId || e.from.node.id === selectedId;
            return (
              <path
                key={i}
                d={edgePath(e.from, e.to)}
                fill="none"
                stroke={highlighted ? "#2563eb" : "#cbd5e1"}
                strokeWidth={highlighted ? 2 : 1.4}
              />
            );
          })}
        </svg>
        {layout.nodes.map(({ node, x, y, depth }) => {
          const hasChildren = (node.children?.length ?? 0) > 0;
          const isCollapsed = collapsed.has(node.id);
          const focus = node.id === path.focus_id;
          const selected = node.id === selectedId;
          const dim = node.status === "upcoming";
          const extra = node.extra_prereq_labels ?? [];
          return (
            <div key={node.id} className="absolute" style={{ left: x + CANVAS_PAD, top: y + CANVAS_PAD }}>
              {focus && (
                <span className="absolute -top-4 left-0 whitespace-nowrap rounded bg-[var(--primary)] px-1.5 text-[9px] text-[var(--primary-foreground)]">
                  从这里开始
                </span>
              )}
              <button
                onClick={() => onSelect(node.id)}
                className={`flex items-center gap-1.5 rounded-lg border px-2 text-left transition
                  ${selected ? "border-[var(--primary)] ring-1 ring-[var(--primary)]/40" : "border-[var(--border)] hover:border-[var(--primary)]/60"}
                  ${focus ? "shadow-[0_0_0_3px_var(--primary)]/20" : ""}
                  ${dim ? "opacity-75" : ""}`}
                style={{ width: NODE_W, height: NODE_H }}
                title={`${typeLabel(node.node_type)}${node.level ? ` · 第 ${node.level} 阶` : ""} · 先修 ${node.prereq_labels.length} · 被依赖 ${node.dependents_count}${
                  node.prereq_labels.length ? `\n先修: ${node.prereq_labels.join("、")}` : ""
                }${extra.length ? `\n父分支外还需: ${extra.join("、")}` : ""}`}
              >
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: typeColor(node.node_type) }}
                  aria-hidden
                />
                <span className={`min-w-0 flex-1 truncate text-[11px] font-medium ${node.status === "mastered" ? "text-green-600" : ""}`}>
                  {node.status === "mastered" ? "✓ " : ""}
                  {node.label}
                </span>
                {hasChildren && (
                  <span
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onToggle(node.id);
                    }}
                    className="flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    role="button"
                    aria-label={isCollapsed ? "展开分支" : "折叠分支"}
                  >
                    <ChevronRight
                      size={12}
                      className={`transition-transform ${isCollapsed ? "-rotate-90" : "rotate-90"}`}
                    />
                  </span>
                )}
                <MasteryRing value={node.p_known ?? 0} status={node.status} compact />
              </button>
              {isCollapsed && hasChildren && (
                <span className="absolute -bottom-3.5 right-1 rounded-full bg-[var(--muted)] px-1.5 text-[9px] text-[var(--muted-foreground)]">
                  +{(node.children ?? []).length}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 出题练习面板:生成 → 作答 → 提交 → 判分反馈。 */
function ExercisePanel({
  node,
  learner,
  onFinished,
}: {
  node: LearningPathNode;
  learner: string;
  onFinished: () => void;
}) {
  const [session, setSession] = useState<TestSession | null>(null);
  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const generate = async () => {
    setGenerating(true);
    setSession(null);
    setAnswers({});
    try {
      const s = await api.createTest({
        scope: "wiki",
        source: null,
        question_count: QUESTION_COUNT,
        question_types: ["multiple_choice", "fill_blank", "short_answer"],
        difficulty: "mixed",
        mode: "practice",
        node_id: node.id,
        seed: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      });
      if (!s.questions?.length) {
        toast({ type: "error", message: "生成失败:没有可用题目" });
        return;
      }
      setSession(s);
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "出题失败" });
    } finally {
      setGenerating(false);
    }
  };

  const submit = async () => {
    if (!session) return;
    setSubmitting(true);
    try {
      const result = await api.submitTest(session.id, answers, {}, learner);
      setSession(result);
      onFinished();
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "提交失败" });
    } finally {
      setSubmitting(false);
    }
  };

  const submitted = session?.status === "submitted";
  const attempts = session?.attempts || [];

  return (
    <div className="rounded-lg border bg-[var(--muted)]/30 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold">
          <Sparkles size={13} className="text-[var(--primary)]" />
          出题练习
          <span className="font-normal text-[var(--muted-foreground)]">
            (材料 = 本点 + 直接先修 {node.prereq_labels.length} 篇)
          </span>
        </div>
        <button
          onClick={generate}
          disabled={generating}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--primary)]/40 bg-[var(--primary)]/5 px-2.5 py-1 text-xs text-[var(--primary)] hover:bg-[var(--primary)]/10 disabled:opacity-50"
        >
          {generating ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {session ? "重新出题" : `生成 ${QUESTION_COUNT} 题`}
        </button>
      </div>

      {!session && !generating && (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          题目围绕《{node.label}》命制,先修点材料用于理解背景。答对会推高 BKT 掌握度(阈值 85%)。
        </p>
      )}

      {session?.questions.map((q, qi) => {
        const attempt = attempts.find((a) => a.question_id === q.id);
        const correct = attempt ? attempt.score >= attempt.max_score * 0.999 : null;
        return (
          <div key={q.id} className="mb-3 rounded-md border bg-[var(--background)] p-2.5">
            <p className="mb-2 text-xs font-medium">
              {qi + 1}. {q.prompt}
              {attempt && (
                <span className={`ml-1.5 ${correct ? "text-green-600" : "text-red-600"}`}>
                  {correct ? "✓" : "✗"}
                </span>
              )}
            </p>
            {q.type === "multiple_choice" ? (
              <div className="space-y-1">
                {q.options.map((opt, oi) => {
                  const picked = answers[q.id] === opt;
                  return (
                    <label key={oi} className="flex cursor-pointer items-start gap-1.5 text-xs">
                      <input
                        type="radio"
                        name={q.id}
                        checked={picked}
                        disabled={submitted}
                        onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: opt }))}
                        className="mt-0.5"
                      />
                      <span>{opt}</span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <textarea
                value={answers[q.id] || ""}
                disabled={submitted}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                placeholder="作答…"
                className="w-full rounded border bg-transparent px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                rows={2}
              />
            )}
            {attempt && (
              <div className="mt-1.5 border-t pt-1.5 text-[11px] text-[var(--muted-foreground)]">
                <span className="font-medium">答案:</span> {Array.isArray(attempt.correct_answer) ? attempt.correct_answer.join(" / ") : attempt.correct_answer}
                {attempt.feedback ? <span className="ml-2">{attempt.feedback}</span> : null}
              </div>
            )}
          </div>
        );
      })}

      {session && !submitted && (
        <button
          onClick={submit}
          disabled={submitting || Object.keys(answers).length < session.questions.length}
          className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          提交({Object.keys(answers).length}/{session.questions.length})
        </button>
      )}

      {submitted && session && (
        <div className="flex items-center justify-between gap-2 border-t pt-2 text-xs">
          <span>
            得分 {session.score}/{session.max_score} · BKT 已更新
          </span>
          <button onClick={generate} className="text-[var(--primary)] hover:underline">
            再练一轮
          </button>
        </div>
      )}
    </div>
  );
}

/** 点详情右栏。 */
function PointDetail({
  node,
  learner,
  onExerciseFinished,
}: {
  node: LearningPathNode;
  learner: string;
  onExerciseFinished: () => void;
}) {
  const [page, setPage] = useState<WikiPage | null>(null);
  const [loadingPage, setLoadingPage] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPage(null);
    if (!node.page_path) return;
    setLoadingPage(true);
    api
      .getPage(node.page_path)
      .then((p) => {
        if (!cancelled) setPage(p);
      })
      .catch(() => {
        if (!cancelled) setPage(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingPage(false);
      });
    return () => {
      cancelled = true;
    };
  }, [node.id, node.page_path]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <div className="rounded-lg border p-3">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: typeColor(node.node_type) }} />
          <h3 className="text-sm font-semibold">{node.label}</h3>
          <span className="ml-auto text-[10px] text-[var(--muted-foreground)]">
            {typeLabel(node.node_type)}
            {node.level ? ` · 第 ${node.level} 阶` : " · 未定序"}
          </span>
        </div>
        <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
          先修 {node.prereq_labels.length}
          {node.prereq_labels.length > 0 && `(${node.prereq_labels.join("、")})`} · 被依赖 {node.dependents_count} ·
          BKT 掌握 {node.p_known === null ? "未学" : `${Math.round(node.p_known * 100)}%`}
        </div>
      </div>

      {node.page_path && (
        <div className="rounded-lg border p-3">
          <div className="mb-2 flex items-center gap-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
            <BookOpen size={11} /> 页面内容
          </div>
          {loadingPage ? (
            <Loader2 size={14} className="animate-spin text-[var(--muted-foreground)]" />
          ) : page ? (
            <Markdown>{page.content || "*无内容*"}</Markdown>
          ) : (
            <p className="text-[11px] text-[var(--muted-foreground)]">页面加载失败</p>
          )}
        </div>
      )}

      <ExercisePanel node={node} learner={learner} onFinished={onExerciseFinished} />
    </div>
  );
}

export function LearnView() {
  const learner = useUserStore((s) => s.userId);
  const [path, setPath] = useState<LearningPathData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showConflicts, setShowConflicts] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const loadPath = useCallback(
    (keepSelection: boolean) => {
      setLoading(true);
      api
        .getLearningPath(learner)
        .then((data) => {
          setPath(data);
          setError(null);
          setSelectedId((current) => {
            if (keepSelection && current) return current;
            return data.focus_id || data.levels[0]?.nodes[0]?.id || null;
          });
        })
        .catch((e: any) => setError(e?.message || "加载学习路径失败"))
        .finally(() => setLoading(false));
    },
    [learner],
  );

  useEffect(() => {
    setSelectedId(null);
    loadPath(false);
  }, [loadPath]);

  const selected = useMemo(() => {
    if (!path || !selectedId) return null;
    const find = (nodes: LearningPathNode[]): LearningPathNode | null => {
      for (const n of nodes) {
        if (n.id === selectedId) return n;
        const hit = find(n.children ?? []);
        if (hit) return hit;
      }
      return null;
    };
    return (
      find(path.tree) || path.unresolved.find((n) => n.id === selectedId) || null
    );
  }, [path, selectedId]);

  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const progressPct = path && path.progress.total > 0
    ? Math.round((path.progress.mastered / path.progress.total) * 100)
    : 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 头部:进度条 + 当前层 */}
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <GitFork size={14} className="text-[var(--primary)]" /> 学习路径
        </h2>
        {path && (
          <>
            <div className="flex min-w-[160px] flex-1 items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--muted)]">
                <div
                  className="h-full rounded-full bg-green-500 transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                {path.progress.mastered}/{path.progress.total} 已掌握 · 当前第 {path.progress.current_level} 阶
              </span>
            </div>
            <span className="text-[11px] text-[var(--muted-foreground)]">学习者: {learner}</span>
          </>
        )}
        <button
          onClick={() => loadPath(true)}
          disabled={loading}
          className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-[var(--accent)] disabled:opacity-50"
          title="重新计算路径(图或掌握度更新后)"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> 刷新
        </button>
      </div>

      {error && (
        <div className="border-b bg-red-50 px-4 py-2 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {loading && !path ? (
        <div className="flex flex-1 items-center justify-center text-sm text-[var(--muted-foreground)]">
          <Loader2 size={16} className="mr-2 animate-spin" /> 正在计算学习路径…
        </div>
      ) : !path || path.progress.total === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
          <Circle size={28} className="opacity-30" />
          <p>当前项目还没有知识图谱——先到 Import 导入文档。</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* 左栏:n 叉树图形(顶行=最先学的树根,向下=学习推进) */}
          <div className="min-h-0 flex-1 p-1">
            <TreeDiagram
              path={path}
              selectedId={selectedId}
              collapsed={collapsed}
              onToggle={toggle}
              onSelect={setSelectedId}
            />

              {/* 观察区:环点 + 边冲突 */}
              {(path.unresolved.length > 0 || path.edge_conflicts.length > 0) && (
                <section className="rounded-lg border border-dashed p-3">
                  <button
                    className="flex w-full items-center gap-1.5 text-xs font-medium text-[var(--muted-foreground)]"
                    onClick={() => setShowConflicts((v) => !v)}
                  >
                    <AlertTriangle size={13} className="text-amber-500" />
                    观察区:未定序 {path.unresolved.length} 点 · 边冲突 {path.edge_conflicts.length} 条
                    <span className="ml-auto">{showConflicts ? "收起" : "展开"}</span>
                  </button>
                  {showConflicts && (
                    <div className="mt-2 space-y-2 text-[11px]">
                      {path.unresolved.map((n) => (
                        <div key={n.id} className="rounded border p-1.5">
                          <button className="font-medium hover:underline" onClick={() => setSelectedId(n.id)}>
                            {n.label}
                          </button>
                          {(n.cycle_edges || []).map((ce, i) => (
                            <span key={i} className="ml-2 text-[var(--muted-foreground)]">
                              {ce.source} → {ce.target}
                            </span>
                          ))}
                        </div>
                      ))}
                      {path.edge_conflicts.map((c, i) => (
                        <div key={i} className="text-[var(--muted-foreground)]">
                          <span className="text-amber-600">冲突边:</span> {c.source} → {c.target}({c.note})
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}
          </div>

          {/* 右栏:点详情 */}
          <aside className="min-h-0 w-[42%] border-l">
            {selected ? (
              <PointDetail
                key={selected.id}
                node={selected}
                learner={learner}
                onExerciseFinished={() => loadPath(true)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">
                点击左侧知识点查看详情与出题
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
