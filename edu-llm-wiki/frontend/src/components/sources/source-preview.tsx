import { useEffect, useState } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Markdown } from "@/components/markdown"
import { FileText, FileScan, Loader2, AlertCircle, ExternalLink, RefreshCw } from "lucide-react"
import { toast } from "@/components/ui/toast"

export function SourcePreview() {
  const filename = useAppStore((s) => s.importSelectedSource)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const setSelectedSource = useAppStore((s) => s.setSelectedSource)
  const [parsedContent, setParsedContent] = useState<string | null>(null)
  const [parsedError, setParsedError] = useState<string | null>(null)
  const [parseLoading, setParseLoading] = useState(false)
  const [parseStatus, setParseStatus] = useState<"not_started" | "pending" | "running" | "done" | "failed" | "unknown">("unknown")

  useEffect(() => {
    setParsedContent(null)
    setParsedError(null)
    if (!filename) return
    let cancelled = false

    const load = async () => {
      setParseLoading(true)
      try {
        const status = await api.getParseStatus(filename)
        if (cancelled) return
        setParseStatus(status.status)
        if (status.status === "done") {
          try {
            const doc = await api.getParsedDoc(filename)
            if (!cancelled) setParsedContent(doc.content)
          } catch (e: any) {
            if (!cancelled) setParsedError(e?.message || "Failed to load parsed content")
          }
        }
      } catch (e: any) {
        if (!cancelled) setParseStatus("unknown")
      }
      setParseLoading(false)
    }
    load()

    return () => { cancelled = true }
  }, [filename])

  // Poll while parsing is in progress
  useEffect(() => {
    if (!filename) return
    if (parseStatus !== "pending" && parseStatus !== "running") return
    const t = setInterval(async () => {
      try {
        const status = await api.getParseStatus(filename)
        setParseStatus(status.status)
        if (status.status === "done") {
          try {
            const doc = await api.getParsedDoc(filename)
            setParsedContent(doc.content)
          } catch {}
        }
      } catch {}
    }, 3000)
    return () => clearInterval(t)
  }, [filename, parseStatus])

  if (!filename) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)] p-4 text-center">
        <div>
          <FileText className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p>Select a source file to preview</p>
          <p className="text-xs mt-1">Click on a file in the list to view it here</p>
        </div>
      </div>
    )
  }

  const isPdf = filename.toLowerCase().endsWith(".pdf")
  const viewUrl = isPdf ? api.viewSourceUrl(filename) : null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-3 border-b flex items-center gap-2">
        <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-orange-100 text-orange-700">
          source
        </span>
        <h2 className="text-sm font-semibold truncate">{filename}</h2>
        {viewUrl && (
          <a
            href={viewUrl}
            target="_blank"
            rel="noreferrer"
            className="ml-auto p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            title="Open in new tab"
          >
            <ExternalLink size={14} />
          </a>
        )}
      </div>

      {/* Two-pane layout */}
      <div className="flex-1 min-h-0 grid grid-cols-2 gap-px bg-[var(--border)]">
        {/* Original document */}
        <div className="flex flex-col bg-[var(--background)] min-w-0 overflow-hidden">
          <div className="shrink-0 px-3 py-1.5 border-b text-xs font-medium text-[var(--muted-foreground)] flex items-center gap-1.5">
            <FileText size={12} /> Original Document
          </div>
          <div className="flex-1 overflow-hidden">
            {isPdf && viewUrl ? (
              <iframe
                src={viewUrl}
                className="w-full h-full border-0"
                title={filename}
              />
            ) : selectedSource?.content ? (
              <div className="h-full overflow-y-auto p-3">
                <Markdown>{selectedSource.content}</Markdown>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)] p-4 text-center">
                <div>
                  {selectedSource ? <p>No preview available</p> : <Loader2 className="h-5 w-5 animate-spin mx-auto opacity-40 mb-2" />}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Parsed document */}
        <div className="flex flex-col bg-[var(--background)] min-w-0 overflow-hidden">
          <div className="shrink-0 px-3 py-1.5 border-b text-xs font-medium text-[var(--muted-foreground)] flex items-center gap-1.5">
            <FileScan size={12} /> Parsed (PaddleOCR-VL)
            {parseStatus === "done" && parsedContent && (
              <span className="ml-auto text-emerald-600 text-[10px]">ready</span>
            )}
            {(parseStatus === "pending" || parseStatus === "running") && (
              <span className="ml-auto text-blue-500 text-[10px] flex items-center gap-1">
                <Loader2 size={10} className="animate-spin" />
                {parseStatus}...
              </span>
            )}
            {parseStatus === "failed" && (
              <button
                onClick={async () => {
                  try {
                    await api.startParse(filename)
                    setParseStatus("pending")
                  } catch (e: any) {
                    toast({ type: "error", message: e?.message || "Retry failed" })
                  }
                }}
                className="ml-auto text-red-500 text-[10px] flex items-center gap-1 hover:underline"
                title={parsedError || "Click to retry"}
              >
                <RefreshCw size={10} /> retry
              </button>
            )}
            {(parseStatus === "not_started" || parseStatus === "unknown") && (
              <button
                onClick={async () => {
                  try {
                    await api.startParse(filename)
                    setParseStatus("pending")
                  } catch (e: any) {
                    toast({ type: "error", message: e?.message || "Parse failed" })
                  }
                }}
                className="ml-auto text-[var(--primary)] text-[10px] flex items-center gap-1 hover:underline"
              >
                <FileScan size={10} /> parse
              </button>
            )}
          </div>
          <div className="flex-1 overflow-hidden">
            {parseLoading ? (
              <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)]">
                <Loader2 className="h-5 w-5 animate-spin mr-2 opacity-40" />
                Loading parse status...
              </div>
            ) : parseStatus === "done" && parsedContent ? (
              <div className="h-full overflow-y-auto p-3">
                <Markdown>{parsedContent}</Markdown>
              </div>
            ) : parseStatus === "failed" ? (
              <div className="flex h-full items-center justify-center text-xs text-red-500 p-4 text-center">
                <div>
                  <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-60" />
                  <p>{parsedError || "Parse failed"}</p>
                </div>
              </div>
            ) : parseStatus === "pending" || parseStatus === "running" ? (
              <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)] p-4 text-center">
                <div>
                  <Loader2 className="h-8 w-8 animate-spin mx-auto mb-2 opacity-40" />
                  <p>Parsing with PaddleOCR-VL...</p>
                  <p className="text-[10px] mt-1">This may take 1-2 minutes for PDFs</p>
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)] p-4 text-center">
                <div>
                  <FileScan className="h-8 w-8 mx-auto mb-2 opacity-30" />
                  <p>Click "parse" to extract structured Markdown</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}