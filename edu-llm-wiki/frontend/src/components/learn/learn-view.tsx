/**
 * 学习路径视图(重设计)——拓扑分层 + BKT 掌握度。
 *
 * 主体:n 叉树图形(每棵树顶=树根=最先学,森林垂直堆叠,深度≥2
 * 默认折叠)。点击节点 → 页面打开到全局预览面板(Select a page to
 * preview 区域);出题练习走右滑抽屉(材料 = 本点 + 直接先修),
 * 判分后 BKT 更新并刷新路径。
 *
 * 路径 = f(图,掌握度) 纯函数(后端 services/learning/path.py):
 * 本体 prerequisiteOf 优先、启发式 prerequisite 增量入图,
 * 方向冲突进观察区(edge_conflicts)。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Circle,
  GitFork,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";

import { api, type LearningPathData, type LearningPathNode, type TestSession } from "@/lib/api";
import { useUserStore } from "@/stores/user-store";
import { useAppStore } from "@/stores/app-store";
import { PAGE_TYPE_CONFIG, type PageType } from "@/lib/page-type";
import { toast } from "@/components/ui/toast";

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
// 森林垂直堆叠:每棵树顶行=树根(无先修 = 最先学),子节点向下扇出,
// 树与树自上而下依次排列;宽度=各树自身叶子列宽(不再整片平铺一行)。
// 深度≥2 的分支默认折叠(+N 徽标),expanded/collapsed 双集合覆盖默认。
const NODE_W = 150;
const NODE_H = 46;
const COL_GAP = 26;
const ROW_GAP = 74;
const TREE_GAP = 64;
const CANVAS_PAD = 24;
/** 深度达到该值起默认折叠分支。 */
const DEFAULT_COLLAPSE_DEPTH = 2;

