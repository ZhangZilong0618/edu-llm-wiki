import { create } from "zustand"

const STORAGE_KEY = "edu-llm-wiki.user"
const SUGGESTIONS = ["default", "learner-a", "learner-b", "learner-c"]

function readInitial(): string {
  if (typeof window === "undefined") return "default"
  const saved = window.localStorage.getItem(STORAGE_KEY)
  return saved && saved.trim() ? saved : "default"
}

export const useUserStore = create<{
  userId: string
  setUserId: (id: string) => void
  suggestions: readonly string[]
}>((set) => ({
  userId: readInitial(),
  setUserId: (id) => {
    const next = id.trim() || "default"
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, next)
    set({ userId: next })
  },
  suggestions: SUGGESTIONS,
}))
