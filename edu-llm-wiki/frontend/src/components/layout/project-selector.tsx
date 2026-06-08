import { useState, useRef, useEffect } from "react"
import { createPortal } from "react-dom"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Plus, Layers, ChevronDown, X } from "lucide-react"

export function ProjectSelector() {
  const projects = useAppStore((s) => s.projects)
  const setProjects = useAppStore((s) => s.setProjects)
  const currentProject = useAppStore((s) => s.currentProject)
  const setCurrentProject = useAppStore((s) => s.setCurrentProject)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const [error, setError] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (creating && inputRef.current) inputRef.current.focus()
  }, [creating])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      const target = e.target as Node
      if (dropdownRef.current?.contains(target)) return
      if (btnRef.current?.contains(target)) return
      setOpen(false)
    }
    if (open) {
      document.addEventListener("mousedown", handleClick)
      return () => document.removeEventListener("mousedown", handleClick)
    }
  }, [open])

  const handleToggle = () => {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 4, left: rect.left })
    }
    setOpen(!open)
  }

  const handleSelect = (name: string) => {
    setCurrentProject(name)
    setOpen(false)
  }

  const handleCreate = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    if (trimmed.length > 50) {
      setError("Name too long (max 50 characters)")
      return
    }
    if (/[/\\:*?"<>|]/.test(trimmed)) {
      setError("Name contains invalid characters: / \\ : * ? \" < > |")
      return
    }
    setError("")
    try {
      const proj = await api.createProject(trimmed)
      setProjects([...projects, proj])
      setCurrentProject(proj.name)
      setCreating(false)
      setName("")
      setOpen(false)
    } catch (e: any) {
      setError(e?.message || "Failed to create project")
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setName(v)
    if (v.length > 50) {
      setError("Name too long (max 50 characters)")
    } else if (/[/\\:*?"<>|]/.test(v)) {
      setError("Invalid characters: / \\ : * ? \" < > |")
    } else {
      setError("")
    }
  }

  const handleCreateKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate()
    if (e.key === "Escape") { setCreating(false); setName(""); setError("") }
  }

  const cancelCreate = () => {
    setCreating(false)
    setName("")
    setError("")
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
        title={currentProject}
      >
        <Layers size={16} />
        <span className="flex-1 truncate text-left">{currentProject}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open &&
        createPortal(
          <div
            ref={dropdownRef}
            style={{ position: "fixed", top: pos.top, left: pos.left }}
            className="z-[9999] w-52 bg-[var(--background)] border border-[var(--border)] rounded-lg shadow-lg"
          >
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

            {creating ? (
              <div className="px-2 py-1.5 border-t border-[var(--border)] space-y-1.5">
                <div className="flex gap-1">
                  <input
                    ref={inputRef}
                    value={name}
                    onChange={handleInputChange}
                    onKeyDown={handleCreateKey}
                    placeholder="e.g. 课程资料 or course-notes"
                    className="flex-1 rounded border px-2 py-1 text-xs bg-[var(--background)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <button
                    onClick={handleCreate}
                    disabled={!name.trim() || !!error}
                    className="px-2 py-1 text-xs rounded bg-[var(--primary)] text-white disabled:opacity-50"
                  >
                    Create
                  </button>
                  <button
                    onClick={cancelCreate}
                    className="px-2 py-1 text-xs rounded hover:bg-[var(--accent)] text-[var(--muted-foreground)]"
                  >
                    <X size={12} />
                  </button>
                </div>
                {error && (
                  <p className="text-[11px] text-red-500">{error}</p>
                )}
              </div>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] border-t border-[var(--border)] transition-colors"
              >
                <Plus size={12} />
                New Project
              </button>
            )}
          </div>,
          document.body
        )}
    </>
  )
}
