import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react"
import { FileSearch, Download, Folder as FolderIcon } from "lucide-react"
import { api, type TestCreateRequest, type TestQuestion, type TestSession, type TestSummary } from "@/lib/api"
import { InlineMarkdown, Markdown } from "@/components/markdown"
import { ConfidenceSlider } from "@/components/learning/confidence-slider"
import { toast } from "@/components/ui/toast"
import { useAppStore } from "@/stores/app-store"
import { useUserStore } from "@/stores/user-store"
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Target,
  Trash2,
} from "lucide-react"

const QUESTION_TYPES = [
  { id: "multiple_choice", label: "Select" },
  { id: "fill_blank", label: "Fill in the blank" },
  { id: "short_answer", label: "Short answer" },
]

const DIFFICULTIES = [
  { id: "mixed", label: "Mixed" },
  { id: "basic", label: "Basic" },
  { id: "understanding", label: "Understood" },
  { id: "application", label: "Apply" },
]

function answerToText(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value.filter(Boolean).join("；")
  return value || ""
}

function questionTypeSummary(session: TestSession): string {
  const counts: Record<string, number> = {}
  for (const q of session.questions) {
    const label = q.type === "multiple_choice" ? "Select" : q.type === "fill_blank" ? "Fill in the blank" : "Short answer"
    counts[label] = (counts[label] || 0) + 1
  }
  return Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(" · ")
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min < 60) return `${min}m${sec ? `${sec}s` : ""}`
  const hr = Math.floor(min / 60)
  const mm = min % 60
  return `${hr}h${mm ? `${mm}m` : ""}`
}

function scoreLabel(session: TestSummary | TestSession): string {
  if (session.score == null || session.max_score == null) return "Not submitted"
  return `${session.score}/${session.max_score}`
}

function levelClass(level: string): string {
  if (level === "good") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/25 dark:text-emerald-200"
  if (level === "partial") return "border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-950/25 dark:text-amber-200"
  return "border-red-200 bg-red-50 text-red-700 dark:bg-red-950/25 dark:text-red-200"
}

function questionTypeLabel(type: string): string {
  if (type === "multiple_choice") return "Multiple choice"
  if (type === "fill_blank") return "Fill-in-the-Blank"
  return "Short answer"
}

function SourceLinks({ question }: { question: TestSession["questions"][number] }) {
  const selectPage = useAppStore((s) => s.selectPage)
  const wikiPages = useAppStore((s) => s.wikiPages)
  const titleByPath = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of wikiPages) map.set(p.path, p.title)
    return map
  }, [wikiPages])

  const handleConcept = async (concept: string) => {
    const match = wikiPages.find((p) => p.title.toLowerCase().includes(concept.toLowerCase()))
    if (match) {
      await selectPage(match.path)
      return
    }
    try {
      const resp = await api.search(concept)
      const hit = resp.results.find((r) => r.path.endsWith(".md"))
      if (hit) await selectPage(hit.path)
    } catch {
      // silently ignore — concept is informational
    }
  }

  if (!question.related_page && (!question.concepts || question.concepts.length === 0)) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-[var(--muted-foreground)]">Source Under Test</span>
      {question.related_page && (
        <button
          onClick={() => selectPage(question.related_page!)}
          className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[var(--primary)] hover:bg-[var(--accent)]"
          title={question.related_page}
        >
          <FileSearch size={11} />
          {titleByPath.get(question.related_page) || question.related_page}
        </button>
      )}
      {(question.concepts || []).map((concept) => (
        <button
          key={concept}
          onClick={() => handleConcept(concept)}
          className="rounded-full border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        >
          {concept}
        </button>
      ))}
    </div>
  )
}

