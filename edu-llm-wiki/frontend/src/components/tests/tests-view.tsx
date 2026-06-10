import { useEffect, useMemo, useState } from "react"
import { api, type TestCreateRequest, type TestSession, type TestSummary } from "@/lib/api"
import { InlineMarkdown, Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { useAppStore } from "@/stores/app-store"
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
  Trash2,
} from "lucide-react"

const QUESTION_TYPES = [
  { id: "multiple_choice", label: "选择" },
  { id: "fill_blank", label: "填空" },
  { id: "short_answer", label: "简答" },
]

const DIFFICULTIES = [
  { id: "mixed", label: "混合" },
  { id: "basic", label: "基础" },
  { id: "understanding", label: "理解" },
  { id: "application", label: "应用" },
]

function answerToText(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value.filter(Boolean).join("；")
  return value || ""
}

function scoreLabel(session: TestSummary | TestSession): string {
  if (session.score == null || session.max_score == null) return "未提交"
  return `${session.score}/${session.max_score}`
}

function levelClass(level: string): string {
  if (level === "good") return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/25 dark:text-emerald-200"
  if (level === "partial") return "border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-950/25 dark:text-amber-200"
  return "border-red-200 bg-red-50 text-red-700 dark:bg-red-950/25 dark:text-red-200"
}

function questionTypeLabel(type: string): string {
  if (type === "multiple_choice") return "选择题"
  if (type === "fill_blank") return "填空题"
  return "简答题"
}

