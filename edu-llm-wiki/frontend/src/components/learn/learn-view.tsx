import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Dumbbell,
  FileText,
  FlaskConical,
  GraduationCap,
  HelpCircle,
  Loader2,
  Layers,
  Lightbulb,
  MessageCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Send,
  Star,
  X,
} from "lucide-react";
import { api, setProjectId } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Markdown } from "@/components/markdown";
import type { GraphData, GraphNode } from "@/types/wiki";

type ItemStatus = "not_started" | "done" | "needs_review";
type StageId = "overview" | "foundations" | "core" | "applications" | "review";

interface LearningItem {
  id: string;
  path: string;
  title: string;
  type: string;
  reason: string;
  prerequisites: string[];
  actions: ("read" | "ask" | "practice" | "review")[];
  status: ItemStatus;
  score: number;
  isBridge: boolean;
  isGap: boolean;
}

interface LearningStage {
  id: StageId;
  title: string;
  description: string;
  items: LearningItem[];
}

interface TutorMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

let tutorIdCounter = Date.now();
function nextTutorId() {
  return `${++tutorIdCounter}-${Math.random().toString(36).slice(2, 8)}`;
}

const STAGE_META: Record<StageId, { title: string; description: string }> = {
  overview: {
    title: "Overview",
    description: "Start with summaries and source-level context so the map has a shape.",
  },
  foundations: {
    title: "Foundations",
    description: "Build the vocabulary and concepts that later items depend on.",
  },
  core: {
    title: "Core Ideas",
    description: "Work through the main concepts, formulas, and principles.",
  },
  applications: {
    title: "Applications",
    description: "Practice with worked examples and the Tests view to check whether the ideas transfer.",
  },
  review: {
    title: "Review & Gaps",
    description: "Revisit isolated, weakly connected, or high-friction knowledge points.",
  },
};

const TYPE_CONFIG: Record<
  string,
  { icon: React.ElementType; color: string; bg: string; label: string }
> = {
  concept: {
    icon: BookOpen,
    color: "text-blue-600",
    bg: "bg-blue-50 dark:bg-blue-950/30",
    label: "Concept",
  },
  formula: {
    icon: FlaskConical,
    color: "text-violet-600",
    bg: "bg-violet-50 dark:bg-violet-950/30",
    label: "Formula",
  },
  principle: {
    icon: Lightbulb,
    color: "text-amber-600",
    bg: "bg-amber-50 dark:bg-amber-950/30",
    label: "Principle",
  },
  source: {
    icon: FileText,
    color: "text-gray-500",
    bg: "bg-gray-50 dark:bg-gray-950/30",
    label: "Source",
  },
  synthesis: {
    icon: Layers,
    color: "text-pink-600",
    bg: "bg-pink-50 dark:bg-pink-950/30",
    label: "Synthesis",
  },
};

const STATUS_LABELS: Record<ItemStatus, string> = {
  not_started: "Not started",
  done: "Done",
  needs_review: "Review",
};

function pagePath(node: GraphNode): string {
  const metadataPath = typeof node.metadata?.path === "string" ? node.metadata.path : "";
  return metadataPath || `${node.id}.md`;
}

