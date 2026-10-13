import { useState, useRef, useCallback, useEffect } from "react"
import { useAppStore, type IngestProgress } from "@/stores/app-store"
import { api, type ParseStatus } from "@/lib/api"
import { toast } from "@/components/ui/toast"
import { Upload, Loader2, Trash2, Play, ChevronDown, ChevronUp, FileText, Brain, PenLine, CheckCircle2, X, Zap, Eye, FileScan, RefreshCw, Clock, AlertCircle, ScanSearch, FileCheck } from "lucide-react"
import { Markdown } from "@/components/markdown"

function viewableExt(filename: string): boolean {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase()
  return [".pdf", ".pptx", ".docx", ".xlsx", ".txt", ".md", ".markdown", ".rst"].includes(ext)
}

const STAGE_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  parse: { label: "Parse File", icon: <FileText size={12} /> },
  plan: { label: "Plan Backbone", icon: <Brain size={12} /> },
  generate_core: { label: "Generate Backbone", icon: <PenLine size={12} /> },
  derive: { label: "Generate Advanced", icon: <Zap size={12} /> },
  generate_derived: { label: "Assemble Page", icon: <FileScan size={12} /> },
  verify_refs: { label: "Citation verification", icon: <FileCheck size={12} /> },
  analyze: { label: "LLM Analysis", icon: <Brain size={12} /> },
  generate: { label: "LLM Generation", icon: <PenLine size={12} /> },
  write: { label: "Write to page", icon: <CheckCircle2 size={12} /> },
}

const INGEST_STAGES = ["parse", "plan", "generate_core", "derive", "generate_derived", "verify_refs", "write"]

const PARSEABLE_EXTS = [".pdf", ".png", ".jpg", ".jpeg"]

type IngestTaskStatus = "queued" | "running" | "done" | "error"