interface LaidNode {
  node: LearningPathNode;
  x: number; // 画布坐标(含内边距)
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

/** 分支是否隐藏:显式折叠,或深度≥2 且未显式展开。 */
function branchHidden(id: string, depth: number, collapsed: Set<string>, expanded: Set<string>): boolean {
  if (collapsed.has(id)) return true;
  return depth >= DEFAULT_COLLAPSE_DEPTH && !expanded.has(id);
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
  expanded: Set<string>,
  focusId: string | null,
): TreeLayout {
  const COL_W = NODE_W + COL_GAP;
  const ROW_H = NODE_H + ROW_GAP;
  // 树排序:含焦点的树最上(先看到),其次子树大的主干在前
  const ordered = [...roots].sort((a, b) => {
    const fa = focusId ? (containsId(a, focusId) ? 0 : 1) : 1;
    const fb = focusId ? (containsId(b, focusId) ? 0 : 1) : 1;
    if (fa !== fb) return fa - fb;
    return subtreeSize(b) - subtreeSize(a) || a.label.localeCompare(b.label, "zh-Hans-CN");
  });

  const nodes: LaidNode[] = [];
  const edges: { from: LaidNode; to: LaidNode }[] = [];
  let width = CANVAS_PAD * 2;
  let yOff = CANVAS_PAD;
  let focusPos: { x: number; y: number } | null = null;

  for (const root of ordered) {
    let col = 0;
    let treeMaxDepth = 0;
    const treeNodes: LaidNode[] = [];
    const treeEdges: { from: LaidNode; to: LaidNode }[] = [];

    const place = (node: LearningPathNode, depth: number): number => {
      treeMaxDepth = Math.max(treeMaxDepth, depth);
      const kids = branchHidden(node.id, depth, collapsed, expanded)
        ? []
        : node.children ?? [];
      let x: number;
      if (kids.length === 0) {
        x = col * COL_W + CANVAS_PAD;
        col += 1;
      } else {
        const childXs = kids.map((k) => place(k, depth + 1));
        x = (Math.min(...childXs) + Math.max(...childXs)) / 2;
      }
      const laid: LaidNode = { node, x, y: yOff + depth * ROW_H, depth };
      treeNodes.push(laid);
      if (node.id === focusId) focusPos = { x, y: laid.y };
      kids.forEach((k) => {
        const child = treeNodes.find((n) => n.node.id === k.id);
        if (child) treeEdges.push({ from: laid, to: child });
      });
      return x;
    };
    place(root, 0);

    nodes.push(...treeNodes);
    edges.push(...treeEdges);
    width = Math.max(width, Math.max(col, 1) * COL_W - COL_GAP + CANVAS_PAD * 2);
    yOff += (treeMaxDepth + 1) * ROW_H - ROW_GAP + NODE_H + TREE_GAP;
  }

  return {
    nodes,
    edges,
    width,
    height: Math.max(yOff - TREE_GAP + CANVAS_PAD, 1),
    focusPos,
  };
}

/** 肘形连线:父底中 → 垂直 → 水平 → 子顶中(坐标已含画布内边距)。 */
function edgePath(from: LaidNode, to: LaidNode): string {
  const x1 = from.x + NODE_W / 2;
  const y1 = from.y + NODE_H;
  const x2 = to.x + NODE_W / 2;
  const y2 = to.y;
  const midY = (y1 + y2) / 2;
  return `M ${x1} ${y1} V ${midY} H ${x2} V ${y2}`;
}

/** n 叉树图形:每棵树顶=树根(最先学),向下扇出;深度≥2 默认折叠。 */
function TreeDiagram({
  path,
  selectedId,
  collapsed,
  expanded,
  onToggle,
  onSelect,
}: {
  path: LearningPathData;
  selectedId: string | null;
  collapsed: Set<string>;
  expanded: Set<string>;
  onToggle: (id: string, visible: boolean) => void;
  onSelect: (node: LearningPathNode) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const layout = useMemo(
    () => layoutForest(path.tree, collapsed, expanded, path.focus_id),
    [path.tree, collapsed, expanded, path.focus_id],
  );

  // 布局/焦点变化时滚到焦点附近
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !layout.focusPos) return;
    el.scrollTo({
      left: Math.max(0, layout.focusPos.x - el.clientWidth / 2 + NODE_W / 2),
      top: Math.max(0, layout.focusPos.y - el.clientHeight / 3),
      behavior: "smooth",
    });
  }, [layout]);

  return (
    <div ref={containerRef} className="min-h-0 min-w-0 flex-1 overflow-auto">
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
          const hidden = branchHidden(node.id, depth, collapsed, expanded);
          const focus = node.id === path.focus_id;
          const selected = node.id === selectedId;
          const dim = node.status === "upcoming";
          const extra = node.extra_prereq_labels ?? [];
          return (
            <div key={node.id} className="absolute" style={{ left: x, top: y }}>
              {focus && (
                <span className="absolute -top-4 left-0 whitespace-nowrap rounded bg-[var(--primary)] px-1.5 text-[9px] text-[var(--primary-foreground)]">
                  从这里开始
                </span>
              )}
              <button
                onClick={() => onSelect(node)}
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
                      onToggle(node.id, !hidden);
                    }}
                    className="flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    role="button"
                    aria-label={hidden ? "展开分支" : "折叠分支"}
                  >
                    <ChevronRight
                      size={12}
                      className={`transition-transform ${hidden ? "-rotate-90" : "rotate-90"}`}
                    />
                  </span>
                )}
                <MasteryRing value={node.p_known ?? 0} status={node.status} compact />
              </button>
              {hidden && hasChildren && (
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
/** 出题抽屉:右滑覆盖,含节点元信息 + 练习面板。 */
function ExerciseDrawer({
  node,
  learner,
  onClose,
  onExerciseFinished,
}: {
  node: LearningPathNode;
  learner: string;
  onClose: () => void;
  onExerciseFinished: () => void;
}) {
  return (
    <div className="absolute inset-0 z-30 flex justify-end bg-black/20" onClick={onClose}>
      <div
        className="flex h-full w-[520px] max-w-[90%] flex-col border-l bg-[var(--background)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: typeColor(node.node_type) }} />
          <span className="truncate text-sm font-semibold">{node.label}</span>
          <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
            {typeLabel(node.node_type)} · 先修 {node.prereq_labels.length} · BKT{" "}
            {node.p_known === null ? "未学" : `${Math.round(node.p_known * 100)}%`}
          </span>
          <button
            onClick={onClose}
            className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-[var(--accent)]"
            aria-label="关闭"
          >
            <X size={14} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <ExercisePanel node={node} learner={learner} onFinished={onExerciseFinished} />
        </div>
      </div>
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
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [exerciseOpen, setExerciseOpen] = useState(false);
  // selectedId 的 ref:loadPath 读它决定是否保留选择,但不依赖 state 本身
  // (依赖 state 会让点击节点触发 loadPath 重建 → effect 重跑 → 焦点覆盖点击)。
  const selectedIdRef = useRef<string | null>(null);

  /** 点击节点:树内高亮 + 打开到全局预览面板(Select a page to preview 区域)。 */
  const openNode = useCallback((node: LearningPathNode) => {
    setSelectedId(node.id);
    selectedIdRef.current = node.id;
    if (node.page_path) {
      useAppStore.getState().selectPage(node.page_path);
    }
  }, []);

  const loadPath = useCallback(
    (keepSelection: boolean) => {
      setLoading(true);
      api
        .getLearningPath(learner)
        .then((data) => {
          setPath(data);
          setError(null);
          const nextId =
            keepSelection && selectedIdRef.current
              ? selectedIdRef.current
              : data.focus_id || data.levels[0]?.nodes[0]?.id || null;
          setSelectedId(nextId);
          selectedIdRef.current = nextId;
          if (!keepSelection && nextId) {
            // 初始加载:焦点点的页面直接打开到预览面板,不留空态
            const focusNode = data.levels.flatMap((lv) => lv.nodes).find((n) => n.id === nextId);
            if (focusNode?.page_path) {
              useAppStore.getState().selectPage(focusNode.page_path);
            }
          }
        })
        .catch((e: any) => setError(e?.message || "加载学习路径失败"))
        .finally(() => setLoading(false));
    },
    [learner],
  );

  useEffect(() => {
    setSelectedId(null);
    selectedIdRef.current = null;
    setCollapsed(new Set());
    setExpanded(new Set());
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

  const toggle = useCallback((id: string, visible: boolean) => {
    if (visible) {
      // 折叠:加入显式折叠集,清掉展开标记
      setCollapsed((prev) => new Set(prev).add(id));
      setExpanded((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } else {
      // 展开:加入展开集(覆盖深度默认折叠),清掉显式折叠
      setExpanded((prev) => new Set(prev).add(id));
      setCollapsed((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, []);

  const progressPct = path && path.progress.total > 0
    ? Math.round((path.progress.mastered / path.progress.total) * 100)
    : 0;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
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
          onClick={() => setExerciseOpen(true)}
          disabled={!selected}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--primary)]/40 bg-[var(--primary)]/5 px-2.5 py-1 text-xs text-[var(--primary)] hover:bg-[var(--primary)]/10 disabled:opacity-40"
          title={selected ? `为《${selected.label}》出 ${QUESTION_COUNT} 题(材料含直接先修)` : "先选择一个知识点"}
        >
          <Sparkles size={12} /> 出题练习
        </button>
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
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* n 叉树图形(每棵树顶=树根=最先学,向下=学习推进);点节点 → 页面开进右侧全局预览面板 */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col p-1">
            <TreeDiagram
              path={path}
              selectedId={selectedId}
              collapsed={collapsed}
              expanded={expanded}
              onToggle={toggle}
              onSelect={openNode}
            />

            {/* 观察区:环点 + 边冲突 */}
            {(path.unresolved.length > 0 || path.edge_conflicts.length > 0) && (
              <section className="shrink-0 rounded-lg border border-dashed p-3">
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
                        <button className="font-medium hover:underline" onClick={() => openNode(n)}>
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
        </div>
      )}

      {/* 出题抽屉(材料=本点+直接先修;提交后 BKT 更新并刷新路径) */}
      {exerciseOpen && selected && (
        <ExerciseDrawer
          node={selected}
          learner={learner}
          onClose={() => setExerciseOpen(false)}
          onExerciseFinished={() => loadPath(true)}
        />
      )}
    </div>
  );
}
