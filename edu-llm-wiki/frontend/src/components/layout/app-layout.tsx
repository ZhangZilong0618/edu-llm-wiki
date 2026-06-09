import { Panel, Group, Separator } from "react-resizable-panels"
import { useAppStore } from "@/stores/app-store"
import { IconSidebar } from "./icon-sidebar"
import { KnowledgeTree } from "./knowledge-tree"
import { PreviewPanel } from "./preview-panel"
import { SourcesView } from "@/components/sources/sources-view"
import { SourcePreview } from "@/components/sources/source-preview"
import { SearchView } from "@/components/search/search-view"
import { GraphView } from "@/components/graph/graph-view"
import { SettingsView } from "@/components/settings/settings-view"
import { ChatPanel } from "@/components/chat/chat-panel"
import { LintView } from "@/components/lint/lint-view"
import { LearnView } from "@/components/learn/learn-view"

export function AppLayout() {
  const activeView = useAppStore((s) => s.activeView)
  const currentProject = useAppStore((s) => s.currentProject)
  const isSourcesView = activeView === "sources"
  const hideSidebars = activeView === "settings"

  const renderSidebar = () => {
    switch (activeView) {
      case "sources":
        return <SourcesView key={currentProject} />
      case "search":
        return <SearchView key={currentProject} />
      default:
        return <KnowledgeTree key={currentProject} />
    }
  }

  const renderMainPanel = () => {
    switch (activeView) {
      case "settings":
        return <SettingsView />
      case "graph":
        return <GraphView key={currentProject} />
      case "lint":
        return <LintView />
      case "learn":
        return <LearnView key={currentProject} />
      case "sources":
        return <SourcePreview />
      default:
        return <ChatPanel key={currentProject} />
    }
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <IconSidebar />

      <div className="flex-1 min-w-0 overflow-hidden">
        <div className={`flex h-full ${isSourcesView ? "" : "gap-0"}`}>
          {/* Sidebar panel - hidden in settings view */}
          {!hideSidebars && (
            <>
              <div
                className="border-r bg-[var(--sidebar)] shrink-0 overflow-hidden"
                style={{ width: isSourcesView ? "320px" : "var(--sidebar-width, 30%)" }}
              >
                {renderSidebar()}
              </div>

              <ResizeHandle orientation="vertical" />
            </>
          )}

          {/* Main panel - takes remaining space */}
          <div className="flex-1 min-w-0 overflow-hidden">
            {renderMainPanel()}
          </div>

          {/* Right preview panel - hidden in sources/settings view */}
          {!isSourcesView && !hideSidebars && (
            <>
              <ResizeHandle orientation="vertical" />
              <div className="border-l bg-[var(--background)] shrink-0 overflow-hidden" style={{ width: "var(--preview-width, 30%)" }}>
                <PreviewPanel />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ResizeHandle({ orientation }: { orientation: "vertical" | "horizontal" }) {
  if (orientation === "vertical") {
    return (
      <div
        className="w-1.5 bg-[var(--border)] hover:bg-[var(--primary)] cursor-col-resize shrink-0 transition-colors"
        onMouseDown={(e) => {
          e.preventDefault()
          const startX = e.clientX
          const target = e.currentTarget
          const prev = target.previousElementSibling as HTMLElement
          const next = target.nextElementSibling as HTMLElement
          const startW = prev.getBoundingClientRect().width
          document.body.style.cursor = "col-resize"
          document.body.style.userSelect = "none"
          const onMove = (ev: MouseEvent) => {
            const dx = ev.clientX - startX
            const newW = Math.max(200, startW + dx)
            if (prev.style.width?.includes("%") || !prev.style.width) {
              prev.style.width = `${newW}px`
            } else {
              prev.style.width = `${newW}px`
            }
          }
          const onUp = () => {
            document.removeEventListener("mousemove", onMove)
            document.removeEventListener("mouseup", onUp)
            document.body.style.cursor = ""
            document.body.style.userSelect = ""
          }
          document.addEventListener("mousemove", onMove)
          document.addEventListener("mouseup", onUp)
        }}
      />
    )
  }
  return null
}