function buildStages(data: GraphData, statuses: Record<string, ItemStatus>): LearningStage[] {
  const nodesById = new Map(data.nodes.map((node) => [node.id, node]));
  const adjacency = new Map<string, Set<string>>();
  const prereqOf = new Map<string, Set<string>>();
  const dependentsOf = new Map<string, Set<string>>();

  for (const node of data.nodes) {
    adjacency.set(node.id, new Set());
    prereqOf.set(node.id, new Set());
    dependentsOf.set(node.id, new Set());
  }

  for (const edge of data.edges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
    if (edge.edge_type === "prerequisite") {
      prereqOf.get(edge.target)?.add(edge.source);
      dependentsOf.get(edge.source)?.add(edge.target);
    }
  }

  const bridgeIds = new Set<string>();
  const gapIds = new Set<string>();
  for (const insight of data.insights) {
    if (insight.insight_type === "bridge") insight.node_ids.forEach((id) => bridgeIds.add(id));
    if (insight.insight_type === "knowledge_gap" || insight.insight_type === "isolated") {
      insight.node_ids.forEach((id) => gapIds.add(id));
    }
  }

  const buckets: Record<StageId, LearningItem[]> = {
    overview: [],
    foundations: [],
    core: [],
    applications: [],
    review: [],
  };

  for (const node of data.nodes) {
    const type = node.node_type;
    const degree = adjacency.get(node.id)?.size ?? 0;
    const prereqs = [...(prereqOf.get(node.id) ?? [])];
    const dependents = dependentsOf.get(node.id)?.size ?? 0;
    const isBridge = bridgeIds.has(node.id);
    const isGap = gapIds.has(node.id) || degree <= 1;
    const score = degree + dependents * 2 + (isBridge ? 4 : 0) - (isGap ? 1 : 0);
    const prerequisites = prereqs.map((id) => nodesById.get(id)?.label || id);

    let stage: StageId = "core";
    let reason = "This is part of the main conceptual spine.";
    let actions: LearningItem["actions"] = ["read", "ask"];

    if (type === "source" || type === "synthesis") {
      stage = "overview";
      reason =
        type === "source"
          ? "Use this to understand where the material came from."
          : "Use this synthesis as a map before details.";
      actions = ["read", "ask"];
    } else if (isGap) {
      stage = "review";
      reason = "This item has weak graph connections, so it is worth checking deliberately.";
      actions = ["read", "ask", "review"];
    } else if (prereqs.length === 0 || dependents >= 2) {
      stage = "foundations";
      reason =
        dependents >= 2
          ? "Many later items depend on this, so learn it early."
          : "This has few prerequisites and works as a foundation.";
      actions = ["read", "ask"];
    } else if (type === "formula" || type === "principle") {
      reason = "Connect this with its prerequisite concepts before applying it.";
      actions = ["read", "ask", "practice"];
    }

    buckets[stage].push({
      id: node.id,
      path: pagePath(node),
      title: node.label,
      type,
      reason,
      prerequisites,
      actions,
      status: statuses[node.id] || "not_started",
      score,
      isBridge,
      isGap,
    });
  }

  const orderByPriority = (a: LearningItem, b: LearningItem) => {
    const typeOrder = {
      synthesis: 0,
      source: 1,
      concept: 2,
      formula: 3,
      principle: 4,
    };
    return (
      (typeOrder[a.type as keyof typeof typeOrder] ?? 9) -
        (typeOrder[b.type as keyof typeof typeOrder] ?? 9) ||
      b.score - a.score ||
      a.title.localeCompare(b.title)
    );
  };

  return (Object.keys(STAGE_META) as StageId[])
    .map((id) => ({
      id,
      ...STAGE_META[id],
      items: buckets[id].sort(orderByPriority),
    }))
    .filter((stage) => stage.items.length > 0);
}

function nextLearningItem(stages: LearningStage[], goal: string): LearningItem | null {
  const preferredOrder: StageId[] =
    goal === "practice"
      ? ["applications", "core", "foundations", "review", "overview"]
      : goal === "review"
        ? ["review", "core", "applications", "foundations", "overview"]
        : goal === "quick"
          ? ["overview", "foundations", "core", "applications", "review"]
          : ["foundations", "core", "applications", "overview", "review"];
  for (const stageId of preferredOrder) {
    const stage = stages.find((s) => s.id === stageId);
    const item = stage?.items.find((i) => i.status !== "done");
    if (item) return item;
  }
  return null;
}