export function TestsView() {
  const [sessions, setSessions] = useState<TestSummary[]>([])
  const [sources, setSources] = useState<{ name: string; size: number; modified: number }[]>([])
  const [activeSession, setActiveSession] = useState<TestSession | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [loading, setLoading] = useState(false)
  const [openingSessionId, setOpeningSessionId] = useState<string | null>(null)
  const operations = useAppStore((s) => s.operations)
  const beginOperation = useAppStore((s) => s.beginOperation)
  const endOperation = useAppStore((s) => s.endOperation)
  const creatingTest = Boolean(operations["tests:create"])
  const submitting = activeSession ? Boolean(operations[`tests:submit:${activeSession.id}`]) : false
  const [form, setForm] = useState<TestCreateRequest>({
    scope: "wiki",
    source: null,
    question_count: 5,
    question_types: ["multiple_choice", "fill_blank", "short_answer"],
    difficulty: "mixed",
    mode: "practice",
  })

  const currentQuestion = activeSession?.questions[currentIndex] || null
  const attemptsById = useMemo(() => {
    const map = new Map<string, TestSession["attempts"][number]>()
    for (const attempt of activeSession?.attempts || []) map.set(attempt.question_id, attempt)
    return map
  }, [activeSession])

  const answeredCount = useMemo(() => {
    if (!activeSession) return 0
    return activeSession.questions.filter((question) => answerToText(answers[question.id]).trim()).length
  }, [activeSession, answers])

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

  const createTest = async () => {
    beginOperation("tests:create", "生成测试中")
    try {
      const session = await api.createTest({
        ...form,
        title: form.title?.trim() || undefined,
        source: form.scope === "source" ? form.source : null,
        // Auto-inject a fresh seed each time so the backend can drive
        // diversity instead of returning a near-identical question set.
        seed: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
      setActiveSession(session)
      setCurrentIndex(0)
      setAnswers({})
      await loadData()
      toast({ type: "success", message: `已生成 ${session.questions.length} 道测试题` })
    } catch (e: any) {
      toast({ type: "error", message: `生成测试失败: ${e?.message || e}` })
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
      for (const attempt of session.attempts || []) restored[attempt.question_id] = attempt.user_answer
      setAnswers(restored)
    } catch (e: any) {
      toast({ type: "error", message: `打开测试失败: ${e?.message || e}` })
    } finally {
      setLoading(false)
      setOpeningSessionId(null)
    }
  }

  const deleteSession = async (id: string) => {
    try {
      await api.deleteTest(id)
      if (activeSession?.id === id) {
        setActiveSession(null)
        setAnswers({})
      }
      await loadData()
    } catch (e: any) {
      toast({ type: "error", message: `删除测试失败: ${e?.message || e}` })
    }
  }

  const setAnswer = (questionId: string, value: string | string[]) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }))
  }

  const submit = async () => {
    if (!activeSession) return
    const key = `tests:submit:${activeSession.id}`
    beginOperation(key, "提交测试中")
    try {
      const session = await api.submitTest(activeSession.id, answers)
      setActiveSession(session)
      await loadData()
      toast({ type: "success", message: `测试已提交：${scoreLabel(session)}` })
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
            <p className="text-sm text-[var(--muted-foreground)]">阶段测评、AI 批改和错题诊断</p>
          </div>
          <button
            onClick={loadData}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          >
            <RefreshCw size={14} />
            刷新
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r bg-[var(--sidebar)] p-4">
          <section className="rounded-lg border bg-[var(--background)] p-3">
            <div className="mb-3 flex items-center gap-2">
              <Plus size={16} className="text-[var(--primary)]" />
              <h2 className="text-sm font-semibold">创建测试</h2>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">标题</span>
                <input
                  value={form.title || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                  placeholder="可选：材料电学阶段测试"
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">范围</span>
                <select
                  value={form.scope}
                  onChange={(e) => setForm((prev) => ({ ...prev, scope: e.target.value as "wiki" | "source" }))}
                  className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm"
                >
                  <option value="wiki">整个 Wiki</option>
                  <option value="source">指定文档</option>
                </select>
              </label>

              {form.scope === "source" && (
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">文档</span>
                  <select
                    value={form.source || ""}
                    onChange={(e) => setForm((prev) => ({ ...prev, source: e.target.value || null }))}
                    className="w-full rounded-md border bg-[var(--background)] px-2.5 py-2 text-sm"
                  >
                    <option value="">选择来源文件</option>
                    {sources.map((source) => (
                      <option key={source.name} value={source.name}>{source.name}</option>
                    ))}
                  </select>
                </label>
              )}

              <div>
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">题量</span>
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
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">题型</span>
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
                <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">难度</span>
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
                {creatingTest ? "生成中..." : "生成测试"}
              </button>
            </div>
          </section>

          <section className="mt-4">
            <div className="mb-2 flex items-center gap-2">
              <FileText size={15} className="text-[var(--muted-foreground)]" />
              <h2 className="text-sm font-semibold">测试历史</h2>
            </div>
            <div className="space-y-2">
              {sessions.length === 0 && (
                <p className="rounded-md border border-dashed px-3 py-5 text-center text-sm text-[var(--muted-foreground)]">暂无测试记录</p>
              )}
              {sessions.map((session) => (
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
                        <p className="truncate text-sm font-medium">{session.title}</p>
                        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                          {session.question_count} 题 · {session.status === "submitted" ? scoreLabel(session) : "进行中"}
                        </p>
                      </div>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] ${session.status === "submitted" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}`}>
                        {openingSessionId === session.id ? "打开中" : session.status === "submitted" ? "已提交" : "进行中"}
                      </span>
                    </div>
                  </button>
                  <button
                    onClick={() => deleteSession(session.id)}
                    disabled={loading}
                    className="absolute bottom-2 right-2 inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted-foreground)] hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                    title="删除测试"
                    aria-label={`删除测试：${session.title}`}
                  >
                    <Trash2 size={12} />
                  </button>
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
                <p className="text-base font-medium text-[var(--foreground)]">创建或打开一个测试</p>
                <p className="mt-1 text-sm">这里会显示独立答题界面、提交结果和知识点诊断。</p>
              </div>
            </div>
          ) : (
            <TestWorkspace
              session={activeSession}
              currentIndex={currentIndex}
              setCurrentIndex={setCurrentIndex}
              answers={answers}
              setAnswer={setAnswer}
              answeredCount={answeredCount}
              submitting={submitting}
              onSubmit={submit}
              attemptsById={attemptsById}
            />
          )}
        </main>
      </div>
    </div>
  )
}

function TestWorkspace({
  session,
  currentIndex,
  setCurrentIndex,
  answers,
  setAnswer,
  answeredCount,
  submitting,
  onSubmit,
  attemptsById,
}: {
  session: TestSession
  currentIndex: number
  setCurrentIndex: (index: number) => void
  answers: Record<string, string | string[]>
  setAnswer: (questionId: string, value: string | string[]) => void
  answeredCount: number
  submitting: boolean
  onSubmit: () => void
  attemptsById: Map<string, TestSession["attempts"][number]>
}) {
  const question = session.questions[currentIndex]
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
              {session.questions.length} 题 · 已答 {answeredCount} 题
              {submitted && resultPercent != null ? ` · 得分 ${scoreLabel(session)} (${resultPercent}%)` : ""}
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
            return (
              <button
                key={item.id}
                onClick={() => setCurrentIndex(index)}
                className={`h-8 min-w-8 rounded-md border px-2 text-xs ${
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
            {question.related_page && <span className="rounded bg-[var(--muted)] px-2 py-0.5 text-xs text-[var(--muted-foreground)]">{question.related_page}</span>}
          </div>

          <section className="rounded-lg border bg-[var(--background)] p-5">
            <Markdown>{question.prompt}</Markdown>
          </section>

          <AnswerInput
            question={question}
            value={answers[question.id]}
            disabled={submitted}
            onChange={(value) => setAnswer(question.id, value)}
          />

          {attempt && (
            <section className={`rounded-lg border p-4 ${levelClass(attempt.level)}`}>
              <div className="mb-2 flex items-center gap-2 font-medium">
                {attempt.level === "good" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                批改结果：{attempt.score}/{attempt.max_score}
              </div>
              <p className="text-sm leading-relaxed">{attempt.feedback}</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-medium opacity-70">你的答案</p>
                  <div className="rounded border bg-[var(--background)]/70 p-2 text-sm">
                    {answerToText(attempt.user_answer) ? <InlineMarkdown>{answerToText(attempt.user_answer)}</InlineMarkdown> : "未作答"}
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium opacity-70">参考答案</p>
                  <div className="rounded border bg-[var(--background)]/70 p-2 text-sm">
                    {answerToText(attempt.correct_answer) ? <InlineMarkdown>{answerToText(attempt.correct_answer)}</InlineMarkdown> : "见解析"}
                  </div>
                </div>
              </div>
            </section>
          )}

          {(submitted || session.mode === "practice") && question.explanation && (
            <section className="rounded-lg border p-4">
              <h3 className="mb-2 text-sm font-semibold">解析</h3>
              <Markdown>{question.explanation}</Markdown>
            </section>
          )}
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
            上一题
          </button>
          <button
            onClick={() => setCurrentIndex(Math.min(session.questions.length - 1, currentIndex + 1))}
            disabled={currentIndex === session.questions.length - 1}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm disabled:opacity-40"
          >
            下一题
            <ChevronRight size={16} />
          </button>
        </div>
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
        <h3 className="mb-3 text-sm font-semibold">作答</h3>
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
        <h3 className="mb-3 text-sm font-semibold">作答</h3>
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
                placeholder="填写答案..."
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
      <h3 className="mb-3 text-sm font-semibold">作答</h3>
      <textarea
        value={answerToText(value)}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="写下你的解题思路或答案..."
        className="min-h-40 w-full resize-y rounded-md border bg-[var(--background)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--primary)] disabled:opacity-70"
      />
    </section>
  )
}
