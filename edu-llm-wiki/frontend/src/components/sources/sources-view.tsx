import { useState, useRef } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Upload, Loader2, Trash2, Play } from "lucide-react"

export function SourcesView() {
  const { sourceFiles, setSourceFiles } = useAppStore()
  const setIngestStatus = useAppStore((s) => s.setIngestStatus)
  const [uploading, setUploading] = useState(false)
  const [ingesting, setIngesting] = useState<string>("")
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
    // Refresh list
    const list = await api.listSources()
    setSourceFiles(list)
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleIngest = async (filename: string) => {
    setIngesting(filename)
    setIngestStatus(`Processing ${filename}...`)
    try {
      const result = await api.runIngest([filename])
      setIngestStatus(`Done: ${result.status}`)
      // Refresh pages
      const [pages, sources] = await Promise.all([
        api.listPages(),
        api.listSources(),
      ])
      useAppStore.getState().setWikiPages(pages)
      setSourceFiles(Array.isArray(sources) ? sources : [])
    } catch (e) {
      setIngestStatus(`Error: ${e}`)
    }
    setIngesting("")
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

      {/* Ingest status bar */}
      <IngestStatus />
    </div>
  )
}

function IngestStatus() {
  const status = useAppStore((s) => s.ingestStatus)
  if (!status) return null
  return (
    <div className="shrink-0 px-3 py-1.5 border-t bg-[var(--muted)] text-[11px] text-[var(--muted-foreground)]">
      {status}
    </div>
  )
}
