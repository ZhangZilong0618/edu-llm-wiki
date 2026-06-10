import { useState, useRef, useCallback, useEffect } from "react"
import { useAppStore, type IngestProgress } from "@/stores/app-store"
import { api, type ParseStatus } from "@/lib/api"
import { toast } from "@/components/ui/toast"
import { Upload, Loader2, Trash2, Play, ChevronDown, ChevronUp, FileText, Brain, PenLine, CheckCircle2, X, Zap, Eye, FileScan, RefreshCw, Clock, AlertCircle, ScanSearch } from "lucide-react"
import { Markdown } from "@/components/markdown"

function viewableExt(filename: string): boolean {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase()
  return [".pdf", ".pptx", ".docx", ".xlsx", ".txt", ".md", ".markdown", ".rst"].includes(ext)
}

const STAGE_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  parse: { label: "解析文件", icon: <FileText size={12} /> },
  plan: { label: "规划主干", icon: <Brain size={12} /> },
  generate_core: { label: "生成主干", icon: <PenLine size={12} /> },
  derive: { label: "生成进阶", icon: <Zap size={12} /> },
  generate_derived: { label: "组装页面", icon: <FileScan size={12} /> },
  analyze: { label: "LLM 分析", icon: <Brain size={12} /> },
  generate: { label: "LLM 生成", icon: <PenLine size={12} /> },
  write: { label: "写入页面", icon: <CheckCircle2 size={12} /> },
}

const INGEST_STAGES = ["parse", "plan", "generate_core", "derive", "generate_derived", "write"]

const PARSEABLE_EXTS = [".pdf", ".png", ".jpg", ".jpeg"]

