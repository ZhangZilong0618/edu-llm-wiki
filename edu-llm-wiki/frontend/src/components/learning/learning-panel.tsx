"use client"
// 8-dim learner state panel.
// Fetches /api/learning/state and renders the weak KCs, misconception
// clusters, readiness progress and SR queue.
import { useEffect, useState } from "react"
import { toast } from "@/components/ui/toast"
import { Brain, AlertTriangle, Sparkles, Target, Trophy, RefreshCw, CheckCircle2, ListChecks, Download } from "lucide-react"
import { api } from "@/lib/api"
import { useUserStore } from "@/stores/user-store"
import { PosteriorBar } from "./posterior-bar"
import { ReviewSession } from "./review-session"
export function LearningPanel({ userId, projectId }: { userId?: string; projectId?: string }) {
  const activeUser = useUserStore((s) => s.userId)
  const effectiveUser = userId ?? activeUser
  const [state, setState] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [tick, setTick] = useState(0)
  const [resetting, setResetting] = useState(false)
  const [refitting, setRefitting] = useState(false)
  const reload = () => setTick((t) => t + 1)
  const exportState = () => {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `learner-state-${effectiveUser}-${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast({ type: "success", message: "Learning profile downloaded" })
  }

  const handleRefit = async () => {
    if (refitting) return
    const adminToken = typeof window !== "undefined"
      ? window.localStorage.getItem("edu-llm-wiki.adminToken") || ""
      : ""
    setRefitting(true)
    try {
      const res = await api.refitBkt(
        effectiveUser,
        projectId || "default",
        adminToken || undefined,
      )
      if (res.status === "ok") {
        const p = res.params || {}
        toast({
          type: "success",
          message: `Refit BKT from ${res.observations} records: p_known=${p.p_known}, p_t=${p.p_t}, p_g=${p.p_g}, p_s=${p.p_s}`,
        })
      } else {
        toast({ type: "error", message: "Insufficient data (at least 5 attempts required)" })
      }
      reload()
    } catch (e: any) {
      if (e?.message?.includes("admin_token") || e?.status === 401) {
        toast({ type: "error", message: "The backend requires an Admin Token; please configure it first in Settings → Admin." })
      } else {
        toast({ type: "error", message: e?.message || "BKT fitting failed" })
      }
    } finally {
      setRefitting(false)
    }
  }

  const handleReset = async () => {
    if (resetting) return
    if (typeof window !== "undefined" && !window.confirm(
      `This will clear all learning records for this learner in the current project (BKT / review / confidence / error causes / answers). This action cannot be undone. Continue?`,
    )) return
    setResetting(true)
    const adminToken = typeof window !== "undefined"
      ? window.localStorage.getItem("edu-llm-wiki.adminToken") || ""
      : ""
    try {
      const res = await api.resetLearnerState(
        effectiveUser,
        projectId || "default",
        adminToken || undefined,
      )
      const total = Object.values(res.deleted || {}).reduce((a, b) => a + (b || 0), 0)
      toast({ type: "success", message: `Cleared ${total} learning records` })
      reload()
    } catch (e: any) {
      if (e?.message?.includes("admin_token") || e?.status === 401) {
        toast({ type: "error", message: "The backend requires an Admin Token; please configure it first in Settings → Admin." })
      } else {
        toast({ type: "error", message: e?.message || "Reset Failed" })
      }
    } finally {
      setResetting(false)
    }
  }
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.getLearningState(effectiveUser)
      .then((s) => { if (!cancelled) setState(s) })
      .catch((e) => toast({ type: "error", message: e?.message || "Failed to load learning profile" }))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [userId, projectId, effectiveUser, tick])
  if (loading) return <div className="text-[11px] text-[var(--muted-foreground)]">Loading profile…</div>
  if (!state) return (
    <div className="rounded-lg border bg-[var(--card)] p-3 text-[11px] text-[var(--muted-foreground)]">
      No learning profile available yet; submit a test or review and check back later.
    </div>
  )
  return (
    <section className="space-y-3 rounded-lg border bg-[var(--card)] p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1 text-xs font-semibold"><Brain size={12} /> Learning Profile</h3>
        <button
          type="button"
          onClick={reload}
          aria-label="Refresh Learning Profile"
          className="flex items-center gap-1 rounded px-1 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        >
          <RefreshCw size={10} /> Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Tile label="BKT Posterior" value={(state.p_known_avg * 100).toFixed(0) + "%"} />
        <Tile label="Overconfident" value={(state.overconfidence_gap * 100).toFixed(0) + "%"} warn={state.overconfidence_gap > 0.2} />
        <Tile label="To Review" value={state.sr_due_today} icon={RefreshCw} />
        <button
          type="button"
          onClick={() => {
            const mastered = state.mastered_kcs || []
            if (mastered.length === 0) {
              toast({ type: "success", message: "No mastered KCs yet; keep answering questions or chatting." })
              return
            }
            const list = mastered.map((k: any) => `${k.title || k.kc_id}（p=${(k.p_known ?? 0).toFixed(2)}）`).join("\n")
            toast({ type: "success", message: list })
          }}
          title="Click to view the list of mastered KCs"
          className="text-left"
        >
          <Tile
            label="Mastered"
            value={`${state.n_kcs_mastered ?? 0} / ${state.n_kcs_tracked ?? 0}`}
            icon={CheckCircle2}
            warn={(state.n_kcs_mastered ?? 0) > 0}
          />
        </button>
        <Tile label="Total Answers" value={state.n_attempts ?? 0} icon={ListChecks} />
        <Tile label="Forgetting Risk" value={(state.decay_risk * 100).toFixed(0) + "%"} warn={state.decay_risk > 0.5} />
      </div>
      <div className="space-y-1">
        <h4 className="flex items-center gap-1 text-[11px] font-medium"><Target size={11} /> Weak Knowledge</h4>
        {(state.weak_kcs || []).slice(0, 4).map((kc: any) => (
          <div key={kc.kc_id} className="flex items-center gap-2 text-[11px]">
            <span className="truncate flex-1">{kc.title || kc.kc_id}</span>
            <span className="w-16"><PosteriorBar p_known={kc.p_known ?? 0} /></span>
          </div>
        ))}
        {(state.weak_kcs || []).length === 0 && <p className="text-[10px] text-[var(--muted-foreground)]">No weak knowledge yet</p>}
      </div>
      {(state.misconception_clusters || []).length > 0 && (
        <div className="space-y-1">
          <h4 className="flex items-center gap-1 text-[11px] font-medium text-amber-600"><AlertTriangle size={11} /> Common Error Patterns</h4>
          {state.misconception_clusters.slice(0, 3).map((m: any) => (
            <p key={m.tag} className="text-[10px] text-[var(--muted-foreground)]">· {m.label} ({m.count})</p>
          ))}
        </div>
      )}
      {(state.transfer_windows || []).length > 0 && (
        <div className="space-y-1">
          <h4 className="flex items-center gap-1 text-[11px] font-medium text-emerald-600"><Sparkles size={11} /> Transfer Opportunities</h4>
          {state.transfer_windows.slice(0, 3).map((t: any, i: number) => (
            <p key={i} className="text-[10px] text-[var(--muted-foreground)]">· {t.from} → {t.to}</p>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <button onClick={() => setReviewOpen(true)} className="flex flex-1 items-center justify-center gap-1 rounded border bg-[var(--primary)] px-2 py-1 text-[11px] text-[var(--primary-foreground)]">
          <Trophy size={11} /> Start Review
        </button>
        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          title="Clear this learner's BKT / SM-2 / confidence / error causes / answer records in the current project"
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-700 hover:bg-amber-100 disabled:opacity-50"
        >
          <RefreshCw size={11} className={resetting ? "animate-spin" : ""} />
          {resetting ? "Resetting..." : "Reset"}
        </button>
        <button
          type="button"
          onClick={handleRefit}
          disabled={refitting}
          title={`Refit BKT parameters from all attempts_raw records (min 5)${state.last_refit_at ? `\nLast refit: ${new Date(state.last_refit_at * 1000).toLocaleString()}` : ""}`}
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-violet-300 bg-violet-50 px-2 py-1 text-[11px] text-violet-700 hover:bg-violet-100 disabled:opacity-50"
        >
          <RefreshCw size={11} className={refitting ? "animate-spin" : ""} />
          {refitting ? "Fitting..." : "Proposed merge"}
        </button>
        <button
          type="button"
          onClick={exportState}
          title="Download the current learner profile (including BKT / SR / mastered KCs) as JSON"
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-slate-300 bg-slate-50 px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
        >
          <Download size={11} /> Export
        </button>
      </div>
      {reviewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setReviewOpen(false)}>
          <div className="max-h-[80vh] w-[28rem] overflow-auto rounded-lg bg-[var(--background)] p-4" onClick={(e) => e.stopPropagation()}>
            <ReviewSession userId={effectiveUser} projectId={projectId} onComplete={() => setReviewOpen(false)} />
          </div>
        </div>
      )}
    </section>
  )
}
function Tile({ label, value, warn, icon: Icon }: any) {
  return (
    <div className={"rounded border p-2 " + (warn ? "border-amber-400" : "")}>
      <div className="flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
        {Icon && <Icon size={10} />}
        {label}
      </div>
      <div className="text-sm font-semibold">{value}</div>
    </div>
  )
}
