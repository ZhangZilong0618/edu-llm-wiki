import { useEffect, useRef, useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"
import { CheckCircle2, ChevronDown, ChevronRight, HelpCircle, RotateCcw } from "lucide-react"

function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/[#*_`>$\\{}[\]().,，。；;：:！？!?-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

function answerScore(answer: string, solution: string): number | null {
  const userWords = new Set(plainText(answer).toLowerCase().split(/\s+/).filter((w) => w.length >= 2))
  const solutionWords = plainText(solution).toLowerCase().split(/\s+/).filter((w) => w.length >= 2)
  if (userWords.size === 0 || solutionWords.length === 0) return null
  const important = solutionWords.slice(0, 80)
  const overlap = important.filter((word) => userWords.has(word)).length
  return Math.min(100, Math.round((overlap / Math.max(6, Math.min(important.length, 24))) * 100))
}

function ExerciseContent({ content }: { content: string }) {
  const [showAnswer, setShowAnswer] = useState(false)
  const [showHint, setShowHint] = useState(false)
  const [userAnswer, setUserAnswer] = useState("")
  const [checked, setChecked] = useState(false)
  const [done, setDone] = useState(false)

  const parts = content.split(/(?=##\s*(?:解|答案|Answer|Solution|解答))/i)
  const question = parts[0] || content
  const referenceAnswer = parts.length > 1 ? parts.slice(1).join("\n") : null
  const score = checked && referenceAnswer ? answerScore(userAnswer, referenceAnswer) : null
  const feedback = score == null
    ? "Write your answer first, then check it against the solution."
    : score >= 70
      ? "Looks close to the reference answer. Now compare details below."
      : score >= 35
        ? "Part of the idea is there. Review the key terms in the solution."
        : "This answer may be missing the main idea. Try using the hint before revealing the solution."
  const hint = plainText(question).split(/\s+/).slice(0, 18).join(" ")

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">题目</h3>
        <Markdown>{question}</Markdown>
      </div>

      <div className="rounded-md border p-3">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase">作答</h3>
          {done && <span className="ml-auto text-[10px] text-emerald-600">completed</span>}
        </div>
        <textarea
          value={userAnswer}
          onChange={(e) => {
            setUserAnswer(e.target.value)
            setChecked(false)
          }}
          placeholder="在这里写你的解题思路或答案..."
          className="min-h-28 w-full resize-y rounded-md border bg-[var(--background)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            onClick={() => setChecked(true)}
            disabled={!userAnswer.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
          >
            <CheckCircle2 size={13} />
            Check
          </button>
          <button
            onClick={() => setShowHint((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <HelpCircle size={13} />
            Hint
          </button>
          <button
            onClick={() => {
              setUserAnswer("")
              setChecked(false)
              setShowAnswer(false)
              setDone(false)
            }}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <RotateCcw size={13} />
            Reset
          </button>
          <button
            onClick={() => setDone(true)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-emerald-500 px-3 py-1.5 text-xs text-emerald-600 hover:bg-emerald-50"
          >
            Mark Done
          </button>
        </div>
        {showHint && (
          <p className="mt-2 rounded bg-[var(--muted)] px-2 py-1.5 text-xs text-[var(--muted-foreground)]">
            先抓住题目关键词：{hint || "找出已知量、未知量，以及要用到的概念或公式。"}
          </p>
        )}
        {checked && (
          <p className="mt-2 rounded bg-[var(--muted)] px-2 py-1.5 text-xs text-[var(--muted-foreground)]">
            {feedback}
          </p>
        )}
      </div>

      {referenceAnswer ? (
        <div className="border-t pt-3">
          <button
            onClick={() => setShowAnswer((v) => !v)}
            className="flex items-center gap-1.5 text-sm font-medium text-emerald-600 hover:text-emerald-700 transition-colors"
          >
            {showAnswer ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            {showAnswer ? "Hide Answer" : "Show Answer"}
          </button>
          {showAnswer && (
            <div className="mt-2 pl-3 border-l-2 border-emerald-300 dark:border-emerald-700">
              <Markdown>{referenceAnswer}</Markdown>
            </div>
          )}
        </div>
      ) : (
        <div className="border-t pt-3">
          <p className="text-xs text-[var(--muted-foreground)] italic">No answer section found</p>
        </div>
      )}
    </div>
  )
}

export function PreviewPanel() {
  const selectedPage = useAppStore((s) => s.selectedPage)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const setSelectedSource = useAppStore((s) => s.setSelectedSource)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, 0)
  }, [selectedPage?.path, selectedSource?.filename])

  if (selectedSource) {
    const isPdf = selectedSource.extension === ".pdf" && selectedSource.view_url

    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="shrink-0 p-3 border-b flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-orange-100 text-orange-700">
            source
          </span>
          <h2 className="text-sm font-semibold truncate">{selectedSource.filename}</h2>
          <button
            onClick={() => setSelectedSource(null)}
            className="ml-auto text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            title="Close source preview"
          >
            &times;
          </button>
        </div>

        <div className="flex-1 overflow-y-auto" ref={scrollRef}>
          {isPdf ? (
            <iframe
              src={selectedSource.view_url!}
              className="w-full h-full border-0"
              title={selectedSource.filename}
              style={{ minHeight: "80vh" }}
            />
          ) : (
            <div className="p-4">
              {selectedSource.images.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">Images</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {selectedSource.images.map((url, i) => (
                      <img
                        key={i}
                        src={url}
                        alt={`Image ${i + 1}`}
                        className="w-full rounded border border-[var(--border)]"
                        loading="lazy"
                      />
                    ))}
                  </div>
                </div>
              )}
              {selectedSource.content && (
                <Markdown>{selectedSource.content}</Markdown>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (!selectedPage) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
        <p>Select a page to preview</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-3 border-b">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
            {selectedPage.page_type}
          </span>
          <h2 className="text-sm font-semibold truncate">{selectedPage.title}</h2>
        </div>
        {selectedPage.sources.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {selectedPage.sources.map((s) => (
              <span key={s} className="px-1.5 py-0.5 text-[10px] rounded bg-[var(--muted)] text-[var(--muted-foreground)]">
                {s}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4" ref={selectedPage ? scrollRef : undefined}>
        {selectedPage.page_type === "exercise" ? (
          <ExerciseContent content={selectedPage.content || ""} />
        ) : (
          <Markdown>{selectedPage.content || "*No content*"}</Markdown>
        )}
      </div>
    </div>
  )
}
