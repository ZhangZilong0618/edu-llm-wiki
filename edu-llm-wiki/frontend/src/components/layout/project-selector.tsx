import { useState, useRef, useEffect, useCallback } from "react"
import { createPortal } from "react-dom"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { Plus, Layers, ChevronDown, X, Trash2 } from "lucide-react"

export function ProjectSelector() {
  const projects = useAppStore((s) => s.projects)
  const setProjects = useAppStore((s) => s.setProjects)
  const currentProject = useAppStore((s) => s.currentProject)
  const setCurrentProject = useAppStore((s) => s.setCurrentProject)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0, dropUp: false })
  const [error, setError] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
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

  const calcPosition = useCallback(() => {
    if (!btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const dropdownMaxH = 320 // approx max-h-80
    const spaceBelow = window.innerHeight - rect.bottom - 8
    const dropUp = spaceBelow < dropdownMaxH && rect.top > spaceBelow
    const top = dropUp ? rect.top - 8 : rect.bottom + 4
    // Keep within viewport horizontally
    let left = rect.left
    const dropdownWidth = Math.max(rect.width, 220)
    if (left + dropdownWidth > window.innerWidth - 8) {
      left = window.innerWidth - dropdownWidth - 8
    }
    setPos({ top: dropUp ? top - dropdownMaxH : top, left, width: dropdownWidth, dropUp })
  }, [])

  const handleToggle = () => {
    if (!open) {
      calcPosition()
    }
    setOpen(!open)
  }

  const handleSelect = (projName: string) => {
    setCurrentProject(projName)
    setOpen(false)
    setCreating(false)
  }

  const handleCreate = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    if (trimmed.length > 50) {
      setError("Name too long (max 50 characters)")
      return
    }
    if (/[/\\:*?"<>|]/.test(trimmed)) {
      setError('Invalid characters: / \\ : * ? " < > |')
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

  const handleDelete = async (projName: string) => {
    if (projName === "default") return
    try {
      await api.deleteProject(projName)
      setProjects(projects.filter((p) => p.name !== projName))
      if (currentProject === projName) {
        setCurrentProject("default")
      }
      setDeleting(null)
    } catch (e: any) {
      setError(e?.message || "Failed to delete project")
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setName(v)
    if (v.length > 50) {
      setError("Name too long (max 50 characters)")
    } else if (/[/\\:*?"<>|]/.test(v)) {
      setError('Invalid characters: / \\ : * ? " < > |')
    } else {
      setError("")
    }
  }

  const handleCreateKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate()
    if (e.key === "Escape") {
      setCreating(false)
      setName("")
      setError("")
    }
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
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxHeight: creating ? 200 : 320,
            }}
            className="z-[9999] bg-[var(--background)] border border-[var(--border)] rounded-lg shadow-lg flex flex-col overflow-hidden"
          >
            {/* Project list */}
            <div className="flex-1 overflow-y-auto">
              {projects.map((p) => (
                <div
                  key={p.name}
                  className={`group flex items-center text-sm transition-colors ${
                    p.name === currentProject
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--foreground)] hover:bg-[var(--accent)]"
                  }`}
                >
                  <button
                    onClick={() => handleSelect(p.name)}
                    className="flex-1 text-left px-3 py-2 truncate"
                  >
                    {p.title}
                  </button>
                  {p.name !== "default" && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        deleting === p.name ? handleDelete(p.name) : setDeleting(p.name)
                      }}
                      className={`px-2 py-2 transition-colors ${
                        deleting === p.name
                          ? "text-red-500 bg-red-50 dark:bg-red-950/30"
                          : "text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 hover:text-red-500"
                      }`}
                      title={deleting === p.name ? "Click again to confirm" : "Delete project"}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))}
              {projects.length === 0 && (
                <p className="px-3 py-3 text-xs text-[var(--muted-foreground)] text-center">
                  No projects yet
                </p>
              )}
            </div>

            {/* Create form */}
            {creating ? (
              <div className="px-3 py-2.5 border-t border-[var(--border)] space-y-2">
                <input
                  ref={inputRef}
                  value={name}
                  onChange={handleInputChange}
                  onKeyDown={handleCreateKey}
                  placeholder="e.g. 课程资料 or course-notes"
                  className="w-full rounded-md border px-2.5 py-1.5 text-xs bg-[var(--background)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                <div className="flex gap-1.5">
                  <button
                    onClick={handleCreate}
                    disabled={!name.trim() || !!error}
                    className="flex-1 px-2 py-1 text-xs rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] disabled:opacity-50 hover:opacity-90 transition-opacity"
                  >
                    Create
                  </button>
                  <button
                    onClick={cancelCreate}
                    className="px-2 py-1 text-xs rounded-md border hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition-colors"
                  >
                    Cancel
                  </button>
                </div>
                {error && <p className="text-[11px] text-red-500">{error}</p>}
              </div>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] border-t border-[var(--border)] transition-colors"
              >
                <Plus size={12} />
                New Project
              </button>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}