export function LearnView() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState("system");
  const [collapsedStages, setCollapsedStages] = useState<Set<StageId>>(new Set());
  const [tutorItem, setTutorItem] = useState<LearningItem | null>(null);
  const [tutorMessages, setTutorMessages] = useState<TutorMessage[]>([]);
  const [tutorInput, setTutorInput] = useState("");
  const [tutorStreaming, setTutorStreaming] = useState(false);
  const [tutorStatus, setTutorStatus] = useState<string | null>(null);
  const [tutorTopPercent, setTutorTopPercent] = useState(50);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const currentProject = useAppStore((s) => s.currentProject);
  const selectPage = useAppStore((s) => s.selectPage);
  const setActiveView = useAppStore((s) => s.setActiveView);
  const [statuses, setStatuses] = useState<Record<string, ItemStatus>>(() => {
    try {
      return JSON.parse(localStorage.getItem("edu-llm-wiki.learning.default") || "{}");
    } catch {
      return {};
    }
  });

  const storageKey = `edu-llm-wiki.learning.${currentProject}`;

  useEffect(() => {
    try {
      setStatuses(JSON.parse(localStorage.getItem(storageKey) || "{}"));
    } catch {
      setStatuses({});
    }
  }, [storageKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setProjectId(currentProject || "default");
    api
      .getGraph()
      .then((graph) => {
        if (!cancelled) setData(graph);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProject]);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(statuses));
  }, [statuses, storageKey]);

  const stages = useMemo(() => (data ? buildStages(data, statuses) : []), [data, statuses]);
  const nextItem = useMemo(() => nextLearningItem(stages, goal), [stages, goal]);
  const items = useMemo(() => stages.flatMap((stage) => stage.items), [stages]);
  const doneCount = items.filter((item) => item.status === "done").length;
  const reviewCount = items.filter((item) => item.status === "needs_review").length;
  const progress = items.length ? Math.round((doneCount / items.length) * 100) : 0;

  const updateStatus = useCallback((id: string, status: ItemStatus) => {
    setStatuses((prev) => ({ ...prev, [id]: status }));
  }, []);

  const openItem = useCallback(
    async (item: LearningItem) => {
      await selectPage(item.path);
      if (item.status === "not_started") updateStatus(item.id, "done");
    },
    [selectPage, updateStatus],
  );

  const askTutor = useCallback(
    async (item: LearningItem) => {
      setTutorItem(item);
      setTutorMessages([
        {
          id: nextTutorId(),
          role: "assistant",
          content: `我会围绕 **${item.title}** 辅导你。你可以问“这页怎么学”“给我举例”“我哪里没理解”，也可以直接贴你的困惑。`,
        },
      ]);
      setTutorInput("");
      void selectPage(item.path);
    },
    [selectPage],
  );

  const sendTutorMessage = useCallback(async () => {
    if (!tutorItem || !tutorInput.trim() || tutorStreaming) return;

    const userText = tutorInput.trim();
    const assistantId = nextTutorId();
    const nextMessages: TutorMessage[] = [
      ...tutorMessages,
      { id: nextTutorId(), role: "user", content: userText },
      { id: assistantId, role: "assistant", content: "" },
    ];
    setTutorMessages(nextMessages);
    setTutorInput("");
    setTutorStreaming(true);
    setTutorStatus("Reading current learning item...");

    try {
      let lastContent = "";
      const apiMessages = [
        {
          role: "user",
          content: [
            `你是学习路径中的 Tutor，当前学习节点是：${tutorItem.title}`,
            `节点类型：${tutorItem.type}`,
            `学习原因：${tutorItem.reason}`,
            tutorItem.prerequisites.length ? `前置知识：${tutorItem.prerequisites.join("、")}` : "",
            "",
            `学生问题：${userText}`,
          ]
            .filter(Boolean)
            .join("\n"),
        },
      ];

      for await (const event of api.chatStream(apiMessages, undefined, {
        mode: "ask",
        scope: { type: "current_page", page_path: tutorItem.path },
        options: { citation_required: true, answer_style: "socratic" },
      })) {
        if (event.type === "status") {
          setTutorStatus(event.text);
        } else if (event.type === "content") {
          lastContent += event.text;
          setTutorMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: lastContent } : m)),
          );
        } else if (event.type === "replace") {
          lastContent = event.text;
          setTutorMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: lastContent } : m)),
          );
        }
      }
    } catch (e: any) {
      setTutorMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: `Tutor failed: ${e?.message || e}` } : m,
        ),
      );
    } finally {
      setTutorStreaming(false);
      setTutorStatus(null);
    }
  }, [tutorInput, tutorItem, tutorMessages, tutorStreaming]);

  const practiceItem = useCallback(
    async (item: LearningItem) => {
      await selectPage(item.path);
      setActiveView("wiki");
    },
    [selectPage, setActiveView],
  );

  const startTutorResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const container = splitContainerRef.current;
    if (!container) return;

    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";

    const onMove = (moveEvent: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const next = ((moveEvent.clientY - rect.top) / rect.height) * 100;
      setTutorTopPercent(Math.min(78, Math.max(22, next)));
    };

    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const toggleStage = (stageId: StageId) => {
    setCollapsedStages((prev) => {
      const next = new Set(prev);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <RefreshCw className="h-8 w-8 animate-spin opacity-40" />
        <p className="text-sm">Building learning path...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--muted-foreground)]">
        <GraduationCap className="h-10 w-10 opacity-30" />
        <p className="text-sm text-red-500">{error}</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-[var(--muted-foreground)]">
        <div>
          <GraduationCap className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p className="text-sm font-medium">No learning path available</p>
          <p className="text-xs mt-1">Import documents and run ingest to generate knowledge.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <GraduationCap className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span className="text-sm font-medium">Learning Path</span>
          <select
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            className="ml-auto h-7 rounded-md border bg-[var(--background)] px-2 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
          >
            <option value="system">System Learning</option>
            <option value="quick">Quick Start</option>
            <option value="practice">Practice Driven</option>
            <option value="review">Review Gaps</option>
          </select>
        </div>
        <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3">
          <div className="h-2 overflow-hidden rounded-full bg-[var(--muted)]">
            <div
              className="h-full bg-[var(--primary)] transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-xs text-[var(--muted-foreground)]">
            {doneCount} / {items.length}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-[var(--muted-foreground)]">
          <span>{stages.length} stages</span>
          <span>·</span>
          <span>{reviewCount} marked for review</span>
          <span>·</span>
          <span>
            Goal:{" "}
            {goal === "system"
              ? "System Learning"
              : goal === "quick"
                ? "Quick Start"
                : goal === "practice"
                  ? "Practice Driven"
                  : "Review Gaps"}
          </span>
        </div>
      </div>

      <div ref={splitContainerRef} className="flex min-h-0 flex-1 flex-col">
        <div
          className={`${tutorItem ? "min-h-[160px] shrink-0" : "flex-1"} min-h-0 overflow-y-auto px-4 py-4`}
          style={tutorItem ? { flexBasis: `${tutorTopPercent}%` } : undefined}
        >
          {nextItem && (
            <section className="mb-5 border-b pb-4">
              <div className="mb-2 flex items-center gap-2">
                <Play className="h-4 w-4 text-[var(--primary)]" />
                <h2 className="text-sm font-semibold">Continue Learning</h2>
                {nextItem.status === "needs_review" && (
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
                    Review
                  </span>
                )}
              </div>
              <div className="flex items-start gap-3 rounded-md border p-3">
                <TypeIcon type={nextItem.type} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{nextItem.title}</p>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">{nextItem.reason}</p>
                  {nextItem.prerequisites.length > 0 && (
                    <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                      Requires: {nextItem.prerequisites.slice(0, 3).join(", ")}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-1">
                  <IconButton
                    label="Start"
                    onClick={() => openItem(nextItem)}
                    icon={<Play size={14} />}
                  />
                  <IconButton
                    label="Ask Tutor"
                    onClick={() => askTutor(nextItem)}
                    icon={<MessageCircle size={14} />}
                  />
                  <IconButton
                    label="Done"
                    onClick={() => updateStatus(nextItem.id, "done")}
                    icon={<Check size={14} />}
                  />
                </div>
              </div>
            </section>
          )}

          {stages.map((stage, index) => {
            const collapsed = collapsedStages.has(stage.id);
            const stageDone = stage.items.filter((item) => item.status === "done").length;
            return (
              <section key={stage.id} className="mb-5">
                <button
                  onClick={() => toggleStage(stage.id)}
                  className="mb-2 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-[var(--accent)]"
                >
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--primary)] text-xs font-semibold text-[var(--primary-foreground)]">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      <span className="text-sm font-semibold">{stage.title}</span>
                      <span className="text-[11px] text-[var(--muted-foreground)]">
                        {stageDone}/{stage.items.length}
                      </span>
                    </div>
                    <p className="truncate text-xs text-[var(--muted-foreground)]">
                      {stage.description}
                    </p>
                  </div>
                </button>
                {!collapsed && (
                  <div className="space-y-2 border-l pl-4">
                    {stage.items.map((item) => (
                      <LearningRow
                        key={item.id}
                        item={item}
                        onRead={() => openItem(item)}
                        onAsk={() => askTutor(item)}
                        onPractice={() => practiceItem(item)}
                        onDone={() => updateStatus(item.id, "done")}
                        onReview={() =>
                          updateStatus(
                            item.id,
                            item.status === "needs_review" ? "not_started" : "needs_review",
                          )
                        }
                      />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>

        {tutorItem && (
          <>
            <div
              onMouseDown={startTutorResize}
              className="group flex h-2 shrink-0 cursor-row-resize items-center justify-center border-y bg-[var(--muted)]/40 hover:bg-[var(--primary)]/10"
              title="Drag to resize tutor"
            >
              <div className="h-0.5 w-10 rounded-full bg-[var(--border)] group-hover:bg-[var(--primary)]" />
            </div>
            <TutorPanel
              item={tutorItem}
              messages={tutorMessages}
              input={tutorInput}
              streaming={tutorStreaming}
              status={tutorStatus}
              onInput={setTutorInput}
              onSend={sendTutorMessage}
              onClose={() => setTutorItem(null)}
            />
          </>
        )}
      </div>
    </div>
  );
}

function TutorPanel({
  item,
  messages,
  input,
  streaming,
  status,
  onInput,
  onSend,
  onClose,
}: {
  item: LearningItem;
  messages: TutorMessage[];
  input: string;
  streaming: boolean;
  status: string | null;
  onInput: (value: string) => void;
  onSend: () => void;
  onClose: () => void;
}) {
  return (
    <section className="flex min-h-[160px] flex-1 flex-col bg-[var(--background)]">
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-2">
        <MessageCircle className="h-4 w-4 text-[var(--primary)]" />
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">Tutor</h2>
          <p className="truncate text-[11px] text-[var(--muted-foreground)]">{item.title}</p>
        </div>
        <button
          onClick={onClose}
          className="ml-auto rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          title="Close tutor"
        >
          <X size={14} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div className="space-y-3">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[86%] rounded-lg px-3 py-2 text-sm ${
                  message.role === "user"
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "bg-[var(--muted)] text-[var(--foreground)]"
                }`}
              >
                {message.role === "assistant" ? (
                  <Markdown>{message.content || "..."}</Markdown>
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
              </div>
            </div>
          ))}
          {streaming && (
            <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {status || "Tutor is thinking..."}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t p-3">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={(e) => {
              const nativeEvent = e.nativeEvent as KeyboardEvent & { isComposing?: boolean };
              if (nativeEvent.isComposing || nativeEvent.keyCode === 229) return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="Ask about this learning item..."
            rows={2}
            className="min-w-0 flex-1 resize-none rounded-md border bg-[var(--background)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          />
          <button
            onClick={onSend}
            disabled={!input.trim() || streaming}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] disabled:opacity-50"
            title="Send"
          >
            {streaming ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
      </div>
    </section>
  );
}

function TypeIcon({ type }: { type: string }) {
  const cfg = TYPE_CONFIG[type] ?? TYPE_CONFIG.concept;
  const Icon = cfg.icon;
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${cfg.bg}`}>
      <Icon className={`h-4 w-4 ${cfg.color}`} />
    </div>
  );
}

function IconButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-md border text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
      title={label}
    >
      {icon}
    </button>
  );
}

function LearningRow({
  item,
  onRead,
  onAsk,
  onPractice,
  onDone,
  onReview,
}: {
  item: LearningItem;
  onRead: () => void;
  onAsk: () => void;
  onPractice: () => void;
  onDone: () => void;
  onReview: () => void;
}) {
  const cfg = TYPE_CONFIG[item.type] ?? TYPE_CONFIG.concept;
  return (
    <div className={`group rounded-md border p-3 ${item.status === "done" ? "opacity-65" : ""}`}>
      <div className="flex items-start gap-3">
        <TypeIcon type={item.type} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium group-hover:text-[var(--primary)]">
              {item.title}
            </span>
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${cfg.bg} ${cfg.color}`}>
              {cfg.label}
            </span>
            {item.isBridge && (
              <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-blue-100 px-1 py-0.5 text-[10px] text-blue-600">
                <Star className="h-2.5 w-2.5" />
                Key
              </span>
            )}
            {item.status === "needs_review" && (
              <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-100 px-1 py-0.5 text-[10px] text-amber-700">
                <AlertTriangle className="h-2.5 w-2.5" />
                Review
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.reason}</p>
          {item.prerequisites.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {item.prerequisites.slice(0, 4).map((prereq) => (
                <span
                  key={prereq}
                  className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
                >
                  {prereq}
                </span>
              ))}
            </div>
          )}
        </div>
        <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
          {STATUS_LABELS[item.status]}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 pl-11">
        {item.actions.includes("read") && (
          <ActionButton label="Read" icon={<BookOpen size={12} />} onClick={onRead} />
        )}
        {item.actions.includes("ask") && (
          <ActionButton label="Ask Tutor" icon={<MessageCircle size={12} />} onClick={onAsk} />
        )}
        {item.actions.includes("practice") && (
          <ActionButton label="Practice" icon={<Dumbbell size={12} />} onClick={onPractice} />
        )}
        {item.actions.includes("review") && (
          <ActionButton
            label={item.status === "needs_review" ? "Clear Review" : "Needs Review"}
            icon={<RotateCcw size={12} />}
            onClick={onReview}
          />
        )}
        <ActionButton label="Mark Done" icon={<Check size={12} />} onClick={onDone} />
        {item.isGap && (
          <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-amber-600">
            <HelpCircle size={11} /> weak link
          </span>
        )}
      </div>
    </div>
  );
}

function ActionButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
    >
      {icon}
      {label}
    </button>
  );
}
