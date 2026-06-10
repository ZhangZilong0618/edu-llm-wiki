import { cn } from "@/lib/cn"
import { useAppStore, type ActiveView } from "@/stores/app-store"
import { ProjectSelector } from "./project-selector"
import {
  Upload, BookOpen, GitGraph, Settings, GraduationCap, ClipboardCheck, Loader2
} from "lucide-react"

const items: { id: ActiveView; label: string; icon: React.ReactNode }[] = [
  { id: "sources", label: "Import", icon: <Upload size={18} /> },
  { id: "wiki", label: "Knowledge Wiki", icon: <BookOpen size={18} /> },
  { id: "learn", label: "Learning Path", icon: <GraduationCap size={18} /> },
  { id: "tests", label: "Tests", icon: <ClipboardCheck size={18} /> },
  { id: "graph", label: "Graph", icon: <GitGraph size={18} /> },
  { id: "settings", label: "Settings", icon: <Settings size={18} /> },
]

export function IconSidebar() {
  const activeView = useAppStore((s) => s.activeView)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const operationMap = useAppStore((s) => s.operations)
  const operations = Object.values(operationMap)
  const activeOperation = operations[0]

  return (
    <div className="flex flex-col gap-0.5 py-3 px-2 w-48 border-r bg-[var(--sidebar)] shrink-0">
      <ProjectSelector />
      <div className="border-t border-[var(--border)] my-1" />
      {items.map((item) => (
        <button
          key={item.id}
          onClick={() => setActiveView(item.id)}
          className={cn(
            "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors w-full text-left",
            activeView === item.id
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
          )}
          title={item.label}
        >
          {item.icon}
          <span className="truncate">{item.label}</span>
        </button>
      ))}
      {operations.length > 0 && (
        <div className="mt-auto rounded-md border bg-[var(--background)] px-2 py-2 text-xs text-[var(--muted-foreground)]">
          <div className="flex items-center gap-2">
            <Loader2 size={13} className="animate-spin text-[var(--primary)]" />
            <span className="min-w-0 flex-1 truncate">{activeOperation?.label || "处理中"}</span>
            {operations.length > 1 && <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">{operations.length}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
