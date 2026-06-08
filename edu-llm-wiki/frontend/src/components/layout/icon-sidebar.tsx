import { cn } from "@/lib/cn"
import { useAppStore, type ActiveView } from "@/stores/app-store"
import { ProjectSelector } from "./project-selector"
import {
  BookOpen, FolderOpen, Search, GitGraph, ShieldCheck, Settings, GraduationCap
} from "lucide-react"

const items: { id: ActiveView; label: string; icon: React.ReactNode }[] = [
  { id: "wiki", label: "Knowledge Tree", icon: <BookOpen size={18} /> },
  { id: "learn", label: "Learning Path", icon: <GraduationCap size={18} /> },
  { id: "sources", label: "Sources", icon: <FolderOpen size={18} /> },
  { id: "search", label: "Search", icon: <Search size={18} /> },
  { id: "graph", label: "Graph", icon: <GitGraph size={18} /> },
  { id: "lint", label: "Health Check", icon: <ShieldCheck size={18} /> },
  { id: "settings", label: "Settings", icon: <Settings size={18} /> },
]

export function IconSidebar() {
  const activeView = useAppStore((s) => s.activeView)
  const setActiveView = useAppStore((s) => s.setActiveView)

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
    </div>
  )
}