interface IngestTaskState {
  status: IngestTaskStatus
  message?: string
}

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
  const [isDragging, setIsDragging] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null)
  const progressClearTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [taskQueue, setTaskQueue] = useState<string[]>([])
  const [activeTask, setActiveTask] = useState<string | null>(null)
  const [taskStates, setTaskStates] = useState<Record<string, IngestTaskState>>({})
  const queueRef = useRef<string[]>([])
  const activeTaskRef = useRef<string | null>(null)
  const queueRunningRef = useRef(false)
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

  useEffect(() => {
    return () => {
      if (progressClearTimer.current) clearTimeout(progressClearTimer.current)
    }
  }, [])

  const triggerParseAllPending = useCallback(async () => {
    try {
      await api.parseAllPending()
      toast({ type: "loading", message: "Parsing started for unparsed files..." })
      await refreshParseStatuses()
    } catch (e: any) {
      toast({ type: "error", message: `Batch parse failed: ${e?.message || e}` })
    }
  }, [refreshParseStatuses])

  useEffect(() => {
    return () => {
      if (progressClearTimer.current) clearTimeout(progressClearTimer.current)
    }
  }, [])

  const runUpload = async (filesIn: FileList | File[] | null | undefined) => {
    if (!filesIn) return
    const list = Array.from(filesIn)
    if (list.length === 0) return
    const total = list.length
    beginOperation("sources:upload", `上传 ${total} 个文件中`)
    setUploadProgress({ done: 0, total })
    let ok = 0
    let fail = 0
    const uploaded: string[] = []
    for (const file of list) {
      try {
        const res = await api.uploadFile(file)
        uploaded.push(res.filename)
        ok++
      } catch (err) {
        fail++
        console.error(err)
      }
      setUploadProgress({ done: ok + fail, total })
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
      toast({ type: "error", message: `${ok} 个上传成功，${fail} 个失败` })
    } else if (ok > 0) {
      toast({ type: "success", message: `已上传 ${ok} 个文件` })
    }
    if (progressClearTimer.current) clearTimeout(progressClearTimer.current)
    progressClearTimer.current = setTimeout(() => setUploadProgress(null), 1500)
    // Auto-trigger PaddleOCR parse for newly uploaded parseable files
    const toParse = uploaded.filter((n) => PARSEABLE_EXTS.includes(n.slice(n.lastIndexOf(".")).toLowerCase()))
    if (toParse.length > 0) {
      for (const f of toParse) {
        triggerParse(f).catch(() => {})
      }
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    await runUpload(e.target.files)
  }

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer?.types?.includes("Files")) {
      e.preventDefault()
      if (!isDragging) setIsDragging(true)
    }
  }
  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (e.currentTarget.contains(e.relatedTarget as Node)) return
    setIsDragging(false)
  }
  const onDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer?.files?.length) {
      await runUpload(e.dataTransfer.files)
    }
  }

  const runIngestTask = useCallback(async (filename: string) => {
    clearProgressDismissTimer()
    updateProgress(() => ({
      filename,
      status: "running" as const,
      stages: INGEST_STAGES.map((stage) => ({ stage, message: "Waiting...", status: "pending" as const })),
    }))

    let failed = false
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
            failed = true
            return { ...prev, status: "error" as const, error: event.message }
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
              status: "done" as const,
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
      failed = true
      updateProgress((prev) => prev ? { ...prev, error: `${e.message || e}` } : prev)
    }

    setTaskStates((prev) => ({
      ...prev,
      [filename]: {
        status: failed ? "error" : "done",
        message: failed ? "Processing failed; you can re-add it to the queue" : undefined,
      },
    }))
  }, [clearProgressDismissTimer, scheduleProgressDismiss, setSourceFiles, updateProgress])

  const processQueue = useCallback(async () => {
    if (queueRunningRef.current) return
    queueRunningRef.current = true

    try {
      while (true) {
        const next = queueRef.current.shift()
        if (!next) break

        setTaskQueue([...queueRef.current])
        activeTaskRef.current = next
        setActiveTask(next)
        setTaskStates((prev) => ({ ...prev, [next]: { status: "running" } }))

        await runIngestTask(next)

        activeTaskRef.current = null
        setActiveTask(null)
      }
    } finally {
      queueRunningRef.current = false
    }

    // A task may have been enqueued while the loop was exiting.
    if (queueRef.current.length > 0) void processQueue()
  }, [runIngestTask])

  const enqueueIngest = useCallback((filename: string) => {
    if (activeTaskRef.current === filename || queueRef.current.includes(filename)) return
    const file = sourceFiles.find((f) => f.name === filename)
    if (file?.imported) return

    queueRef.current = [...queueRef.current, filename]
    setTaskQueue(queueRef.current)
    setTaskStates((prev) => ({ ...prev, [filename]: { status: "queued" } }))
    void processQueue()
  }, [processQueue, sourceFiles])

  const enqueueAllPending = useCallback(() => {
    const filenames = sourceFiles
      .filter((f) => !f.imported)
      .map((f) => f.name)
      .filter((name) => name !== activeTaskRef.current && !queueRef.current.includes(name))
    if (filenames.length === 0) return

    queueRef.current = [...queueRef.current, ...filenames]
    setTaskQueue(queueRef.current)
    setTaskStates((prev) => {
      const next = { ...prev }
      for (const filename of filenames) next[filename] = { status: "queued" }
      return next
    })
    void processQueue()
  }, [processQueue, sourceFiles])

  const removeQueuedTask = useCallback((filename: string) => {
    queueRef.current = queueRef.current.filter((name) => name !== filename)
    setTaskQueue(queueRef.current)
    setTaskStates((prev) => ({
      ...prev,
      [filename]: { status: "done", message: "Removed from queue" },
    }))
  }, [])

  const clearPendingQueue = useCallback(() => {
    queueRef.current = []
    setTaskQueue([])
    setTaskStates((prev) => {
      const next = { ...prev }
      for (const [filename, state] of Object.entries(prev)) {
        if (state.status === "queued") next[filename] = { status: "done", message: "Removed from queue" }
      }
      return next
    })
  }, [])

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
      const [pages, sources] = await Promise.all([
        api.listPages(),
        api.listSources(),
      ])
      useAppStore.getState().setWikiPages(pages)
      useAppStore.getState().setSelectedPage(null)
      setSourceFiles(Array.isArray(sources) ? sources : [])
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

  const queuedSet = new Set(taskQueue)
  const pendingIngestFiles = sourceFiles.filter(
    (f) => !f.imported && !queuedSet.has(f.name) && f.name !== activeTask
  )

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
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={
            "rounded-lg border-2 border-dashed transition-colors " +
            (isDragging
              ? "border-[var(--primary)] bg-[var(--primary)]/5"
              : "border-[var(--border)]")
          }
        >
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-[var(--muted-foreground)] hover:text-[var(--primary)] transition-colors"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {uploading ? "Uploading..." : isDragging ? "Release mouse to upload" : "Upload or Drop Documents"}
        </button>
        </div>
        {uploadProgress ? (
          <div className="mt-1.5">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]">
              <div
                className="h-full bg-[var(--primary)] transition-all"
                style={{ width: `${Math.round((uploadProgress.done / Math.max(1, uploadProgress.total)) * 100)}%` }}
              />
            </div>
            <p className="mt-1 text-center text-[10px] text-[var(--muted-foreground)]">
              {uploadProgress.done} / {uploadProgress.total}
            </p>
          </div>
        ) : null}

        {sourceFiles.length > 1 && (
          <button
            onClick={enqueueAllPending}
            disabled={pendingIngestFiles.length === 0}
            className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] text-xs hover:opacity-90 transition-opacity disabled:opacity-50"
            title="Add all unimported documents to the task queue"
          >
            <Clock size={14} />
            添加 {pendingIngestFiles.length} 个任务
          </button>
        )}

        {(activeTask || taskQueue.length > 0) && (
          <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--muted)] p-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
                Task Queue
              </span>
              {taskQueue.length > 0 && (
                <button
                  onClick={clearPendingQueue}
                  className="text-[10px] text-[var(--muted-foreground)] hover:text-rose-600"
                >
                  Clear pending
                </button>
              )}
            </div>
            {activeTask && (
              <div className="flex items-center gap-2 rounded bg-white px-2 py-1 text-[11px]">
                <Loader2 size={12} className="shrink-0 animate-spin text-blue-600" />
                <span className="flex-1 truncate">{activeTask}</span>
                <span className="shrink-0 text-[10px] text-blue-600">Running</span>
              </div>
            )}
            {taskQueue.map((filename) => (
              <div key={filename} className="mt-1 flex items-center gap-2 rounded bg-white px-2 py-1 text-[11px]">
                <Clock size={12} className="shrink-0 text-[var(--muted-foreground)]" />
                <span className="flex-1 truncate">{filename}</span>
                <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">Pending</span>
                <button
                  onClick={() => removeQueuedTask(filename)}
                  className="shrink-0 rounded p-0.5 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-600"
                  title="Remove from queue"
                  aria-label={`Remove from queue ${filename}`}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
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
              {f.imported ? (
                <span className="shrink-0 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                  Added to Graph
                </span>
              ) : (
                <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                  Not imported
                </span>
              )}
              <span className="text-[10px] text-[var(--muted-foreground)]">
                {(f.size / 1024).toFixed(0)} KB
              </span>
              <ParseStatusIcon status={st} parseable={isParseable} onReparse={() => triggerParse(f.name)} />
              {viewableExt(f.name) && (
                <button
                  onClick={(e) => { e.stopPropagation(); handlePreview(f.name) }}
                  className="group relative p-1 rounded hover:bg-blue-100 text-blue-600"
                  title="Preview original file"
                  aria-label="Preview original file"
                >
                  <Eye size={14} />
                  <IconTooltip>Preview original file</IconTooltip>
                </button>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); enqueueIngest(f.name) }}
                disabled={f.imported || activeTask === f.name || queuedSet.has(f.name)}
                className="group relative p-1 rounded hover:bg-green-100 text-green-600 disabled:opacity-50"
                title={
                  f.imported
                    ? "Already in the graph; to regenerate, please delete the generated Wiki first"
                    : activeTask === f.name
                      ? "Processing"
                      : queuedSet.has(f.name)
                        ? "Added to task queue"
                        : "Generate knowledge Wiki with LLM"
                }
                aria-label={
                  f.imported
                    ? "Already added to the graph; cannot run again"
                    : activeTask === f.name
                      ? "Processing"
                      : queuedSet.has(f.name)
                        ? "Added to task queue"
                        : "Generate knowledge Wiki with LLM"
                }
              >
                {activeTask === f.name ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : queuedSet.has(f.name) ? (
                  <Clock size={14} />
                ) : (
                  <Play size={14} />
                )}
                <IconTooltip>
                  {f.imported
                    ? "Added to Graph"
                    : activeTask === f.name
                      ? "Processing"
                      : queuedSet.has(f.name)
                        ? "Added to queue"
                        : "Generate knowledge Wiki"}
                </IconTooltip>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteWiki(f.name) }}
                className={`group relative p-1 rounded transition-colors ${
                  confirmDeleteWiki === f.name
                    ? "bg-amber-100 text-amber-700 hover:bg-amber-200"
                    : "hover:bg-amber-100 text-amber-600"
                }`}
                title={confirmDeleteWiki === f.name ? "Click again to confirm deleting the Wiki pages generated from this file" : "Delete only the Wiki pages generated from this file"}
                aria-label={confirmDeleteWiki === f.name ? "Click again to confirm deleting the Wiki pages generated from this file" : "Delete only the Wiki pages generated from this file"}
              >
                <ScanSearch size={14} />
                <IconTooltip>{confirmDeleteWiki === f.name ? "Click again to confirm" : "Delete generated Wiki"}</IconTooltip>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDelete(f.name) }}
                className={`group relative p-1 rounded transition-colors ${
                  confirmDelete === f.name
                    ? "bg-red-100 text-red-600 hover:bg-red-200"
                    : "hover:bg-red-100 text-red-600"
                }`}
                title={confirmDelete === f.name ? "Click again to confirm deleting the source file" : "Delete source file"}
                aria-label={confirmDelete === f.name ? "Click again to confirm deleting the source file" : "Delete source file"}
              >
                <Trash2 size={14} />
                <IconTooltip>{confirmDelete === f.name ? "Click again to confirm" : "Delete source file"}</IconTooltip>
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
      <span className="group relative w-4 h-4" title="This file type does not require OCR parsing">
        <IconTooltip>No OCR parsing needed</IconTooltip>
      </span>
    )
  }
  if (!status || status.status === "not_started") {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); onReparse() }}
        className="group relative p-1 rounded text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        title="Parse documents with PaddleOCR-VL"
        aria-label="Parse documents with PaddleOCR-VL"
      >
        <ScanSearch size={12} />
        <IconTooltip>Parse Document</IconTooltip>
      </button>
    )
  }
  if (status.status === "pending" || status.status === "running") {
    return (
      <span className="group relative p-1 text-blue-500" title={`Parsing: ${status.page_count} 页`}>
        <Loader2 size={12} className="animate-spin" />
        <IconTooltip>Parsing</IconTooltip>
      </span>
    )
  }
  if (status.status === "failed") {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); onReparse() }}
        className="group relative p-1 rounded text-red-500 hover:bg-red-50"
        title={`Analysis失败: ${status.error || "未知错误"}。点击Retry。`}
        aria-label="Parsing failed; click to retry"
      >
        <AlertCircle size={12} />
        <IconTooltip>Parsing failed, retry</IconTooltip>
      </button>
    )
  }
  // done
  return (
    <span
      className="group relative p-1 text-emerald-500"
      title={`已Analysis: ${status.page_count} 页, ${status.image_count} 张图片`}
    >
      <CheckCircle2 size={12} />
      <IconTooltip>Analysis completed</IconTooltip>
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
  // 当某阶段有 LLM 日志且 ingest 已Complete/出错时，自动Expand该阶段。
  useEffect(() => {
    if (progress?.status !== "done" && progress?.status !== "error") return
    const auto = new Set(expandedStages)
    let changed = false
    for (const s of progress.stages) {
      if (s.logs && s.logs.length > 0 && !auto.has(s.stage)) {
        auto.add(s.stage)
        changed = true
      }
    }
    if (changed) setExpandedStages(auto)
  }, [progress?.status, progress?.stages])
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
           allDone ? `处理Complete: ${progress.filename}` :
           `Processing: ${progress.filename}`}
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
          const hasDetails = s.details && (
            s.details.concepts?.length ||
            s.details.formulas?.length ||
            s.details.principles?.length
          )
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
                <pre className="ml-6 mb-1 max-h-40 min-w-0 max-w-[calc(100%_-_1.5rem)] overflow-auto rounded bg-slate-950 px-2 py-1.5 text-[10px] leading-relaxed text-slate-100 whitespace-pre-wrap [overflow-wrap:anywhere] break-words">
                  {s.logs}
                </pre>
              )}

              {isExpanded && hasDetails && s.details && (
                <div className="ml-6 mb-1 min-w-0 max-w-[calc(100%_-_1.5rem)] overflow-hidden rounded bg-white/60 px-2 py-1.5 text-[11px] space-y-1">
                  {s.details.concepts && s.details.concepts.length > 0 && (
                    <div className="min-w-0 break-words [overflow-wrap:anywhere]">
                      <span className="font-medium text-[var(--foreground)]">Concept: </span>
                      <span className="text-[var(--muted-foreground)] break-words [overflow-wrap:anywhere]">{s.details.concepts.join(", ")}</span>
                    </div>
                  )}
                  {s.details.formulas && s.details.formulas.length > 0 && (
                    <div className="min-w-0 break-words [overflow-wrap:anywhere]">
                      <span className="font-medium text-[var(--foreground)]">Formula: </span>
                      <span className="text-[var(--muted-foreground)] break-words [overflow-wrap:anywhere]">{s.details.formulas.join(", ")}</span>
                    </div>
                  )}
                  {s.details.principles && s.details.principles.length > 0 && (
                    <div className="min-w-0 break-words [overflow-wrap:anywhere]">
                      <span className="font-medium text-[var(--foreground)]">Principle: </span>
                      <span className="text-[var(--muted-foreground)] break-words [overflow-wrap:anywhere]">{s.details.principles.join(", ")}</span>
                    </div>
                  )}
                </div>
              )}

              {isExpanded && hasPages && s.pages && (
                <div className="ml-6 mb-1 max-h-32 min-w-0 max-w-[calc(100%_-_1.5rem)] overflow-y-auto overflow-x-hidden rounded bg-white/60 text-[11px]">
                  {s.pages.items.map((p, i) => (
                    <div key={i} className="flex min-w-0 items-center gap-2 border-b px-2 py-0.5 last:border-0">
                      <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                        p.action === "New" ? "bg-green-400" : p.action === "skip" ? "bg-gray-300" : "bg-blue-400"
                      }`} />
                      <span className="text-[var(--muted-foreground)] w-6 text-right shrink-0">{p.page_type}</span>
                      <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{p.title}</span>
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
