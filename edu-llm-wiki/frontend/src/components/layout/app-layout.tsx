import { useState } from "react"
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
            <div className="p-4">
              <h2 className="text-lg font-semibold mb-4">Knowledge Base Health Check</h2>
              <LintView />
            </div>
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

function LintView() {
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const runLint = async () => {
    setLoading(true)
    try {
      const { api } = await import("@/lib/api")
      const r = await api.runLint()
      setResult(r)
    } catch (e: any) {
      setResult({ error: e.message })
    }
    setLoading(false)
  }

  return (
    <div>
      <button
        onClick={runLint}
        disabled={loading}
        className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg text-sm disabled:opacity-50"
      >
        {loading ? "Running..." : "Run Health Check"}
      </button>
      {result && (
        <pre className="mt-4 p-4 bg-[var(--muted)] rounded-lg text-xs overflow-auto max-h-[60vh]">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  )
}
