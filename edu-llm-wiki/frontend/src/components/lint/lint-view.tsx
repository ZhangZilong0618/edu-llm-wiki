import { useState } from "react"
import {
  Activity,
  AlertTriangle,
  Unlink,
  Lightbulb,
  BookOpen,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  TrendingUp,
} from "lucide-react"

interface LintResult {
  health_score: number
  contradictions: { pages: string[]; description: string }[]
  orphans: { path: string; issue: string }[]
  missing_pages: string[]
  knowledge_gaps: string[]
  suggestions: string[]
  summary: string
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-600"
  if (score >= 60) return "text-amber-600"
  return "text-red-500"
}

function scoreBg(score: number): string {
  if (score >= 80) return "bg-emerald-500"
  if (score >= 60) return "bg-amber-500"
  return "bg-red-500"
}

function scoreRing(score: number): string {
  if (score >= 80) return "stroke-emerald-500"
  if (score >= 60) return "stroke-amber-500"
  return "stroke-red-500"
}

function ScoreCircle({ score }: { score: number }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference

  return (
    <div className="relative w-32 h-32 flex items-center justify-center">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={radius} fill="none" strokeWidth="8" className="stroke-[var(--muted)]" />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          strokeWidth="8"
          strokeLinecap="round"
          className={`${scoreRing(score)} transition-all duration-1000`}
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: offset,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-bold ${scoreColor(score)}`}>{score}</span>
        <span className="text-xs text-[var(--muted-foreground)]">/ 100</span>
      </div>
    </div>
  )
}

function SectionCard({
  icon: Icon,
  title,
  count,
  color,
  children,
  defaultOpen = true,
}: {
  icon: React.ElementType
  title: string
  count: number
  color: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="rounded-lg border bg-[var(--background)] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 hover:bg-[var(--muted)]/50 transition-colors"
      >
        <Icon className={`h-4 w-4 ${color}`} />
        <span className="text-sm font-medium flex-1 text-left">{title}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded-full ${count > 0 ? "bg-[var(--muted)]" : "bg-emerald-500/10 text-emerald-600"}`}>
          {count}
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-[var(--muted-foreground)]" /> : <ChevronRight className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />}
      </button>
      {open && count > 0 && (
        <div className="border-t px-4 py-3 space-y-2">{children}</div>
      )}
      {open && count === 0 && (
        <div className="border-t px-4 py-3 flex items-center gap-2 text-xs text-emerald-600">
          <CheckCircle2 className="h-3.5 w-3.5" />
          <span>No issues found</span>
        </div>
      )}
    </div>
  )
}

export function LintView() {
  const [result, setResult] = useState<LintResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runLint = async () => {
    setLoading(true)
    setError(null)
    try {
      const { api } = await import("@/lib/api")
      const r = (await api.runLint()) as unknown as LintResult
      setResult(r)
    } catch (e: any) {
      setError(e.message || "Failed to run health check")
    }
    setLoading(false)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-[var(--muted-foreground)]" />
          <span className="text-sm font-medium">Knowledge Base Health Check</span>
        </div>
        <button
          onClick={runLint}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-xs hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Analyzing..." : "Run Check"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/20 dark:border-red-900 px-4 py-3 flex items-center gap-2 text-sm text-red-600">
            <XCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {!result && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-full text-center text-[var(--muted-foreground)] gap-3">
            <Activity className="h-12 w-12 opacity-20" />
            <div>
              <p className="text-sm font-medium">Run a health check to analyze your knowledge base</p>
              <p className="text-xs mt-1">Detects contradictions, orphan pages, knowledge gaps, and more</p>
            </div>
          </div>
        )}

        {loading && !result && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-[var(--muted-foreground)]">
            <RefreshCw className="h-8 w-8 animate-spin opacity-40" />
            <p className="text-sm">Analyzing knowledge base with LLM...</p>
          </div>
        )}

        {result && (
          <>
            {/* Score + Summary */}
            <div className="flex items-center gap-6 rounded-lg border p-5 bg-[var(--background)]">
              <ScoreCircle score={result.health_score} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <TrendingUp className={`h-4 w-4 ${scoreColor(result.health_score)}`} />
                  <span className={`text-sm font-semibold ${scoreColor(result.health_score)}`}>
                    {result.health_score >= 80 ? "Healthy" : result.health_score >= 60 ? "Needs Attention" : "Critical Issues"}
                  </span>
                </div>
                <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">{result.summary}</p>
              </div>
            </div>

            {/* Issue Sections */}
            <div className="space-y-3">
              <SectionCard
                icon={AlertTriangle}
                title="Contradictions"
                count={result.contradictions?.length ?? 0}
                color="text-red-500"
                defaultOpen={false}
              >
                {result.contradictions?.map((c, i) => (
                  <div key={i} className="rounded-md bg-red-50 dark:bg-red-950/20 px-3 py-2">
                    <div className="flex flex-wrap gap-1 mb-1">
                      {c.pages?.map((p) => (
                        <span key={p} className="text-xs font-mono bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 rounded">
                          {p.split("/").pop()}
                        </span>
                      ))}
                    </div>
                    <p className="text-xs text-[var(--muted-foreground)]">{c.description}</p>
                  </div>
                ))}
              </SectionCard>

              <SectionCard
                icon={Unlink}
                title="Orphan Pages"
                count={result.orphans?.length ?? 0}
                color="text-amber-500"
                defaultOpen={false}
              >
                {result.orphans?.map((o, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="font-mono bg-amber-100 dark:bg-amber-900/30 px-1.5 py-0.5 rounded shrink-0">
                      {o.path?.split("/").pop()}
                    </span>
                    <span className="text-[var(--muted-foreground)]">{o.issue}</span>
                  </div>
                ))}
              </SectionCard>

              <SectionCard
                icon={BookOpen}
                title="Missing Pages"
                count={result.missing_pages?.length ?? 0}
                color="text-blue-500"
                defaultOpen={false}
              >
                <div className="flex flex-wrap gap-1.5">
                  {result.missing_pages?.map((p, i) => (
                    <span key={i} className="text-xs bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-900 px-2 py-1 rounded-md">
                      {p}
                    </span>
                  ))}
                </div>
              </SectionCard>

              <SectionCard
                icon={AlertTriangle}
                title="Knowledge Gaps"
                count={result.knowledge_gaps?.length ?? 0}
                color="text-orange-500"
                defaultOpen={false}
              >
                {result.knowledge_gaps?.map((g, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-orange-500 mt-0.5">-</span>
                    <span className="text-[var(--muted-foreground)]">{g}</span>
                  </div>
                ))}
              </SectionCard>

              <SectionCard
                icon={Lightbulb}
                title="Suggestions"
                count={result.suggestions?.length ?? 0}
                color="text-violet-500"
                defaultOpen={true}
              >
                {result.suggestions?.map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-violet-500 font-bold mt-0.5">{i + 1}.</span>
                    <span className="text-[var(--muted-foreground)] leading-relaxed">{s}</span>
                  </div>
                ))}
              </SectionCard>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
