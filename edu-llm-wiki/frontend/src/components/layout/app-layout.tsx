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
import { TestsView } from "@/components/tests/tests-view"

export function AppLayout() {
  const activeView = useAppStore((s) => s.activeView)
  const currentProject = useAppStore((s) => s.currentProject)
  const isSourcesView = activeView === "sources"
  const hideSidebars = activeView === "settings" || activeView === "graph" || activeView === "tests"
  const hidePreview = isSourcesView || hideSidebars

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
      case "tests":
        return <TestsView key={currentProject} />
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
        <Group orientation="horizontal" className="h-full">
          {!hideSidebars && (
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
              <ResizeHandle orientation="vertical" />
            </>
          )}

          <Panel
            id="main"
            defaultSize={hideSidebars ? "100%" : hidePreview ? "74%" : "48%"}
            minSize="25%"
            className="min-w-0 overflow-hidden"
          >
            {renderMainPanel()}
          </Panel>

          {!hidePreview && (
            <>
              <ResizeHandle orientation="vertical" />
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

function ResizeHandle({ orientation }: { orientation: "vertical" | "horizontal" }) {
  return (
    <Separator
      className={
        orientation === "vertical"
          ? "group relative w-1.5 shrink-0 cursor-col-resize bg-[var(--border)] transition-colors hover:bg-[var(--primary)] data-[resize-handle-active]:bg-[var(--primary)]"
          : "group relative h-1.5 shrink-0 cursor-row-resize bg-[var(--border)] transition-colors hover:bg-[var(--primary)] data-[resize-handle-active]:bg-[var(--primary)]"
      }
    />
  )
}
