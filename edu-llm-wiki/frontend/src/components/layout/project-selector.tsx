import { useState, useRef, useEffect } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Plus, Layers, ChevronDown } from "lucide-react"

export function ProjectSelector() {
  const projects = useAppStore((s) => s.projects)
  const setProjects = useAppStore((s) => s.setProjects)
  const currentProject = useAppStore((s) => s.currentProject)
  const setCurrentProject = useAppStore((s) => s.setCurrentProject)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (creating && inputRef.current) inputRef.current.focus()
  }, [creating])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

  const handleSelect = (name: string) => {
    setCurrentProject(name)
    setOpen(false)
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    try {
      const proj = await api.createProject(name.trim())
      setProjects([...projects, proj])
      setCurrentProject(proj.name)
      setCreating(false)
      setName("")
      setOpen(false)
    } catch (e) {
      console.error(e)
    }
  }

  const handleCreateKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate()
    if (e.key === "Escape") { setCreating(false); setName("") }
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
        title={currentProject}
      >
        <Layers size={16} />
        <span className="flex-1 truncate text-left">{currentProject}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute top-full left-2 right-2 mt-1 z-50 bg-[var(--background)] border rounded-lg shadow-lg overflow-hidden">
          <div className="max-h-48 overflow-y-auto">
            {projects.map((p) => (
              <button
                key={p.name}
                onClick={() => handleSelect(p.name)}
                className={`w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-[var(--accent)] ${
                  p.name === currentProject
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "text-[var(--foreground)]"
                }`}
              >
                {p.title}
              </button>
            ))}
            {projects.length === 0 && (
              <p className="px-3 py-2 text-xs text-[var(--muted-foreground)]">No projects</p>
            )}
          </div>

          {/* Create new project */}
          {creating ? (
            <div className="flex gap-1 px-2 py-1.5 border-t">
              <input
                ref={inputRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={handleCreateKey}
                placeholder="Project name..."
                className="flex-1 rounded border px-2 py-1 text-xs bg-[var(--background)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
              />
              <button
                onClick={handleCreate}
                disabled={!name.trim()}
                className="px-2 py-1 text-xs rounded bg-[var(--primary)] text-white disabled:opacity-50"
              >
                Create
              </button>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] border-t transition-colors"
            >
              <Plus size={12} />
              New Project
            </button>
          )}
        </div>
      )}
    </div>
  )
}
