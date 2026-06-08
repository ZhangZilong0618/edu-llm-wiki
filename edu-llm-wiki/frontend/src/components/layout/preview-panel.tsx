import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"

export function PreviewPanel() {
  const selectedPage = useAppStore((s) => s.selectedPage)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const setSelectedSource = useAppStore((s) => s.setSelectedSource)

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

        <div className="flex-1 overflow-y-auto">
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
      <div className="flex-1 overflow-y-auto p-4">
        <Markdown>{selectedPage.content || "*No content*"}</Markdown>
      </div>
    </div>
  )
}
