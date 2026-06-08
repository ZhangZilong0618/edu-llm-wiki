import { Panel, Group, Separator } from "react-resizable-panels"
import { useAppStore } from "@/stores/app-store"
import { IconSidebar } from "./icon-sidebar"
import { KnowledgeTree } from "./knowledge-tree"
import { PreviewPanel } from "./preview-panel"
import { SourcesView } from "@/components/sources/sources-view"
import { SearchView } from "@/components/search/search-view"
import { GraphView } from "@/components/graph/graph-view"
import { SettingsView } from "@/components/settings/settings-view"
import { ChatPanel } from "@/components/chat/chat-panel"
import { LintView } from "@/components/lint/lint-view"
import { LearnView } from "@/components/learn/learn-view"

export function AppLayout() {
  const activeView = useAppStore((s) => s.activeView)
  const currentProject = useAppStore((s) => s.currentProject)

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

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <IconSidebar />

      <div className="flex-1 min-w-0 overflow-hidden">
        <Group orientation="horizontal" id="edu-llm-wiki-layout-v3">
        {/* Left panel */}
        <Panel defaultSize="30%" minSize="18%" maxSize="50%" className="border-r bg-[var(--sidebar)]">
          {renderSidebar()}
        </Panel>

        <Separator style={{ width: 10 }} className="bg-[var(--border)] hover:bg-[var(--primary)] cursor-col-resize" />

        {/* Center panel - Chat */}
        <Panel defaultSize="38%" minSize="20%">
          {activeView === "settings" ? (
            <SettingsView />
          ) : activeView === "graph" ? (
            <GraphView key={currentProject} />
          ) : activeView === "lint" ? (
            <LintView />
          ) : activeView === "learn" ? (
            <LearnView key={currentProject} />
          ) : (
            <ChatPanel key={currentProject} />
          )}
        </Panel>

        <Separator style={{ width: 10 }} className="bg-[var(--border)] hover:bg-[var(--primary)] cursor-col-resize" />

        {/* Right panel - Preview */}
        <Panel defaultSize="30%" minSize="15%" className="border-l bg-[var(--background)]">
          <PreviewPanel />
        </Panel>
      </Group>
      </div>
    </div>
  )
}
