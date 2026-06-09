import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from "pdfjs-dist"
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url"

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

type PdfPreviewProps = {
  src: string
  cacheKey?: string | number
  targetPage: number
  syncEnabled: boolean
  onVisiblePageChange?: (page: number) => void
}

type PageSize = {
  page: number
  width: number
  height: number
}

function PdfPage({ doc, pageNumber, containerWidth }: { doc: PDFDocumentProxy; pageNumber: number; containerWidth: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [size, setSize] = useState<PageSize | null>(null)

  useEffect(() => {
    let cancelled = false
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null
    const renderPage = async () => {
      const page = await doc.getPage(pageNumber)
      const baseViewport = page.getViewport({ scale: 1 })
      const scale = Math.max(0.5, Math.min(2, (containerWidth - 32) / baseViewport.width))
      const viewport = page.getViewport({ scale })
      const canvas = canvasRef.current
      if (!canvas || cancelled) return
      const pixelRatio = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * pixelRatio)
      canvas.height = Math.floor(viewport.height * pixelRatio)
      canvas.style.width = `${Math.floor(viewport.width)}px`
      canvas.style.height = `${Math.floor(viewport.height)}px`
      setSize({ page: pageNumber, width: viewport.width, height: viewport.height })
      const context = canvas.getContext("2d")
      if (!context) return
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      renderTask = page.render({ canvasContext: context, viewport })
      await renderTask.promise
    }
    renderPage().catch(() => {})
    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [containerWidth, doc, pageNumber])

  return (
    <div
      data-pdf-page={pageNumber}
      className="mx-auto my-3 w-fit rounded border bg-white shadow-sm"
      style={{ minHeight: size?.height || 320, minWidth: size?.width || "80%" }}
    >
      <div className="border-b px-2 py-1 text-[10px] text-gray-500">Page {pageNumber}</div>
      <canvas ref={canvasRef} className="block" />
    </div>
  )
}

export function PdfPreview({ src, cacheKey, targetPage, syncEnabled, onVisiblePageChange }: PdfPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [containerWidth, setContainerWidth] = useState(640)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    let task: ReturnType<typeof getDocument> | null = null
    setDoc(null)
    setError(null)
    setLoading(true)

    const loadPdf = async () => {
      const separator = src.includes("?") ? "&" : "?"
      const cacheBust = cacheKey ?? Date.now()
      const url = `${src}${separator}v=${encodeURIComponent(String(cacheBust))}`
      const res = await fetch(url, { cache: "no-store" })
      if (!res.ok) throw new Error(`PDF unavailable: HTTP ${res.status}`)
      const data = await res.arrayBuffer()
      if (cancelled) return
      task = getDocument({ data })
      const pdf = await task.promise
      if (!cancelled) setDoc(pdf)
    }

    loadPdf()
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load PDF")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      task?.destroy()
    }
  }, [src, cacheKey])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const resizeObserver = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width)
    })
    resizeObserver.observe(container)
    return () => resizeObserver.disconnect()
  }, [])

  useEffect(() => {
    if (!syncEnabled) return
    const page = containerRef.current?.querySelector<HTMLElement>(`[data-pdf-page="${targetPage}"]`)
    page?.scrollIntoView({ block: "start" })
  }, [syncEnabled, targetPage])

  const reportVisiblePage = useCallback(() => {
    const container = containerRef.current
    if (!container || !onVisiblePageChange) return
    const pages = Array.from(container.querySelectorAll<HTMLElement>("[data-pdf-page]"))
    let visiblePage: number | null = null
    for (const page of pages) {
      const top = page.getBoundingClientRect().top - container.getBoundingClientRect().top
      if (top <= 80) visiblePage = Number(page.dataset.pdfPage)
      else break
    }
    if (visiblePage) onVisiblePageChange(visiblePage)
  }, [onVisiblePageChange])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin opacity-40" />
        Loading PDF...
      </div>
    )
  }

  if (error || !doc) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs text-red-500">
        {error || "PDF unavailable"}
      </div>
    )
  }

  return (
    <div ref={containerRef} onScroll={reportVisiblePage} className="h-full overflow-y-auto bg-[var(--muted)] px-2 py-1">
      {Array.from({ length: doc.numPages }, (_, i) => (
        <PdfPage key={i + 1} doc={doc} pageNumber={i + 1} containerWidth={containerWidth} />
      ))}
    </div>
  )
}
