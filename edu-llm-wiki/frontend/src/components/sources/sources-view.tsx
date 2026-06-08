import { useState, useRef } from "react"
import { useAppStore, type IngestProgress } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Upload, Loader2, Trash2, Play, ChevronDown, ChevronUp, FileText, Brain, PenLine, CheckCircle2, X } from "lucide-react"

const STAGE_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  parse: { label: "解析文件", icon: <FileText size={12} /> },
  analyze: { label: "LLM 分析", icon: <Brain size={12} /> },
  generate: { label: "LLM 生成", icon: <PenLine size={12} /> },
  write: { label: "写入页面", icon: <CheckCircle2 size={12} /> },
}

export function SourcesView() {
  const { sourceFiles, setSourceFiles } = useAppStore()
  const progress = useAppStore((s) => s.ingestProgress)
  const updateProgress = useAppStore((s) => s.updateIngestProgress)
  const [uploading, setUploading] = useState(false)
  const [ingesting, setIngesting] = useState<string>("")
  const [expandedStages, setExpandedStages] = useState<Set<string>>(new Set())
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    setUploading(true)
    for (const file of files) {
      try {
        await api.uploadFile(file)
      } catch (err) {
        console.error(err)
      }
    }
    const list = await api.listSources()
    setSourceFiles(list)
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleIngest = async (filename: string) => {
    setIngesting(filename)
    updateProgress(() => ({
      filename,
      stages: [
        { stage: "parse", message: "等待中...", status: "pending" as const },
        { stage: "analyze", message: "等待中...", status: "pending" as const },
        { stage: "generate", message: "等待中...", status: "pending" as const },
        { stage: "write", message: "等待中...", status: "pending" as const },
      ],
    }))
    try {
      for await (const event of api.runIngestStream([filename])) {
        updateProgress((prev) => {
          if (!prev) return null  // shouldn't happen, but safe
          const stages = prev.stages.map((s) => ({ ...s, items: s.pages?.items ? [...s.pages.items] : s.pages?.items }))

          if (event.event === "stage") {
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = { ...stages[idx], status: "active", message: event.message }
              if (event.total) {
                stages[idx].pages = { current: 0, total: event.total, items: [] }
              }
            }
          } else if (event.event === "stage_done") {
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                status: "done",
                message: event.message,
                details: event.details,
                created: event.created,
                updated: event.updated,
              }
            }
          } else if (event.event === "write_page") {
            const idx = stages.findIndex((s) => s.stage === "write")
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                message: event.message,
                pages: {
                  current: event.current,
                  total: event.total,
                  items: [...(stages[idx].pages?.items || []), {
                    title: event.title,
                    page_type: event.page_type,
                    action: event.action || (event.skipped ? "skip" : "new"),
                  }],
                },
              }
            }
          } else if (event.event === "error") {
            return { ...prev, error: event.message }
          } else if (event.event === "cached") {
            // Mark all stages as done for cached items
            return {
              ...prev,
              stages: prev.stages.map((s) => ({ ...s, status: "done" as const, message: event.message })),
              error: undefined,
            }
          }

          return { ...prev, stages }
        })
        if (event.event === "complete" || event.event === "cached") {
          const [pages, sources] = await Promise.all([
            api.listPages(),
            api.listSources(),
          ])
          useAppStore.getState().setWikiPages(pages)
          setSourceFiles(Array.isArray(sources) ? sources : [])
        }
      }
    } catch (e: any) {
      updateProgress((prev) => prev ? { ...prev, error: `${e.message || e}` } : prev)
    }
    setIngesting("")
    // No auto-dismiss — user closes manually
  }

  const handleDelete = async (filename: string) => {
    await api.deleteSource(filename)
    const list = await api.listSources()
    setSourceFiles(Array.isArray(list) ? list : [])
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b">
        <h2 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">Sources</h2>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleUpload}
          className="hidden"
          accept=".pdf,.docx,.pptx,.xlsx,.xls,.md,.txt"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border-2 border-dashed border-[var(--border)] text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {uploading ? "Uploading..." : "Upload Documents"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sourceFiles.map((f) => (
          <div
            key={f.name}
            className="flex items-center gap-2 px-3 py-2 border-b hover:bg-[var(--accent)] text-sm"
          >
            <span className="flex-1 truncate text-[var(--sidebar-foreground)]">{f.name}</span>
            <span className="text-[10px] text-[var(--muted-foreground)]">
              {(f.size / 1024).toFixed(0)} KB
            </span>
            <button
              onClick={() => handleIngest(f.name)}
              disabled={ingesting === f.name}
              className="p-1 rounded hover:bg-green-100 text-green-600 disabled:opacity-50"
              title="Process with LLM"
            >
              {ingesting === f.name ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            </button>
            <button
              onClick={() => handleDelete(f.name)}
              className="p-1 rounded hover:bg-red-100 text-red-600"
              title="Delete"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {sourceFiles.length === 0 && (
          <p className="text-xs text-[var(--muted-foreground)] p-4">
            No sources. Upload documents (PDF, DOCX, PPTX, XLSX, MD) to begin.
          </p>
        )}
      </div>

      {/* Ingest progress panel */}
      {progress && <IngestProgressPanel progress={progress} expandedStages={expandedStages} setExpandedStages={setExpandedStages} />}
    </div>
  )
}

function IngestProgressPanel({
  progress,
  expandedStages,
  setExpandedStages,
}: {
  progress: IngestProgress
  expandedStages: Set<string>
  setExpandedStages: (s: Set<string>) => void
}) {
  const dismiss = useAppStore((s) => s.setIngestProgress)
  const toggleExpand = (stage: string) => {
    const next = new Set(expandedStages)
    if (next.has(stage)) next.delete(stage)
    else next.add(stage)
    setExpandedStages(next)
  }

  const allDone = progress.stages.every((s) => s.status === "done")
  const hasError = !!progress.error

  return (
    <div className={`shrink-0 border-t ${
      hasError ? "bg-red-50" : allDone ? "bg-green-50/50" : "bg-blue-50/50"
    }`}>
      {/* Header */}
      <div className={`px-3 py-1.5 text-xs font-medium flex items-center gap-2 ${
        hasError ? "text-red-700" : allDone ? "text-green-700" : "text-blue-700"
      }`}>
        {allDone ? <CheckCircle2 size={12} /> : hasError ? null : <Loader2 size={12} className="animate-spin" />}
        <span className="truncate flex-1">
          {hasError ? `错误: ${progress.error}` :
           allDone ? `处理完成: ${progress.filename}` :
           `处理中: ${progress.filename}`}
        </span>
        <button
          onClick={() => dismiss(null)}
          className="shrink-0 p-0.5 rounded hover:bg-black/10 transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Stage list */}
      <div className="px-2 pb-2 space-y-0.5">
        {progress.stages.map((s) => {
          const info = STAGE_LABELS[s.stage]
          const isExpanded = expandedStages.has(s.stage)
          const hasDetails = s.details && (s.details.concepts?.length || s.details.formulas?.length)
          const hasPages = s.pages && s.pages.items.length > 0

          return (
            <div key={s.stage} className="rounded">
              <button
                onClick={() => (hasDetails || hasPages) ? toggleExpand(s.stage) : null}
                className={`w-full flex items-center gap-2 px-2 py-1 rounded text-xs transition-colors ${
                  s.status === "active" ? "bg-white/60 text-blue-700" :
                  s.status === "done" ? "text-green-700" :
                  "text-[var(--muted-foreground)]"
                } ${(hasDetails || hasPages) ? "cursor-pointer hover:bg-white/40" : ""}`}
              >
                {/* Stage icon */}
                <span className="shrink-0">
                  {s.status === "done" ? <CheckCircle2 size={12} className="text-green-500" /> :
                   s.status === "active" ? <Loader2 size={12} className="animate-spin" /> :
                   info?.icon}
                </span>
                {/* Progress bar for write stage */}
                {s.stage === "write" && s.pages && (
                  <div className="w-16 h-1.5 rounded-full bg-gray-200 shrink-0">
                    <div
                      className="h-1.5 rounded-full bg-blue-500 transition-all"
                      style={{ width: `${(s.pages.current / s.pages.total) * 100}%` }}
                    />
                  </div>
                )}
                <span className="flex-1 truncate text-left">{s.message}</span>
                {(hasDetails || hasPages) && (
                  <span className="shrink-0 text-[var(--muted-foreground)]">
                    {isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                  </span>
                )}
              </button>

              {/* Expanded details */}
              {isExpanded && hasDetails && s.details && (
                <div className="ml-6 mb-1 px-2 py-1.5 rounded bg-white/60 text-[11px] space-y-1">
                  {s.details.concepts && s.details.concepts.length > 0 && (
                    <div>
                      <span className="font-medium text-[var(--foreground)]">概念: </span>
                      <span className="text-[var(--muted-foreground)]">{s.details.concepts.join(", ")}</span>
                    </div>
                  )}
                  {s.details.formulas && s.details.formulas.length > 0 && (
                    <div>
                      <span className="font-medium text-[var(--foreground)]">公式: </span>
                      <span className="text-[var(--muted-foreground)]">{s.details.formulas.join(", ")}</span>
                    </div>
                  )}
                  {s.details.principles && s.details.principles.length > 0 && (
                    <div>
                      <span className="font-medium text-[var(--foreground)]">原理: </span>
                      <span className="text-[var(--muted-foreground)]">{s.details.principles.join(", ")}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Expanded page list */}
              {isExpanded && hasPages && s.pages && (
                <div className="ml-6 mb-1 max-h-32 overflow-y-auto rounded bg-white/60 text-[11px]">
                  {s.pages.items.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 px-2 py-0.5 border-b last:border-0">
                      <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                        p.action === "新建" ? "bg-green-400" : p.action === "skip" ? "bg-gray-300" : "bg-blue-400"
                      }`} />
                      <span className="text-[var(--muted-foreground)] w-6 text-right shrink-0">{p.page_type}</span>
                      <span className="truncate">{p.title}</span>
                      <span className="text-[10px] text-[var(--muted-foreground)] shrink-0">{p.action}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
