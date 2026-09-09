"use client"
// Spaced-repetition review shell.
// Pulls the next N due items from /api/learning/schedule, lets the learner
// self-rate 0-5 (SM-2 quality) and records each answer back through the
// mastery observer so BKT, SR and confidence update together.

import { useEffect, useState } from "react"
import { Check, X, ChevronRight } from "lucide-react"

import { api } from "@/lib/api"

import { ConfidenceSlider } from "./confidence-slider"

export function ReviewSession({
  userId = "default",
  projectId,
  limit = 8,
  onComplete,
}: {
  userId?: string
  projectId?: string
  limit?: number
  onComplete?: () => void
}) {
  const [items, setItems] = useState<any[]>([])
  const [idx, setIdx] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const [confidence, setConfidence] = useState(3)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState({ correct: 0, total: 0 })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await api.getLearningSchedule(userId, limit)
        if (!cancelled) setItems(Array.isArray(data) ? data : [])
      } catch {
        if (!cancelled) setItems([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [userId, projectId, limit])

  if (!items.length) {
    return (
      <div className="rounded-lg border p-6 text-center text-sm text-[var(--muted-foreground)]">
        今天没有需要复习的知识点 — 去做一些新题目吧。
      </div>
    )
  }

  const item = items[idx]
  const finished = idx >= items.length

  const submit = async (correct: boolean) => {
    setBusy(true)
    try {
      await api.postLearningReview(
        item.kc_id,
        correct,
        confidence,
        correct ? Math.min(5, confidence + 1) : Math.max(0, confidence - 2),
        userId,
      )
      setStats((s) => ({ correct: s.correct + (correct ? 1 : 0), total: s.total + 1 }))
    } catch {
      // swallow — the schedule is best-effort
    }
    setBusy(false)
    setRevealed(false)
    setConfidence(3)
    setIdx((n) => n + 1)
  }

  if (finished) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-sm">
          本轮复习完成 — {stats.correct}/{stats.total} 答对
        </p>
        {onComplete && (
          <button
            onClick={onComplete}
            className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white"
          >
            完成
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="text-[10px] text-[var(--muted-foreground)]">
        {idx + 1} / {items.length}
      </div>
      <h3 className="text-sm font-semibold">{item.title || item.kc_id}</h3>
      <p className="text-xs text-[var(--muted-foreground)]">{item.prompt || "复习这道题"}</p>
      {revealed && item.expected && (
        <p className="rounded bg-slate-100 px-3 py-2 text-xs">参考：{item.expected}</p>
      )}
      <ConfidenceSlider value={confidence} onChange={setConfidence} />
      <div className="flex gap-2">
        {!revealed ? (
          <button
            onClick={() => setRevealed(true)}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-xs"
          >
            显示答案
          </button>
        ) : (
          <>
            <button
              disabled={busy}
              onClick={() => submit(false)}
              className="inline-flex items-center gap-1 rounded-md bg-rose-100 px-3 py-1.5 text-xs text-rose-700"
            >
              <X size={12} /> 答错
            </button>
            <button
              disabled={busy}
              onClick={() => submit(true)}
              className="inline-flex items-center gap-1 rounded-md bg-emerald-100 px-3 py-1.5 text-xs text-emerald-700"
            >
              <Check size={12} /> 答对
            </button>
          </>
        )}
        <ChevronRight size={14} className="ml-auto text-slate-300" />
      </div>
    </div>
  )
}
