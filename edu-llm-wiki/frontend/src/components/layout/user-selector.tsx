"use client"
import { useState } from "react"
import { useUserStore } from "@/stores/user-store"
import { User, Pencil, Check, X } from "lucide-react"

export function UserSelector() {
  const userId = useUserStore((s) => s.userId)
  const setUserId = useUserStore((s) => s.setUserId)
  const suggestions = useUserStore((s) => s.suggestions)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(userId)

  const open = () => {
    setDraft(userId)
    setEditing(true)
  }
  const apply = () => {
    setUserId(draft)
    setEditing(false)
  }
  const cancel = () => setEditing(false)

  if (!editing) {
    return (
      <div className="px-3 py-2 border-b border-[var(--border)]">
        <button
          type="button"
          onClick={open}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-[var(--accent)]"
          aria-label="切换当前学习者"
          title="当前学习者会用于 BKT/SM-2/聊天画像/复习队列。点此切换。"
        >
          <User size={12} className="text-[var(--muted-foreground)]" />
          <span className="flex-1 truncate text-[var(--sidebar-foreground)]">
            <span className="block text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">当前学习者</span>
            <span className="font-medium">{userId}</span>
          </span>
          <Pencil size={11} className="text-[var(--muted-foreground)]" />
        </button>
      </div>
    )
  }

  return (
    <div className="px-3 py-2 border-b border-[var(--border)]">
      <label className="block text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">切换学习者</label>
      <div className="mt-1 flex gap-1">
        <input
          aria-label="学习者 ID"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply()
            if (e.key === "Escape") cancel()
          }}
          className="flex-1 rounded-md border bg-[var(--background)] px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
          autoFocus
        />
        <button
          type="button"
          onClick={apply}
          aria-label="确认"
          className="rounded-md bg-[var(--primary)] px-2 text-white"
        >
          <Check size={12} />
        </button>
        <button
          type="button"
          onClick={cancel}
          aria-label="取消"
          className="rounded-md border px-2"
        >
          <X size={12} />
        </button>
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setDraft(s)}
            className={`rounded-md border px-1.5 py-0.5 text-[10px] ${draft === s ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
