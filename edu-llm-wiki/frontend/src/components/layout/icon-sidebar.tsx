import { cn } from "@/lib/cn"
import { useState } from "react"
import { useAppStore, type ActiveView } from "@/stores/app-store"
import { ProjectSelector } from "./project-selector"
import { UserSelector } from "./user-selector"
import {
  Upload, BookOpen, GitGraph, Settings, GraduationCap, Loader2, UsersRound, X
} from "lucide-react"

const items: { id: ActiveView; label: string; icon: React.ReactNode }[] = [
  { id: "sources", label: "Import", icon: <Upload size={18} /> },
  // Keep the chat entry on the dedicated chat view so it uses the same
  // full-width conversation surface as page actions and learning prompts.
  { id: "chat", label: "Chat", icon: <BookOpen size={18} /> },
  { id: "learn", label: "Learning Path", icon: <GraduationCap size={18} /> },
  { id: "graph", label: "Graph", icon: <GitGraph size={18} /> },
  { id: "settings", label: "Settings", icon: <Settings size={18} /> },
]

export function IconSidebar() {
  const [mobileContextOpen, setMobileContextOpen] = useState(false)
  const activeView = useAppStore((s) => s.activeView)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const operationMap = useAppStore((s) => s.operations)
  const operations = Object.values(operationMap)
  const activeOperation = operations[0]

  return (
    <div className="flex flex-col gap-0.5 py-3 px-0.5 sm:px-2 w-12 sm:w-48 border-r bg-[var(--sidebar)] shrink-0">
      <div className="hidden sm:block">
        <UserSelector />
        <ProjectSelector />
      </div>
      <button
        type="button"
        onClick={() => setMobileContextOpen(true)}
        className="flex h-9 w-full items-center justify-center rounded-lg text-[var(--sidebar-foreground)] hover:bg-[var(--accent)] sm:hidden"
        title="项目与学习者"
        aria-label="打开项目与学习者设置"
      >
        <UsersRound size={18} />
      </button>
      <div className="border-t border-[var(--border)] my-1" />
      {items.map((item) => (
        <button
          key={item.id}
          onClick={() => setActiveView(item.id)}
          className={cn(
            "flex items-center justify-center sm:justify-start gap-0 sm:gap-3 px-2 sm:px-3 py-2 rounded-lg text-sm transition-colors w-full text-left",
            (activeView === item.id || (item.id === "chat" && activeView === "wiki"))
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
          )}
          title={item.label}
        >
          {item.icon}
          <span className="hidden sm:inline truncate">{item.label}</span>
        </button>
      ))}
      {operations.length > 0 && (
        <div className="mt-auto rounded-md border bg-[var(--background)] px-2 py-2 text-xs text-[var(--muted-foreground)]">
          <div className="flex items-center gap-2">
            <Loader2 size={13} className="animate-spin text-[var(--primary)]" />
            <span className="min-w-0 flex-1 truncate">{activeOperation?.label || "Processing"}</span>
            {operations.length > 1 && <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">{operations.length}</span>}
          </div>
        </div>
      )}
      {mobileContextOpen ? (
        <div
          className="fixed inset-0 z-[9998] bg-slate-950/25 sm:hidden"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setMobileContextOpen(false)
          }}
        >
          <div
            className="absolute left-2 top-2 w-[min(280px,calc(100vw-1rem))] overflow-hidden rounded-xl border bg-[var(--background)] shadow-xl"
            role="dialog"
            aria-label="项目与学习者设置"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-xs font-medium text-[var(--foreground)]">项目与学习者</span>
              <button
                type="button"
                onClick={() => setMobileContextOpen(false)}
                className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                aria-label="关闭项目与学习者设置"
              >
                <X size={14} />
              </button>
            </div>
            <div className="p-2">
              <UserSelector />
              <ProjectSelector />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