export function TestsView() {
  const currentProject = useAppStore((s) => s.currentProject)
  const [sessions, setSessions] = useState<TestSummary[]>([])
  const [sources, setSources] = useState<{ name: string; size: number; modified: number }[]>([])
  const [activeSession, setActiveSession] = useState<TestSession | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [confidences, setConfidences] = useState<Record<string, number>>({})
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [lastAnswerAt, setLastAnswerAt] = useState<Record<string, number>>({})
  const [submitSummary, setSubmitSummary] = useState<{ total: number; perQuestion: { id: string; ms: number }[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [openingSessionId, setOpeningSessionId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<"all" | "submitted" | "active">("all")
  const operations = useAppStore((s) => s.operations)
  const beginOperation = useAppStore((s) => s.beginOperation)
  const endOperation = useAppStore((s) => s.endOperation)
  const creatingTest = Boolean(operations["tests:create"])
  const submitting = activeSession ? Boolean(operations[`tests:submit:${activeSession.id}`]) : false
  const [form, setForm] = useState<TestCreateRequest>({
    scope: "wiki",
    source: null,
    natural_prompt: "",
    folder: "",
    question_count: 5,
    question_types: ["multiple_choice", "fill_blank", "short_answer"],
    difficulty: "mixed",
    mode: "practice",
    page_path: null,
  })

  // Consume a page-scoped request from PreviewPanel's footer button.
  const pendingTestPagePath = useAppStore((s) => s.pendingTestPagePath)
  const userId = useUserStore((s) => s.userId)
  const setPendingTestPagePath = useAppStore((s) => s.setPendingTestPagePath)
  useEffect(() => {
    if (!pendingTestPagePath) return
    setForm((f) => ({ ...f, page_path: pendingTestPagePath, scope: "wiki" }))
    setPendingTestPagePath(null)
  }, [pendingTestPagePath, setPendingTestPagePath])

  const currentQuestion = activeSession?.questions[currentIndex] || null
  const existingFolders = useMemo(() => {
    const folders = new Set<string>()
    for (const session of sessions) {
      if (session.folder) folders.add(session.folder)
    }
    return Array.from(folders).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"))
  }, [sessions])

  const filteredSessions = useMemo(
    () => sessions.filter((session) => statusFilter === "all" || session.status === statusFilter),
    [sessions, statusFilter],
  )

  const folderGroups = useMemo(() => {
    const groups = new Map<string, TestSummary[]>()
    for (const session of filteredSessions) {
      const key = session.folder || "Uncategorized"
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(session)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => {
      if (a === "Uncategorized") return 1
      if (b === "Uncategorized") return -1
      return a.localeCompare(b, "zh-Hans-CN")
    })
  }, [filteredSessions])

  const attemptsById = useMemo(() => {
    const map = new Map<string, TestSession["attempts"][number]>()
    for (const attempt of activeSession?.attempts || []) map.set(attempt.question_id, attempt)
    return map
  }, [activeSession])

  const answeredCount = useMemo(() => {
    if (!activeSession) return 0
    return activeSession.questions.filter((question) => answerToText(answers[question.id]).trim()).length
  }, [activeSession, answers])

  const draftKey = (uid: string, sessionId: string) =>
    `tests.draft.${uid}.${sessionId}`

  type DraftPayload = {
    answers: Record<string, string | string[]>
    confidences: Record<string, number>
    lastAnswerAt: Record<string, number>
    savedAt: number
  }

  const readDraft = (uid: string, sessionId: string): DraftPayload | null => {
    if (typeof window === "undefined") return null
    try {
      const raw = window.localStorage.getItem(draftKey(uid, sessionId))
      if (!raw) return null
      const parsed = JSON.parse(raw) as DraftPayload
      if (!parsed || typeof parsed !== "object") return null
      return parsed
    } catch {
      return null
    }
  }

  const writeDraft = (
    uid: string,
    sessionId: string,
    payload: { answers: Record<string, string | string[]>; confidences: Record<string, number>; lastAnswerAt: Record<string, number> },
  ) => {
    if (typeof window === "undefined") return
    try {
      const value: DraftPayload = { ...payload, savedAt: Date.now() }
      window.localStorage.setItem(draftKey(uid, sessionId), JSON.stringify(value))
    } catch {
      // localStorage may be full or disabled; ignore — the worst case is the
      // next refresh loses the in-progress answers.
    }
  }

  const clearDraft = (uid: string, sessionId: string) => {
    if (typeof window === "undefined") return
    try {
      window.localStorage.removeItem(draftKey(uid, sessionId))
    } catch {
      // ignore
    }
  }

  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!activeSession || activeSession.submitted_at) return
    if (!userId) return
    if (Object.keys(answers).length === 0 && Object.keys(confidences).length === 0) return
    if (draftTimer.current) clearTimeout(draftTimer.current)
    draftTimer.current = setTimeout(() => {
      writeDraft(userId, activeSession.id, { answers, confidences, lastAnswerAt })
    }, 800)
    return () => {
      if (draftTimer.current) clearTimeout(draftTimer.current)
    }
  }, [activeSession, answers, confidences, lastAnswerAt, userId])

  const loadData = async () => {
    try {
      const [testList, sourceList] = await Promise.all([api.listTests(), api.listSources().catch(() => [])])
      setSessions(testList)
      setSources(sourceList)
    } catch (e: any) {
      toast({ type: "error", message: `加载测试失败: ${e?.message || e}` })
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const moveSessionFolder = async (sessionId: string, nextFolder: string) => {
    let folder = nextFolder
    if (folder === "__new__") {
      folder = typeof window === "undefined" ? "" : window.prompt("Enter a new test directory; use / for hierarchy, e.g. Final Review/Chapter 2") || ""
      if (!folder.trim()) return
    }
    try {
      const updated = await api.updateTest(sessionId, { folder: folder.trim() || null })
      setSessions((prev) => prev.map((item) => (item.id === updated.id ? { ...item, folder: updated.folder } : item)))
      if (activeSession?.id === updated.id) setActiveSession(updated)
      toast({ type: "success", message: updated.folder ? `已移动到「${updated.folder}」` : "已移回Uncategorized" })
    } catch (e: any) {
      toast({ type: "error", message: `移动测试失败：${e?.message || e}` })
    }
  }

  const createTest = async () => {
    beginOperation("tests:create", "Generating test")
    try {
      const session = await api.createTest({
        ...form,
        title: form.title?.trim() || undefined,
        natural_prompt: form.natural_prompt?.trim() || undefined,
        folder: form.folder?.trim() || undefined,
        source: form.scope === "source" ? form.source : null,
        // Auto-inject a fresh seed each time so the backend can drive
        // diversity instead of returning a near-identical question set.
        seed: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
      setActiveSession(session)
      setCurrentIndex(0)
      setAnswers({})
      setConfidences({})
      setStartedAt(Date.now())
      setLastAnswerAt({})
      setSubmitSummary(null)
      await loadData()
      toast({ type: "success", message: `已生成 ${session.questions.length} 道测试题` })
    } catch (e: any) {
      toast({ type: "error", message: `Generate Test失败: ${e?.message || e}` })
    } finally {
      endOperation("tests:create")
    }
  }

  const openSession = async (id: string) => {
    setLoading(true)
    setOpeningSessionId(id)
    try {
      const session = await api.getTest(id)
      setActiveSession(session)
      setCurrentIndex(0)
      const restored: Record<string, string | string[]> = {}
      const restoredConfidence: Record<string, number> = {}
      for (const attempt of session.attempts || []) {
        restored[attempt.question_id] = attempt.user_answer
        if (attempt.confidence != null) restoredConfidence[attempt.question_id] = attempt.confidence
      }

      // Restore in-progress draft from localStorage if the learner never
      // submitted this session yet. A submitted session keeps the server
      // record as authoritative.
      let restoredLastAnswerAt: Record<string, number> = {}
      if (!session.submitted_at) {
        const draft = readDraft(userId, session.id)
        if (draft) {
          for (const [qid, val] of Object.entries(draft.answers || {})) {
            restored[qid] = val
          }
          for (const [qid, val] of Object.entries(draft.confidences || {})) {
            restoredConfidence[qid] = val
          }
          restoredLastAnswerAt = draft.lastAnswerAt || {}
        }
      }

      setAnswers(restored)
      setConfidences(restoredConfidence)
      setStartedAt(session.submitted_at ? null : Date.now())
      setLastAnswerAt(restoredLastAnswerAt)
      setSubmitSummary(null)
    } catch (e: any) {
      toast({ type: "error", message: `打开测试失败: ${e?.message || e}` })
    } finally {
      setLoading(false)
      setOpeningSessionId(null)
    }
  }

  const deleteSession = async (id: string) => {
    const confirmed = typeof window === "undefined"
      || window.confirm("Deleting this test session will also clear historical answer records. Are you sure you want to continue?")
    if (!confirmed) return
    try {
      await api.deleteTest(id)
      clearDraft(userId, id)
      if (activeSession?.id === id) {
        setActiveSession(null)
        setAnswers({})
        setConfidences({})
      }
      await loadData()
      toast({ type: "success", message: "Test deleted" })
    } catch (e: any) {
      toast({ type: "error", message: `Delete Test失败: ${e?.message || e}` })
    }
  }

  const setAnswer = (questionId: string, value: string | string[]) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }))
    setLastAnswerAt((prev) => ({ ...prev, [questionId]: Date.now() }))
  }
  const regenerateFromWrong = async () => {
    if (!activeSession) return
    if (typeof window === "undefined") return
    const confirmed = window.confirm("Generate a new test containing only the wrong answers from this test?")
    if (!confirmed) return
    beginOperation(`tests:regen:${activeSession.id}`, "Generate Mistake Test")
    try {
      const session = await api.regenerateFromWrong(activeSession.id, userId)
      setActiveSession(session)
      setCurrentIndex(0)
      setAnswers({})
      setConfidences({})
      setStartedAt(Date.now())
      setLastAnswerAt({})
      setSubmitSummary(null)
      setPendingTestPagePath(null)
      await loadData()
      toast({ type: "success", message: `已Generate Mistake Test：${session.questions.length} 题` })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to generate wrong-answer test" })
    } finally {
      endOperation(`tests:regen:${activeSession.id}`)
    }
  }

  const resetAnswers = () => {
    if (typeof window === "undefined") return
    if (!activeSession) return
    const confirmed = window.confirm("Clear all answers and confidence for this test and start over? Submitted scores will not change.")
    if (!confirmed) return
    setAnswers({})
    setConfidences({})
    setLastAnswerAt({})
    setCurrentIndex(0)
    setStartedAt(Date.now())
    setSubmitSummary(null)
    clearDraft(userId, activeSession.id)
    toast({ type: "success", message: "Answer cleared; you can answer again" })
  }

  const exportTest = () => {
    if (!activeSession) return
    const lines: string[] = []
    lines.push(`# ${activeSession.title || "Test Session"}`)
    lines.push("")
    lines.push(`- Exported: ${new Date().toLocaleString()}`)
    lines.push(`- 学习者: ${userId}`)
    if (activeSession.submitted_at) {
      lines.push(`- 提交时间: ${activeSession.submitted_at}`)
    }
    if (activeSession.score != null && activeSession.max_score != null) {
      const pct = Math.round((activeSession.score / activeSession.max_score) * 100)
      lines.push(`- 得分: ${activeSession.score}/${activeSession.max_score} (${pct}%)`)
    }
    if (submitSummary) {
      const avg = Math.round(submitSummary.total / Math.max(1, submitSummary.perQuestion.length))
      lines.push(`- 总用时: ${formatDuration(submitSummary.total)} · 平均 ${formatDuration(avg)} / 题`)
    }
    lines.push("")
    activeSession.questions.forEach((q, i) => {
      const a = activeSession.attempts?.find((x) => x.question_id === q.id)
      const conf = a?.confidence
      const dur = submitSummary?.perQuestion[i]?.ms
      lines.push(`## Q${i + 1}. ${q.prompt.replace(/\n+/g, " ").slice(0, 200)}`)
      lines.push(`- Type: ${q.type}`)
      if (q.options.length > 0) lines.push(`- 选项: ${q.options.join(" | ")}`)
      lines.push(`- Reference Answer: ${q.answer}`)
      lines.push(`- 学生Answer: ${a ? answerToText(a.user_answer) : "(Unanswered)"}`)
      if (a) lines.push(`- 得分: ${a.score}/${a.max_score} · 等级: ${a.level}`)
      if (conf != null) lines.push(`- 把握: ${conf}/5`)
      if (dur != null) lines.push(`- 用时: ${formatDuration(dur)}`)
      if (q.explanation) {
        lines.push("")
        lines.push("**Analysis**")
        lines.push(q.explanation)
      }
      lines.push("")
    })
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${(activeSession.title || "test").replace(/[\\\\/:*?"<>|]+/g, "_").slice(0, 64)}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast({ type: "success", message: "Test results exported" })
  }

  const submit = async () => {
    if (!activeSession) return
    const key = `tests:submit:${activeSession.id}`
    beginOperation(key, "Submitting test")
    const finishAt = Date.now()
    try {
      const session = await api.submitTest(activeSession.id, answers, confidences, userId)
      setActiveSession(session)
      const perQuestion = session.questions.map((q) => {
        const last = lastAnswerAt[q.id]
        // Un-answered questions do not have a per-question duration; show 0.
        if (!last) return { id: q.id, ms: 0 }
        const base = startedAt ?? last
        return { id: q.id, ms: Math.max(0, last - base) }
      })
      const total = perQuestion.reduce((sum, x) => sum + x.ms, 0)
      setSubmitSummary({ total, perQuestion })
      setStartedAt(null)
      // Submission succeeded; the server record is now authoritative.
      clearDraft(userId, activeSession.id)
      await loadData()
      // Use the same count the sidebar uses (the backend-computed wrong_count
      // when available, fallback to the approximation from individual attempts).
      const wrongCount = (session.attempts || []).filter(
        (a) => (a.score || 0) / Math.max(1, a.max_score || 1) < 0.5
      ).length
      const correctCount = (session.attempts || []).length - wrongCount
      toast({
        type: "success",
        message: `Submitted ${scoreLabel(session)} · Correct ${correctCount} · Incorrect ${wrongCount}`,
      })
      // After the auto-refit that runs in submit_test, check whether the
      // user newly mastered any KC and celebrate.
      try {
        const summary = await api.getLearningState(userId)
        const mastered = summary?.n_kcs_mastered ?? 0
        if (mastered > 0) {
          toast({
            type: "success",
            message: `🎉 Mastered ${mastered} / ${summary?.n_kcs_tracked ?? mastered} 个知识组件`,
          })
        }
      } catch {
        // Learning state may be empty for new users; ignore.
      }
    } catch (e: any) {
      toast({ type: "error", message: `提交失败: ${e?.message || e}` })
    } finally {
      endOperation(key)
    }
  }

  const toggleQuestionType = (id: string) => {
    setForm((prev) => {
      const exists = prev.question_types.includes(id)
      const next = exists ? prev.question_types.filter((type) => type !== id) : [...prev.question_types, id]
      return { ...prev, question_types: next.length ? next : [id] }
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      <header className="shrink-0 border-b px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
            <ClipboardCheck size={20} />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Tests</h1>
            <p className="text-sm text-[var(--muted-foreground)]">Stage assessments, AI grading, and mistake diagnostics</p>
          </div>
          <button
            onClick={loadData}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r bg-[var(--sidebar)] p-4">
          <section className="rounded-lg border bg-[var(--background)] p-3">
            <div className="mb-3 flex items-center gap-2">
              <Plus size={16} className="text-[var(--primary)]" />
              <h2 className="text-sm font-semibold">Create Test</h2>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Title</span>
                <input
                  value={form.title || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                  placeholder="Optional: Materials electricity unit test"
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Generate Questions from Natural Language</span>
                <textarea
                  value={form.natural_prompt || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, natural_prompt: e.target.value }))}
                  placeholder="e.g. Create 10 applied questions about fatigue fracture, only multiple choice and short answer"
                  rows={3}
                  className="w-full resize-none rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                />
                <span className="mt-1 block text-[10px] text-[var(--muted-foreground)]">
                  Question count, question types, difficulty, and topic will be sent to the backend; the advanced settings below serve as defaults.
                </span>
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Test Catalog</span>
                <input
                  value={form.folder || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, folder: e.target.value }))}
                  placeholder="Optional: Final review / Chapter 2"
                  list="test-folder-options"
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                />
                <datalist id="test-folder-options">
                  {existingFolders.map((folder) => (
                    <option key={folder} value={folder} />
                  ))}
                </datalist>
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Range</span>
                <select
                  value={form.scope}
                  onChange={(e) => setForm((prev) => ({ ...prev, scope: e.target.value as "wiki" | "source" }))}
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm"
                >
                  <option value="wiki">Entire Wiki</option>
                  <option value="source">Specified Document</option>
                </select>
              </label>

              {form.page_path && (
                <div className="rounded-md border border-dashed border-[var(--primary)]/40 bg-[var(--primary)]/5 px-2.5 py-1.5 text-[11px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[var(--muted-foreground)]">
                      Target Page: <span className="font-medium text-[var(--foreground)]">{form.page_path.split("/").pop()?.replace(/\.md$/, "")}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => setForm((prev) => ({ ...prev, page_path: null }))}
                      className="shrink-0 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              )}

              {/* page_path indicator above; legacy scope-conditional source picker continues below */}

              {form.scope === "source" && (
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Document</span>
                  <select
                    value={form.source || ""}
                    onChange={(e) => setForm((prev) => ({ ...prev, source: e.target.value || null }))}
                    className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm"
                  >
                    <option value="">Select source file</option>
                    {sources.map((source) => (
                      <option key={source.name} value={source.name}>{source.name}</option>
                    ))}
                  </select>
                </label>
              )}

              <div>
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Question count</span>
                <div className="grid grid-cols-4 gap-1.5">
                  {[5, 10, 15, 20].map((count) => (
                    <button
                      key={count}
                      onClick={() => setForm((prev) => ({ ...prev, question_count: count }))}
                      className={`rounded-md border px-2 py-1.5 text-sm ${form.question_count === count ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "hover:bg-[var(--accent)]"}`}
                    >
                      {count}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Question type</span>
                <div className="grid grid-cols-3 gap-1.5">
                  {QUESTION_TYPES.map((type) => (
                    <button
                      key={type.id}
                      onClick={() => toggleQuestionType(type.id)}
                      className={`rounded-md border px-2 py-1.5 text-sm ${form.question_types.includes(type.id) ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "hover:bg-[var(--accent)]"}`}
                    >
                      {type.label}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">Difficulty</span>
                <select
                  value={form.difficulty}
                  onChange={(e) => setForm((prev) => ({ ...prev, difficulty: e.target.value }))}
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm"
                >
                  {DIFFICULTIES.map((difficulty) => (
                    <option key={difficulty.id} value={difficulty.id}>{difficulty.label}</option>
                  ))}
                </select>
              </label>

              <button
                onClick={createTest}
                disabled={creatingTest || (form.scope === "source" && !form.source)}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[var(--primary)] px-3 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
              >
                {creatingTest ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                {creatingTest ? "Generating..." : "Generate Test"}
              </button>
            </div>
          </section>

          <section className="mt-4">
            <div className="mb-2 flex items-center gap-2">
              <FileText size={15} className="text-[var(--muted-foreground)]" />
              <h2 className="text-sm font-semibold">Test History</h2>
            </div>
            <div className="mb-2 flex items-center gap-1.5 text-xs">
              {(["all", "submitted", "active"] as const).map((key) => {
                const label = key === "all" ? "All" : key === "submitted" ? "Graded" : "In Progress"
                const count = key === "all"
                  ? sessions.length
                  : sessions.filter((s) => s.status === key).length
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setStatusFilter(key)}
                    className={
                      "rounded-md border px-2 py-0.5 " +
                      (statusFilter === key
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]")
                    }
                  >
                    {label} <span className="opacity-60">({count})</span>
                  </button>
                )
              })}
            </div>
            <div className="space-y-4">
              {sessions.length === 0 && (
                <p className="rounded-md border border-dashed px-3 py-5 text-center text-sm text-[var(--muted-foreground)]">No test records yet</p>
              )}
              {folderGroups.map(([folder, folderSessions]) => (
                <div key={folder} className="space-y-2">
                  <div className="flex items-center gap-2 px-1">
                    <FolderIcon size={12} className="text-[var(--muted-foreground)]" />
                    <span className="text-[11px] font-semibold text-[var(--muted-foreground)]">{folder}</span>
                    <span className="text-[10px] text-[var(--muted-foreground)]">({folderSessions.length})</span>
                  </div>
                  {folderSessions.map((session) => (
                <div
                  key={session.id}
                  className={`group relative overflow-hidden rounded-lg border bg-[var(--background)] transition-colors hover:border-[var(--primary)]/60 hover:bg-[var(--accent)]/30 ${
                    activeSession?.id === session.id ? "border-[var(--primary)]" : ""
                  }`}
                >
                  <button
                    onClick={() => openSession(session.id)}
                    disabled={loading}
                    className="block min-h-20 w-full cursor-pointer px-3 py-3 pr-10 text-left disabled:cursor-wait disabled:opacity-70"
                  >
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <p className="truncate text-sm font-medium">{session.title}</p>
                          {session.title?.includes("Redo") ? (
                            <span className="shrink-0 rounded bg-blue-100 px-1 py-0.5 text-[9px] font-medium text-blue-700">Redo</span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                          {session.question_count} 题 · {session.status === "submitted" ? scoreLabel(session) : "In Progress"}
                        </p>
                        {(() => {
                          const status = session.status
                          // Prefer the exact wrong_count from the backend; fall
                          // back to the score-ratio approximation for sessions
                          // recorded before the field was introduced.
                          const wrongCount = session.wrong_count ?? (session.score != null && session.max_score
                            ? Math.round(((session.max_score - session.score) / session.max_score) * session.question_count)
                            : 0)
                          if (status === "submitted" && wrongCount > 0) {
                            return (
                              <span className="mt-1 inline-flex rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium text-rose-700">
                                待巩固 {wrongCount} 题
                              </span>
                            )
                          }
                          if (status === "active" && session.question_count > 0) {
                            return (
                              <span className="mt-1 inline-flex rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                                Incomplete
                              </span>
                            )
                          }
                          return null
                        })()}
                      </div>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] ${session.status === "submitted" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}`}>
                        {openingSessionId === session.id ? "Opening" : session.status === "submitted" ? "Submitted" : "In Progress"}
                      </span>
                    </div>
                  </button>
                  <button
                    onClick={() => deleteSession(session.id)}
                    disabled={loading}
                    className="absolute bottom-2 right-2 inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted-foreground)] hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                    title="Delete Test"
                    aria-label={`Delete Test：${session.title}`}
                  >
                    <Trash2 size={12} />
                  </button>
                  <div className="flex items-center gap-2 border-t bg-[var(--muted)]/20 px-3 py-2">
                    <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">Contents</span>
                    <select
                      value={session.folder || ""}
                      disabled={loading}
                      onChange={(e) => void moveSessionFolder(session.id, e.target.value)}
                      className="min-w-0 flex-1 rounded border bg-[var(--background)] px-1.5 py-1 text-[11px]"
                      title="Move to Custom Folder"
                    >
                      <option value="">Uncategorized</option>
                      {(existingFolders.includes(session.folder || "") || !session.folder
                        ? existingFolders
                        : [session.folder || "", ...existingFolders]
                      ).map((folder) => (
                        <option key={folder} value={folder}>{folder}</option>
                      ))}
                      <option value="__new__">+ New Folder…</option>
                    </select>
                  </div>
                </div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        </aside>

        <main className="min-h-0 overflow-hidden">
          {!activeSession || !currentQuestion ? (
            <div className="flex h-full items-center justify-center text-center text-[var(--muted-foreground)]">
              <div>
                <ClipboardCheck className="mx-auto mb-3 h-12 w-12 opacity-25" />
                <p className="text-base font-medium text-[var(--foreground)]">Create or open a test</p>
                <p className="mt-1 text-sm">The standalone answering interface, submission results, and knowledge point diagnostics will be shown here.</p>
              </div>
            </div>
          ) : (
            <TestWorkspace
              session={activeSession}
              currentIndex={currentIndex}
              setCurrentIndex={setCurrentIndex}
              answers={answers}
              setAnswer={setAnswer}
              confidences={confidences}
              setConfidence={setConfidences}
              answeredCount={answeredCount}
              submitting={submitting}
              onSubmit={submit}
              attemptsById={attemptsById}
              userId={userId}
              submitSummary={submitSummary}
              onExport={exportTest}
              onResetAnswers={resetAnswers}
              onRegenerateFromWrong={regenerateFromWrong}
            />
          )}
        </main>
      </div>
    </div>
  )
}

const DIFFICULTY_ORDER: Record<string, number> = {
  basic: 0,
  understanding: 1,
  application: 2,
  mixed: 3,
}

function computeWrongQuestions(session: TestSession): TestQuestion[] {
  if (!session.attempts) return []
  return session.questions.filter((q, i) => {
    const a = session.attempts[i]
    if (!a) return false
    // Clamp to a non-NaN ratio so ungraded questions (score / max_score
    // both 0) are not silently treated as wrong.
    const ratio = ((a.score || 0) / Math.max(1, a.max_score || 1))
    return ratio < 0.5
  })
}

function groupWrongQuestions(
  wrong: TestQuestion[],
): Array<{ key: string; title: string; questions: TestQuestion[] }> {
  /** Group by related_page (KC), largest first, ordered by pedagogical
   *  difficulty within each group. Questions without a related_page
   *  fall into a synthetic "Other" bucket so they still surface. */
  const groups = new Map<string, { title: string; questions: TestQuestion[] }>()
  for (const q of wrong) {
    const key = q.related_page || "__no_kc__"
    const title = q.related_page ? q.related_page.replace(/\.md$/, "") : "Other"
    if (!groups.has(key)) groups.set(key, { title, questions: [] })
    groups.get(key)!.questions.push(q)
  }
  const sorted = Array.from(groups.entries())
    .map(([key, value]) => ({ key, ...value }))
    .sort((a, b) => {
      // Largest group first; ties broken by alphabetical title.
      if (b.questions.length !== a.questions.length) {
        return b.questions.length - a.questions.length
      }
      return a.title.localeCompare(b.title)
    })
  for (const group of sorted) {
    group.questions.sort((a, b) => {
      const da = DIFFICULTY_ORDER[a.difficulty] ?? 3
      const db = DIFFICULTY_ORDER[b.difficulty] ?? 3
      if (da !== db) return da - db
      return a.prompt.localeCompare(b.prompt)
    })
  }
  return sorted
}

function TestWorkspace({
  session,
  currentIndex,
  setCurrentIndex,
  answers,
  setAnswer,
  confidences,
  setConfidence,
  answeredCount,
  submitting,
  onSubmit,
  attemptsById,
  userId,
  submitSummary,
  onExport,
  onResetAnswers,
  onRegenerateFromWrong,
}: {
  session: TestSession
  currentIndex: number
  setCurrentIndex: (index: number) => void
  answers: Record<string, string | string[]>
  setAnswer: (questionId: string, value: string | string[]) => void
  confidences: Record<string, number>
  setConfidence: Dispatch<SetStateAction<Record<string, number>>>
  answeredCount: number
  submitting: boolean
  onSubmit: () => void
  attemptsById: Map<string, TestSession["attempts"][number]>
  userId: string
  submitSummary: { total: number; perQuestion: { id: string; ms: number }[] } | null
  onExport: () => void
  onResetAnswers: () => void
  onRegenerateFromWrong: () => void
}) {
  const question = session.questions[currentIndex]
  const wrongQuestions = computeWrongQuestions(session)
  const attempt = attemptsById.get(question.id)
  const submitted = session.status === "submitted"
  const resultPercent = session.score != null && session.max_score ? Math.round((session.score / session.max_score) * 100) : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold">{session.title}</h2>
            <p className="text-sm text-[var(--muted-foreground)]">
              <span className="inline-flex items-center gap-1">
                {session.title?.includes("Redo") ? (
                  <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">Redo</span>
                ) : null}
                {session.questions.length} 题 · {questionTypeSummary(session)} · 已答 {answeredCount} 题 · 学习者 <span className="font-medium text-[var(--foreground)]">{userId}</span>
              </span>
              {submitted && resultPercent != null ? ` · 得分 ${scoreLabel(session)} (${resultPercent}%)` : ""}
            {submitted ? (
              <button
                type="button"
                onClick={onExport}
                className="ml-2 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                title="Export test results as Markdown"
              >
                <Download size={10} /> Export
              </button>
            ) : null}
            {submitted ? (
              <button
                type="button"
                onClick={onResetAnswers}
                className="ml-2 inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] text-amber-700 hover:bg-amber-100"
                title="Clear answers and confidence and start over. Submitted scores will remain in the conversation."
              >
                <RotateCcw size={10} /> Retry Answer
              </button>
            ) : null}
            {submitted ? (
              <button
                type="button"
                onClick={onRegenerateFromWrong}
                className="ml-2 inline-flex items-center gap-1 rounded border border-blue-300 bg-blue-50 px-2 py-0.5 text-[10px] text-blue-700 hover:bg-blue-100"
                title="Automatically create a new test from this test's wrong answers, focusing on weak points."
              >
                <RefreshCw size={10} /> Wrong Questions Only
              </button>
            ) : null}
            </p>
          </div>
          {!submitted && (
            <button
              onClick={onSubmit}
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-md bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
              提交测试
            </button>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {session.questions.map((item, index) => {
            const itemAttempt = attemptsById.get(item.id)
            const answered = answerToText(answers[item.id]).trim()
            const dur = submitSummary?.perQuestion[index]?.ms
            return (
              <button
                key={item.id}
                onClick={() => setCurrentIndex(index)}
                title={dur && dur > 0 ? `用时 ${formatDuration(dur)}` : undefined}
                className={`relative h-8 min-w-8 rounded-md border px-2 text-xs ${
                  index === currentIndex
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : itemAttempt
                      ? levelClass(itemAttempt.level)
                      : answered
                        ? "border-blue-200 bg-blue-50 text-blue-700"
                        : "hover:bg-[var(--accent)]"
                }`}
              >
                {index + 1}
                {dur && dur > 0 ? (
                  <span className="ml-1 text-[9px] opacity-70">·{formatDuration(dur)}</span>
                ) : null}
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-4xl space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-full bg-[var(--muted)] px-2.5 py-1 text-[var(--muted-foreground)]">{questionTypeLabel(question.type)}</span>
            <span className="text-[var(--muted-foreground)]">第 {currentIndex + 1} / {session.questions.length} 题</span>
          </div>
          <SourceLinks question={question} />

          <section className="rounded-lg border bg-[var(--background)] p-5">
            <Markdown>{question.prompt}</Markdown>
          </section>

          <AnswerInput
            question={question}
            value={answers[question.id]}
            disabled={submitted}
            onChange={(value) => setAnswer(question.id, value)}
          />

          {!submitted && (
            <section className="rounded-lg border p-4">
              <h3 className="mb-3 text-sm font-semibold">Answer confidence</h3>
              <ConfidenceSlider
                value={confidences[question.id] ?? 3}
                onChange={(value) =>
                  setConfidence((prev) => ({ ...prev, [question.id]: value }))
                }
              />
            </section>
          )}

          {attempt && (
            <section className={`rounded-lg border p-4 ${levelClass(attempt.level)}`}>
              <div className="mb-2 flex items-center gap-2 font-medium">
                {attempt.level === "good" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                批改结果：{attempt.score}/{attempt.max_score}
                {attempt.confidence != null && attempt.confidence !== undefined ? (
                  <span
                    className={
                      "ml-2 inline-flex items-center rounded px-2 py-0.5 text-xs " +
                      (attempt.score >= 0.5
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-rose-100 text-rose-700")
                    }
                    title="Confidence vs correctness"
                  >
                    把握 {attempt.confidence}/5
                    {attempt.score >= 0.7 && attempt.confidence >= 4 ? " · Well calibrated" : null}
                    {attempt.score < 0.5 && attempt.confidence >= 4 ? " · Overconfident" : null}
                    {attempt.score >= 0.7 && attempt.confidence <= 2 ? " · Conservative" : null}
                  </span>
                ) : null}
              </div>
              <p className="text-sm leading-relaxed">{attempt.feedback}</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-medium opacity-70">Your answer</p>
                  <div className="rounded border bg-[var(--background)]/70 p-2 text-sm">
                    {answerToText(attempt.user_answer) ? <InlineMarkdown>{answerToText(attempt.user_answer)}</InlineMarkdown> : "Unanswered"}
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium opacity-70">Reference Answer</p>
                  <div className="rounded border bg-[var(--background)]/70 p-2 text-sm">
                    {answerToText(attempt.correct_answer) ? <InlineMarkdown>{answerToText(attempt.correct_answer)}</InlineMarkdown> : "See Explanation"}
                  </div>
                </div>
              </div>
            </section>
          )}

          {submitted && question.explanation && (
            <section className="rounded-lg border p-4">
              <h3 className="mb-2 text-sm font-semibold">Analysis</h3>
              <Markdown>{question.explanation}</Markdown>
              <div className="mt-3 border-t pt-3">
                <SourceLinks question={question} />
              </div>
            </section>
          )}

          {(() => {
            const masteredQuestions = session.questions.filter((q, i) => {
              const a = (session.attempts || [])[i]
              return a && (a.score || 0) / Math.max(1, a.max_score || 1) >= 0.7
            })
            if (submitted && masteredQuestions.length > 0) {
              return (
                <section className="rounded-lg border border-emerald-200 bg-emerald-50/30 p-4">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h3
                      className="text-sm font-semibold text-emerald-800"
                      title="Questions scored ≥ 70% in this simulation indicate stable mastery"
                    >
                      Mastered in this session
                    </h3>
                    <span className="text-[10px] text-emerald-600">{masteredQuestions.length} 题Mastered</span>
                  </div>
                  <ul className="space-y-1.5">
                    {masteredQuestions.map((q) => {
                      const origIdx = session.questions.findIndex((x) => x.id === q.id)
                      const a = (session.attempts || [])[origIdx]
                      return (
                        <li key={q.id}>
                          <button
                            type="button"
                            onClick={() => setCurrentIndex(origIdx)}
                            className="w-full rounded border border-emerald-200 bg-white px-2 py-1.5 text-left text-[12px] text-emerald-700 hover:bg-emerald-50"
                          >
                            <div className="flex items-center gap-2">
                              <span className="shrink-0 font-medium">第 {origIdx + 1} 题</span>
                              {a ? (
                                <span className="shrink-0 text-[10px] text-emerald-500">
                                  · {a.score}/{a.max_score}
                                </span>
                              ) : null}
                            </div>
                            <p className="line-clamp-1 text-foreground">{q.prompt.replace(/\n+/g, " ")}</p>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )
            }
            return null
          })()}

          {submitted && wrongQuestions.length > 0
            ? (() => {
                const groups = groupWrongQuestions(wrongQuestions)
                return (
                  <section className="rounded-lg border border-rose-200 bg-rose-50/30 p-4">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-rose-800">Review This Session's Mistakes</h3>
                      {(() => {
                        const masteredCount = session.questions.filter((_, i) => {
                          const a = (session.attempts || [])[i]
                          return a && (a.score || 0) / Math.max(1, a.max_score || 1) >= 0.7
                        }).length
                        if (masteredCount === 0) return null
                        return (
                          <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                            Mastered in this session {masteredCount} 题
                          </span>
                        )
                      })()}
                      <span className="text-[10px] text-rose-600">{wrongQuestions.length} 道待巩固 · {groups.length} 个知识组件</span>
                    </div>
                    <div className="space-y-3">
                      {groups.map((group) => (
                        <div key={group.key} className="rounded-md border border-rose-100 bg-white/60 p-2">
                          <div className="mb-1 flex items-center gap-1 text-[11px] font-medium text-rose-700">
                            <Target size={11} />
                            <span className="truncate">{group.title}</span>
                            <span className="ml-auto text-[10px] text-rose-500">{group.questions.length} 道</span>
                          </div>
                          <ul className="space-y-1">
                            {group.questions.map((q) => {
                              const a = attemptsById.get(q.id)
                              const origIdx = session.questions.findIndex((x) => x.id === q.id)
                              const difficultyLabel =
                                q.difficulty === "basic" ? "Basic"
                                  : q.difficulty === "understanding" ? "Understood"
                                  : q.difficulty === "application" ? "Apply"
                                  : "Mixed"
                              return (
                                <li key={q.id}>
                                  <button
                                    type="button"
                                    onClick={() => setCurrentIndex(origIdx)}
                                    className="w-full rounded border border-rose-200 bg-white px-2 py-1.5 text-left text-[12px] text-rose-700 hover:bg-rose-50"
                                  >
                                    <div className="flex items-center gap-2">
                                      <span className="shrink-0 font-medium">第 {origIdx + 1} 题</span>
                                      <span className="shrink-0 rounded bg-rose-50 px-1 py-0.5 text-[10px] text-rose-600">{difficultyLabel}</span>
                                      {a ? (
                                        <span className="shrink-0 text-[10px] text-rose-500">
                                          · {a.score}/{a.max_score}
                                        </span>
                                      ) : null}
                                    </div>
                                    <p className="line-clamp-2 text-foreground">{q.prompt.replace(/\n+/g, " ")}</p>
                                    {a ? (
                                      <p className="line-clamp-1 mt-0.5 text-[11px] text-rose-500">
                                        <span className="text-rose-700">Your answer: </span>{answerToText(a.user_answer) || "(Unanswered)"}
                                        <span className="ml-2 text-rose-700">Correct: </span>{answerToText(a.correct_answer) || "(无)"}
                                      </p>
                                    ) : null}
                                  </button>
                                </li>
                              )
                            })}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </section>
                )
              })()
            : null}
        </div>
      </div>

      <div className="shrink-0 border-t px-5 py-3">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3">
          <button
            onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
            disabled={currentIndex === 0}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm disabled:opacity-40"
          >
            <ChevronLeft size={16} />
            Previous
          </button>
          <button
            onClick={() => setCurrentIndex(Math.min(session.questions.length - 1, currentIndex + 1))}
            disabled={currentIndex === session.questions.length - 1}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm disabled:opacity-40"
          >
            Next Question
            <ChevronRight size={16} />
          </button>
        </div>
        <p className="mt-2 text-center text-[10px] text-[var(--muted-foreground)]">
          Shortcuts: 1-9 / A-D to select · ← → to switch questions · ⌘/Ctrl + Enter to submit
        </p>
      </div>
    </div>
  )
}

function AnswerInput({
  question,
  value,
  disabled,
  onChange,
}: {
  question: TestSession["questions"][number]
  value: string | string[] | undefined
  disabled: boolean
  onChange: (value: string | string[]) => void
}) {
  if (question.type === "multiple_choice" && question.options.length > 0) {
    const current = answerToText(value)
    return (
      <section className="rounded-lg border p-4">
        <h3 className="mb-3 text-sm font-semibold">Answer</h3>
        <div className="grid gap-2">
          {question.options.map((option) => {
            const key = option.match(/^\s*([A-Ha-h])/)?.[1]?.toUpperCase() || option
            const selected = current === key
            return (
              <button
                key={option}
                onClick={() => onChange(key)}
                disabled={disabled}
                className={`rounded-lg border px-3 py-3 text-left text-sm transition-colors ${
                  selected ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "hover:bg-[var(--accent)]"
                } disabled:cursor-default`}
              >
                <InlineMarkdown>{option}</InlineMarkdown>
              </button>
            )
          })}
        </div>
      </section>
    )
  }

  if (question.type === "fill_blank") {
    const count = Math.max(1, question.blanks || 1)
    const values = Array.isArray(value) ? value : answerToText(value) ? [answerToText(value)] : []
    return (
      <section className="rounded-lg border p-4">
        <h3 className="mb-3 text-sm font-semibold">Answer</h3>
        <div className="grid gap-2">
          {Array.from({ length: count }).map((_, index) => (
            <label key={index} className="block">
              <span className="mb-1 block text-xs text-[var(--muted-foreground)]">第 {index + 1} 空</span>
              <input
                value={values[index] || ""}
                onChange={(e) => {
                  const next = [...values]
                  next[index] = e.target.value
                  onChange(next)
                }}
                disabled={disabled}
                placeholder="Enter your answer..."
                className="w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)] disabled:opacity-70"
              />
            </label>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-lg border p-4">
      <h3 className="mb-3 text-sm font-semibold">Answer</h3>
      <textarea
        value={answerToText(value)}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="Write your solution approach or answer..."
        className="min-h-40 w-full resize-y rounded-md border bg-[var(--background)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--primary)] disabled:opacity-70"
      />
    </section>
  )
}