export function SourcesView() {
  const { sourceFiles, setSourceFiles } = useAppStore()
  const progress = useAppStore((s) => s.ingestProgress)
  const updateProgress = useAppStore((s) => s.updateIngestProgress)
  const setSelectedSource = useAppStore((s) => s.setSelectedSource)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const importSelected = useAppStore((s) => s.importSelectedSource)
  const setImportSelected = useAppStore((s) => s.setImportSelectedSource)
  const operations = useAppStore((s) => s.operations)
  const beginOperation = useAppStore((s) => s.beginOperation)
  const endOperation = useAppStore((s) => s.endOperation)
  const uploading = Boolean(operations["sources:upload"])
  const [ingesting, setIngesting] = useState<string>("")
  const [expandedStages, setExpandedStages] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [confirmDeleteWiki, setConfirmDeleteWiki] = useState<string | null>(null)
  const [parseStatuses, setParseStatuses] = useState<Record<string, ParseStatus>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const progressDismissTimerRef = useRef<number | null>(null)

  const clearProgressDismissTimer = useCallback(() => {
    if (progressDismissTimerRef.current !== null) {
      window.clearTimeout(progressDismissTimerRef.current)
      progressDismissTimerRef.current = null
    }
  }, [])

  const scheduleProgressDismiss = useCallback((delay = 1800) => {
    clearProgressDismissTimer()
    progressDismissTimerRef.current = window.setTimeout(() => {
      useAppStore.getState().setIngestProgress(null)
      progressDismissTimerRef.current = null
    }, delay)
  }, [clearProgressDismissTimer])

  useEffect(() => {
    return () => clearProgressDismissTimer()
  }, [clearProgressDismissTimer])

  // Clear delete confirmation when clicking elsewhere
  useEffect(() => {
    if (!confirmDelete && !confirmDeleteWiki) return
    const handler = () => {
      setConfirmDelete(null)
      setConfirmDeleteWiki(null)
    }
    const timer = setTimeout(() => document.addEventListener("click", handler, { once: true }), 100)
    return () => { clearTimeout(timer); document.removeEventListener("click", handler) }
  }, [confirmDelete, confirmDeleteWiki])

  const refreshParseStatuses = useCallback(async () => {
    try {
      const list = await api.getAllParseStatuses()
      const map: Record<string, ParseStatus> = {}
      for (const s of list) map[s.filename] = s
      setParseStatuses(map)
    } catch {}
  }, [])

  // Poll parse statuses while any file is pending/running
  useEffect(() => {
    const hasInFlight = Object.values(parseStatuses).some(
      (s) => s.status === "pending" || s.status === "running"
    )
    if (!hasInFlight) return
    const t = setInterval(() => { refreshParseStatuses() }, 3000)
    return () => clearInterval(t)
  }, [parseStatuses, refreshParseStatuses])

  useEffect(() => {
    refreshParseStatuses()
  }, [sourceFiles, refreshParseStatuses])

  const triggerParse = useCallback(async (filename: string) => {
    try {
      await api.startParse(filename)
      await refreshParseStatuses()
    } catch (e: any) {
      toast({ type: "error", message: `Parse failed: ${e?.message || e}` })
    }
  }, [refreshParseStatuses])

  const triggerParseAllPending = useCallback(async () => {
    try {
      await api.parseAllPending()
      toast({ type: "loading", message: "Parsing started for unparsed files..." })
      await refreshParseStatuses()
    } catch (e: any) {
      toast({ type: "error", message: `Batch parse failed: ${e?.message || e}` })
    }
  }, [refreshParseStatuses])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    beginOperation("sources:upload", "上传文件中")
    let ok = 0
    let fail = 0
    const uploaded: string[] = []
    for (const file of files) {
      try {
        const res = await api.uploadFile(file)
        uploaded.push(res.filename)
        ok++
      } catch (err) {
        fail++
        console.error(err)
      }
    }
    try {
      const list = await api.listSources()
      setSourceFiles(list)
    } catch {
      toast({ type: "error", message: "Failed to refresh file list" })
    }
    endOperation("sources:upload")
    if (fileInputRef.current) fileInputRef.current.value = ""
    if (fail > 0) {
      toast({ type: "error", message: `${ok} file(s) uploaded, ${fail} failed` })
    } else if (ok > 0) {
      toast({ type: "success", message: `${ok} file(s) uploaded` })
    }

    // Auto-trigger PaddleOCR parse for newly uploaded parseable files
    const toParse = uploaded.filter((n) => PARSEABLE_EXTS.includes(n.slice(n.lastIndexOf(".")).toLowerCase()))
    if (toParse.length > 0) {
      for (const f of toParse) {
        triggerParse(f).catch(() => {})
      }
    }
  }

  const handleIngest = async (filename: string) => {
    clearProgressDismissTimer()
    setIngesting(filename)
    updateProgress(() => ({
      filename,
      stages: INGEST_STAGES.map((stage) => ({ stage, message: "等待中...", status: "pending" as const })),
    }))
    try {
      for await (const event of api.runIngestStream([filename])) {
        updateProgress((prev) => {
          if (!prev) return null
          const stages = prev.stages.map((s) => ({ ...s, items: s.pages?.items ? [...s.pages.items] : s.pages?.items }))

          if (event.event === "stage") {
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = { ...stages[idx], status: "active", message: event.message }
              if (event.total) {
                stages[idx].pages = { current: 0, total: event.total, items: [] }
              }
            }
          } else if (event.event === "llm_delta") {
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                logs: `${stages[idx].logs || ""}${event.text || ""}`.slice(-12000),
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
            return {
              ...prev,
              stages: prev.stages.map((s) => ({ ...s, status: "done" as const, message: event.message })),
              error: undefined,
            }
          } else if (event.event === "complete") {
            return {
              ...prev,
              filename,
              stages: prev.stages.map((s) => ({
                ...s,
                status: "done" as const,
                message: s.stage === "write" ? event.message : s.message,
              })),
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
          scheduleProgressDismiss()
        }
      }
    } catch (e: any) {
      updateProgress((prev) => prev ? { ...prev, error: `${e.message || e}` } : prev)
    }
    setIngesting("")
  }

  const handleIngestAll = useCallback(async () => {
    const filenames = sourceFiles.map((f) => f.name)
    if (filenames.length === 0) return

    clearProgressDismissTimer()
    setIngesting("all")
    updateProgress(() => ({
      filename: `[Batch] ${filenames.length} files`,
      stages: INGEST_STAGES.map((stage) => ({ stage, message: "等待中...", status: "pending" as const })),
    }))

    const fileStatus = new Map<string, string>()
    let completedCount = 0

    try {
      for await (const event of api.runIngestBatch(filenames)) {
        const src = event.source || ""

        updateProgress((prev) => {
          if (!prev) return null
          const stages = prev.stages.map((s) => ({ ...s, items: s.pages?.items ? [...s.pages.items] : s.pages?.items }))

          if (event.event === "stage") {
            fileStatus.set(src, event.stage)
            const activeFiles = [...fileStatus.entries()].filter(([, s]) => s === event.stage)
            const stageLabel = STAGE_LABELS[event.stage]?.label || event.stage
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                status: "active",
                message: `${stageLabel} (${activeFiles.length} files)`,
              }
            }
          } else if (event.event === "llm_delta") {
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                logs: `${stages[idx].logs || ""}${event.text || ""}`.slice(-12000),
              }
            }
          } else if (event.event === "stage_done") {
            fileStatus.delete(src)
            const idx = stages.findIndex((s) => s.stage === event.stage)
            if (idx >= 0 && stages[idx].status !== "done") {
              stages[idx] = {
                ...stages[idx],
                status: "done",
                message: event.message,
                details: event.details,
              }
            }
          } else if (event.event === "write_page") {
            const idx = stages.findIndex((s) => s.stage === "write")
            if (idx >= 0) {
              stages[idx] = {
                ...stages[idx],
                message: `[${src}] ${event.message}`,
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
            completedCount++
            return {
              ...prev,
              filename: `[Batch] ${completedCount}/${filenames.length} done — Error: ${src}: ${event.message}`,
            }
          } else if (event.event === "cached") {
            completedCount++
          } else if (event.event === "complete") {
            completedCount++
          }

          const allFinished = completedCount >= filenames.length
          return {
            ...prev,
            stages: allFinished
              ? stages.map((s) => ({ ...s, status: "done" as const }))
              : stages,
            filename: allFinished
              ? `[Batch] ${completedCount}/${filenames.length} completed`
              : `[Batch] ${completedCount}/${filenames.length} completed`,
          }
        })

        if (event.event === "complete" || event.event === "cached") {
          const [pages, sources] = await Promise.all([
            api.listPages(),
            api.listSources(),
          ])
          useAppStore.getState().setWikiPages(pages)
          setSourceFiles(Array.isArray(sources) ? sources : [])
          if (completedCount >= filenames.length) scheduleProgressDismiss()
        }
        if (event.event === "error" && completedCount >= filenames.length) {
          scheduleProgressDismiss(5000)
        }
      }
    } catch (e: any) {
      updateProgress((prev) => prev ? { ...prev, error: `${e.message || e}` } : prev)
    }
    setIngesting("")
  }, [clearProgressDismissTimer, scheduleProgressDismiss, sourceFiles, setSourceFiles, updateProgress])

  const handleDelete = async (filename: string) => {
    if (confirmDelete !== filename) {
      setConfirmDelete(filename)
      return
    }
    try {
      await api.deleteSource(filename)
    } catch {
      toast({ type: "error", message: `Failed to delete ${filename}` })
    }
    const list = await api.listSources()
    setSourceFiles(Array.isArray(list) ? list : [])
    setConfirmDelete(null)
    if (importSelected === filename) setImportSelected(null)
  }

  const handleDeleteWiki = async (filename: string) => {
    if (confirmDeleteWiki !== filename) {
      setConfirmDeleteWiki(filename)
      return
    }
    try {
      const result = await api.deleteSourceWiki(filename)
      const pages = await api.listPages()
      useAppStore.getState().setWikiPages(pages)
      useAppStore.getState().setSelectedPage(null)
      toast({ type: "success", message: `Deleted ${result.deleted_count} generated wiki page(s)` })
    } catch (e: any) {
      toast({ type: "error", message: `Failed to delete generated wiki: ${e?.message || e}` })
    }
    setConfirmDeleteWiki(null)
  }

  const handlePreview = async (filename: string) => {
    setImportSelected(filename)
    setSelectedPage(null)
    try {
      const result = await api.parseSource(filename)
      setSelectedSource(result)
    } catch {
      setSelectedSource(null)
    }
  }

  const unparsedCount = sourceFiles.filter((f) => {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase()
    if (!PARSEABLE_EXTS.includes(ext)) return false
    const st = parseStatuses[f.name]
    return !st || st.status === "not_started" || st.status === "failed"
  }).length

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b">
        <h2 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">Import</h2>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleUpload}
          className="hidden"
          accept=".pdf,.docx,.pptx,.xlsx,.xls,.md,.txt,.markdown,.rst"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border-2 border-dashed border-[var(--border)] text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {uploading ? "Uploading..." : "Upload Documents"}
        </button>

        {sourceFiles.length > 1 && (
          <button
            onClick={handleIngestAll}
            disabled={!!ingesting}
            className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] text-xs hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {ingesting === "all" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Zap size={14} />
            )}
            {ingesting === "all" ? `Processing ${sourceFiles.length} files...` : `Ingest All (${sourceFiles.length} files)`}
          </button>
        )}

        {unparsedCount > 0 && (
          <button
            onClick={triggerParseAllPending}
            className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-dashed border-[var(--primary)]/40 text-[var(--primary)] text-xs hover:bg-[var(--primary)]/5 transition-colors"
            title="Parse unparsed PDF/image files with PaddleOCR-VL"
          >
            <FileScan size={14} />
            Parse {unparsedCount} unparsed file{unparsedCount > 1 ? "s" : ""}
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {sourceFiles.map((f) => {
          const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase()
          const isParseable = PARSEABLE_EXTS.includes(ext)
          const st = parseStatuses[f.name]
          return (
            <div
              key={f.name}
              className={`flex items-center gap-2 px-3 py-2 border-b hover:bg-[var(--accent)] text-sm cursor-pointer ${
                importSelected === f.name ? "bg-[var(--accent)]" : ""
              }`}
              onClick={() => setImportSelected(f.name)}
              onDoubleClick={() => handlePreview(f.name)}
            >
              <span className="flex-1 truncate text-[var(--sidebar-foreground)]">{f.name}</span>
              <span className="text-[10px] text-[var(--muted-foreground)]">
                {(f.size / 1024).toFixed(0)} KB
              </span>
              <ParseStatusIcon status={st} parseable={isParseable} onReparse={() => triggerParse(f.name)} />
              {viewableExt(f.name) && (
                <button
                  onClick={(e) => { e.stopPropagation(); handlePreview(f.name) }}
                  className="group relative p-1 rounded hover:bg-blue-100 text-blue-600"
                  title="预览原始文件"
                  aria-label="预览原始文件"
                >
                  <Eye size={14} />
                  <IconTooltip>预览原始文件</IconTooltip>
                </button>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); handleIngest(f.name) }}
                disabled={!!ingesting}
                className="group relative p-1 rounded hover:bg-green-100 text-green-600 disabled:opacity-50"
                title="用 LLM 生成知识 Wiki"
                aria-label="用 LLM 生成知识 Wiki"
              >
                {ingesting === f.name ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                <IconTooltip>生成知识 Wiki</IconTooltip>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteWiki(f.name) }}
                className={`group relative p-1 rounded transition-colors ${
                  confirmDeleteWiki === f.name
                    ? "bg-amber-100 text-amber-700 hover:bg-amber-200"
                    : "hover:bg-amber-100 text-amber-600"
                }`}
                title={confirmDeleteWiki === f.name ? "再次点击确认删除该文件生成的 Wiki 页面" : "仅删除该文件生成的 Wiki 页面"}
                aria-label={confirmDeleteWiki === f.name ? "再次点击确认删除该文件生成的 Wiki 页面" : "仅删除该文件生成的 Wiki 页面"}
              >
                <ScanSearch size={14} />
                <IconTooltip>{confirmDeleteWiki === f.name ? "再次点击确认" : "删除生成的 Wiki"}</IconTooltip>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDelete(f.name) }}
                className={`group relative p-1 rounded transition-colors ${
                  confirmDelete === f.name
                    ? "bg-red-100 text-red-600 hover:bg-red-200"
                    : "hover:bg-red-100 text-red-600"
                }`}
                title={confirmDelete === f.name ? "再次点击确认删除源文件" : "删除源文件"}
                aria-label={confirmDelete === f.name ? "再次点击确认删除源文件" : "删除源文件"}
              >
                <Trash2 size={14} />
                <IconTooltip>{confirmDelete === f.name ? "再次点击确认" : "删除源文件"}</IconTooltip>
              </button>
            </div>
          )
        })}
        {sourceFiles.length === 0 && (
          <p className="text-xs text-[var(--muted-foreground)] p-4">
            No files imported. Upload documents (PDF, DOCX, PPTX, XLSX, MD) to begin.
          </p>
        )}
      </div>

      {progress && <IngestProgressPanel progress={progress} expandedStages={expandedStages} setExpandedStages={setExpandedStages} />}
    </div>
  )
}

