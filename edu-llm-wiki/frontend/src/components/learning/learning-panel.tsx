"use client"
// 8-dim learner state panel.
// Fetches /api/learning/state and renders the weak KCs, misconception
// clusters, readiness progress and SR queue.
import { useEffect, useState } from "react"
import { Brain, AlertTriangle, Sparkles, Target, Trophy, RefreshCw } from "lucide-react"
import { api } from "@/lib/api"
import { PosteriorBar } from "./posterior-bar"
import { ReviewSession } from "./review-session"
export function LearningPanel({ userId = "default", projectId }: { userId?: string; projectId?: string }) {
  const [state, setState] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [reviewOpen, setReviewOpen] = useState(false)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.getLearningState(userId).then((s) => { if (!cancelled) setState(s) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [userId, projectId])
  if (loading) return <div className="text-[11px] text-[var(--muted-foreground)]">载入画像…</div>
  if (!state) return null
  return (
    <section className="space-y-3 rounded-lg border bg-[var(--card)] p-3">
      <h3 className="flex items-center gap-1 text-xs font-semibold"><Brain size={12} /> 学习画像</h3>
      <div className="grid grid-cols-2 gap-2">
        <Tile label="BKT 后验" value={(state.p_known_avg * 100).toFixed(0) + "%"} />
        <Tile label="过度自信" value={(state.overconfidence_gap * 100).toFixed(0) + "%"} warn={state.overconfidence_gap > 0.2} />
        <Tile label="待复习" value={state.sr_due_today} icon={RefreshCw} />
        <Tile label="遗忘风险" value={(state.decay_risk * 100).toFixed(0) + "%"} warn={state.decay_risk > 0.5} />
      </div>
      <div className="space-y-1">
        <h4 className="flex items-center gap-1 text-[11px] font-medium"><Target size={11} /> 薄弱知识</h4>
        {(state.weak_kcs || []).slice(0, 4).map((kc: any) => (
          <div key={kc.kc_id} className="flex items-center gap-2 text-[11px]">
            <span className="truncate flex-1">{kc.title || kc.kc_id}</span>
            <span className="w-16"><PosteriorBar p_known={kc.p_known ?? 0} /></span>
          </div>
        ))}
        {(state.weak_kcs || []).length === 0 && <p className="text-[10px] text-[var(--muted-foreground)]">暂无薄弱知识</p>}
      </div>
      {(state.misconception_clusters || []).length > 0 && (
        <div className="space-y-1">
          <h4 className="flex items-center gap-1 text-[11px] font-medium text-amber-600"><AlertTriangle size={11} /> 易错模式</h4>
          {state.misconception_clusters.slice(0, 3).map((m: any) => (
            <p key={m.tag} className="text-[10px] text-[var(--muted-foreground)]">· {m.label} ({m.count})</p>
          ))}
        </div>
      )}
      {(state.transfer_windows || []).length > 0 && (
        <div className="space-y-1">
          <h4 className="flex items-center gap-1 text-[11px] font-medium text-emerald-600"><Sparkles size={11} /> 迁移机会</h4>
          {state.transfer_windows.slice(0, 3).map((t: any, i: number) => (
            <p key={i} className="text-[10px] text-[var(--muted-foreground)]">· {t.from} → {t.to}</p>
          ))}
        </div>
      )}
      <button onClick={() => setReviewOpen(true)} className="flex w-full items-center justify-center gap-1 rounded border bg-[var(--primary)] px-2 py-1 text-[11px] text-[var(--primary-foreground)]">
        <Trophy size={11} /> 进入复习
      </button>
      {reviewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setReviewOpen(false)}>
          <div className="max-h-[80vh] w-[28rem] overflow-auto rounded-lg bg-[var(--background)] p-4" onClick={(e) => e.stopPropagation()}>
            <ReviewSession userId={userId} projectId={projectId} onComplete={() => setReviewOpen(false)} />
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
