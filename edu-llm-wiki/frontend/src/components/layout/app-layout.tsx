import { useEffect, useState } from "react"
import { Group, Panel, Separator } from "react-resizable-panels"
import { useAppStore } from "@/stores/app-store"
import { IconSidebar } from "./icon-sidebar"
import { KnowledgeTree } from "./knowledge-tree"
import { PreviewPanel } from "./preview-panel"
import { SourcesView } from "@/components/sources/sources-view"
import { SourcePreview } from "@/components/sources/source-preview"
import { GraphView } from "@/components/graph/graph-view"
import { SettingsView } from "@/components/settings/settings-view"
import { ChatPanel } from "@/components/chat/chat-panel"
import { LearnView } from "@/components/learn/learn-view"

export function AppLayout() {
  const activeView = useAppStore((s) => s.activeView)
  const currentProject = useAppStore((s) => s.currentProject)
  const selectedPage = useAppStore((s) => s.selectedPage)
  const isSourcesView = activeView === "sources"
  const isChatView = activeView === "chat"
  const hideSidebars = isChatView || activeView === "settings" || activeView === "graph"
  // Chat hides the left navigation but keeps the right Wiki preview available
  // after a Wiki link is selected, beside the conversation.
  const hidePreview = isSourcesView || activeView === "settings" || activeView === "graph" || (isChatView && !selectedPage)
  const [compact, setCompact] = useState(false)

  useEffect(() => {
    const media = window.matchMedia("(max-width: 720px)")
    const update = () => setCompact(media.matches)
    update()
    media.addEventListener("change", update)
    return () => media.removeEventListener("change", update)
  }, [])

  // A hidden preview does not always mean the main panel is alone: Sources
  // keeps its navigation panel visible, so the main panel must remain
  // resizable there as well.
  const singlePanel = compact || (hideSidebars && hidePreview)

  const renderSidebar = () => {
    switch (activeView) {
      case "sources":
        return <SourcesView key={currentProject} />
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
        <Group
          orientation="horizontal"
          resizeTargetMinimumSize={{ coarse: 28, fine: 20 }}
          className="h-full"
        >
          {!compact && !hideSidebars && (
            <>
              <Panel
                id={isSourcesView ? "sources-sidebar" : "wiki-sidebar"}
                defaultSize={isSourcesView ? "26%" : "22%"}
                minSize="16%"
                maxSize="42%"
                className="min-w-0 overflow-hidden border-r bg-[var(--sidebar)]"
              >
                {renderSidebar()}
              </Panel>
              <ResizeHandle
                id="wiki-sidebar-separator"
                label="调整知识导航和主内容宽度"
                orientation="vertical"
              />
            </>
          )}

          <Panel
            id="main"
            defaultSize={singlePanel ? "100%" : isChatView ? "68%" : hidePreview ? "74%" : "48%"}
            minSize={singlePanel ? "100%" : isChatView ? "48%" : "25%"}
            className="min-w-0 overflow-hidden"
          >
            {renderMainPanel()}
          </Panel>

          {!compact && !hidePreview && (
            <>
              <ResizeHandle
                id="preview-separator"
                label="调整主内容和知识页面宽度"
                orientation="vertical"
              />
              <Panel
                id="preview"
                defaultSize="30%"
                minSize="24%"
                maxSize="52%"
                className="min-w-0 overflow-hidden border-l bg-[var(--background)]"
              >
                <PreviewPanel />
              </Panel>
            </>
          )}
        </Group>
      </div>
    </div>
  )
}

function ResizeHandle({
  id,
  label,
  orientation,
}: {
  id: string
  label: string
  orientation: "vertical" | "horizontal"
}) {
  return (
    <Separator
      id={id}
      aria-label={label}
      className={
        orientation === "vertical"
          ? "group relative z-10 w-2.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-[var(--primary)]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--primary)] data-[separator=active]:bg-[var(--primary)]/10"
          : "group relative z-10 h-2.5 shrink-0 cursor-row-resize bg-transparent transition-colors hover:bg-[var(--primary)]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--primary)] data-[separator=active]:bg-[var(--primary)]/10"
      }
    >
      <span
        aria-hidden="true"
        className={
          orientation === "vertical"
            ? "pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded bg-[var(--border)] transition-colors group-hover:bg-[var(--primary)] group-data-[separator=active]:bg-[var(--primary)]"
            : "pointer-events-none absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded bg-[var(--border)] transition-colors group-hover:bg-[var(--primary)] group-data-[separator=active]:bg-[var(--primary)]"
        }
      />
    </Separator>
  )
}
