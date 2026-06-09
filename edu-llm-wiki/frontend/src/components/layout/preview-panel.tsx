import { useEffect, useRef, useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"
import { ChevronDown, ChevronRight, Play } from "lucide-react"

function ExerciseContent({ content }: { content: string }) {
  const [showAnswer, setShowAnswer] = useState(false)
  const [activeView] = useAppStore((s) => [s.activeView])

  const parts = content.split(/(?=##\s*(?:解|答案|Answer|Solution|解答))/i)
  const question = parts[0] || content
  const answer = parts.length > 1 ? parts.slice(1).join("\n") : null

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">题目</h3>
        <Markdown>{question}</Markdown>
      </div>
      {answer ? (
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
              <Markdown>{answer}</Markdown>
            </div>
          )}
        </div>
      ) : (
        <div className="border-t pt-3">
          <p className="text-xs text-[var(--muted-foreground)] italic">No answer section found</p>
        </div>
      )}
      {activeView !== "chat" && (
        <button
          onClick={() => useAppStore.getState().setActiveView("chat")}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md bg-emerald-500 text-white hover:bg-emerald-600 transition-colors"
        >
          <Play className="h-3.5 w-3.5" />
          Practice in Chat
        </button>
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