function IconTooltip({ children }: { children: React.ReactNode }) {
  return (
    <span className="pointer-events-none absolute right-full top-1/2 z-20 mr-1 -translate-y-1/2 whitespace-nowrap rounded border border-[var(--border)] bg-white px-2 py-1 text-[11px] font-medium text-slate-700 opacity-0 shadow-md transition-opacity group-hover:opacity-100">
      {children}
    </span>
  )
}

function ParseStatusIcon({
  status,
  parseable,
  onReparse,
}: {
  status?: ParseStatus
  parseable: boolean
  onReparse: () => void
}) {
  if (!parseable) {
    return (
      <span className="group relative w-4 h-4" title="该文件类型不需要 OCR 解析">
        <IconTooltip>无需 OCR 解析</IconTooltip>
      </span>
    )
  }
  if (!status || status.status === "not_started") {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); onReparse() }}
        className="group relative p-1 rounded text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        title="用 PaddleOCR-VL 解析文档"
        aria-label="用 PaddleOCR-VL 解析文档"
      >
        <ScanSearch size={12} />
        <IconTooltip>解析文档</IconTooltip>
      </button>
    )
  }
  if (status.status === "pending" || status.status === "running") {
    return (
      <span className="group relative p-1 text-blue-500" title={`正在解析: ${status.page_count} 页`}>
        <Loader2 size={12} className="animate-spin" />
        <IconTooltip>正在解析</IconTooltip>
      </span>
    )
  }
  if (status.status === "failed") {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); onReparse() }}
        className="group relative p-1 rounded text-red-500 hover:bg-red-50"
        title={`解析失败: ${status.error || "未知错误"}。点击重试。`}
        aria-label="解析失败，点击重试"
      >
        <AlertCircle size={12} />
        <IconTooltip>解析失败，重试</IconTooltip>
      </button>
    )
  }
  // done
  return (
    <span
      className="group relative p-1 text-emerald-500"
      title={`已解析: ${status.page_count} 页, ${status.image_count} 张图片`}
    >
      <CheckCircle2 size={12} />
      <IconTooltip>已完成解析</IconTooltip>
    </span>
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

      <div className="px-2 pb-2 space-y-0.5">
        {progress.stages.map((s) => {
          const info = STAGE_LABELS[s.stage]
          const isExpanded = expandedStages.has(s.stage)
          const hasDetails = s.details && (s.details.concepts?.length || s.details.formulas?.length)
          const hasPages = s.pages && s.pages.items.length > 0
          const hasLogs = !!s.logs

          return (
            <div key={s.stage} className="rounded">
              <button
                onClick={() => (hasDetails || hasPages || hasLogs) ? toggleExpand(s.stage) : null}
                className={`w-full flex items-center gap-2 px-2 py-1 rounded text-xs transition-colors ${
                  s.status === "active" ? "bg-white/60 text-blue-700" :
                  s.status === "done" ? "text-green-700" :
                  "text-[var(--muted-foreground)]"
                } ${(hasDetails || hasPages || hasLogs) ? "cursor-pointer hover:bg-white/40" : ""}`}
              >
                <span className="shrink-0">
                  {s.status === "done" ? <CheckCircle2 size={12} className="text-green-500" /> :
                   s.status === "active" ? <Loader2 size={12} className="animate-spin" /> :
                   info?.icon}
                </span>
                {s.stage === "write" && s.pages && (
                  <div className="w-16 h-1.5 rounded-full bg-gray-200 shrink-0">
                    <div
                      className="h-1.5 rounded-full bg-blue-500 transition-all"
                      style={{ width: `${s.pages.total ? (s.pages.current / s.pages.total) * 100 : 0}%` }}
                    />
                  </div>
                )}
                <span className="flex-1 truncate text-left">{s.message}</span>
                {(hasDetails || hasPages || hasLogs) && (
                  <span className="shrink-0 text-[var(--muted-foreground)]">
                    {isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                  </span>
                )}
              </button>

              {isExpanded && hasLogs && (
                <pre className="ml-6 mb-1 max-h-40 overflow-auto rounded bg-slate-950 px-2 py-1.5 text-[10px] leading-relaxed text-slate-100 whitespace-pre-wrap">
                  {s.logs}
                </pre>
              )}

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
