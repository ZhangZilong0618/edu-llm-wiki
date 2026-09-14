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
    toast({ type: "success", message: "学习画像已下载" })
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
          message: `已用 ${res.observations} 条记录拟合 BKT：p_known=${p.p_known}, p_t=${p.p_t}, p_g=${p.p_g}, p_s=${p.p_s}`,
        })
      } else {
        toast({ type: "error", message: "数据不足（至少 5 条 attempt）" })
      }
      reload()
    } catch (e: any) {
      if (e?.message?.includes("admin_token") || e?.status === 401) {
        toast({ type: "error", message: "后端要求 Admin Token，请先在 Settings → Admin 中配置。" })
      } else {
        toast({ type: "error", message: e?.message || "BKT 拟合失败" })
      }
    } finally {
      setRefitting(false)
    }
  }

  const handleReset = async () => {
    if (resetting) return
    if (typeof window !== "undefined" && !window.confirm(
      `将清空该学习者在当前项目中的所有学习记录（BKT / 复习 / 信心 / 错因 / 答题），此操作不可撤销。继续？`,
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
      toast({ type: "success", message: `已清空 ${total} 条学习记录` })
      reload()
    } catch (e: any) {
      if (e?.message?.includes("admin_token") || e?.status === 401) {
        toast({ type: "error", message: "后端要求 Admin Token，请先在 Settings → Admin 中配置。" })
      } else {
        toast({ type: "error", message: e?.message || "重置失败" })
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
      .catch((e) => toast({ type: "error", message: e?.message || "加载学习画像失败" }))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [userId, projectId, effectiveUser, tick])
  if (loading) return <div className="text-[11px] text-[var(--muted-foreground)]">载入画像…</div>
  if (!state) return (
    <div className="rounded-lg border bg-[var(--card)] p-3 text-[11px] text-[var(--muted-foreground)]">
      暂无可用的学习画像，提交一次测试或复习后再来查看。
    </div>
  )
  return (
    <section className="space-y-3 rounded-lg border bg-[var(--card)] p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1 text-xs font-semibold"><Brain size={12} /> 学习画像</h3>
        <button
          type="button"
          onClick={reload}
          aria-label="刷新学习画像"
          className="flex items-center gap-1 rounded px-1 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        >
          <RefreshCw size={10} /> 刷新
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Tile label="BKT 后验" value={(state.p_known_avg * 100).toFixed(0) + "%"} />
        <Tile label="过度自信" value={(state.overconfidence_gap * 100).toFixed(0) + "%"} warn={state.overconfidence_gap > 0.2} />
        <Tile label="待复习" value={state.sr_due_today} icon={RefreshCw} />
        <Tile
          label="已掌握"
          value={`${state.n_kcs_mastered ?? 0} / ${state.n_kcs_tracked ?? 0}`}
          icon={CheckCircle2}
          warn={(state.n_kcs_mastered ?? 0) > 0}
        />
        <Tile label="总答题数" value={state.n_attempts ?? 0} icon={ListChecks} />
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
      <div className="flex gap-1.5">
        <button onClick={() => setReviewOpen(true)} className="flex flex-1 items-center justify-center gap-1 rounded border bg-[var(--primary)] px-2 py-1 text-[11px] text-[var(--primary-foreground)]">
          <Trophy size={11} /> 进入复习
        </button>
        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          title="清空该学习者在当前项目中的 BKT / SM-2 / 信心 / 错因 / 答题记录"
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-700 hover:bg-amber-100 disabled:opacity-50"
        >
          <RefreshCw size={11} className={resetting ? "animate-spin" : ""} />
          {resetting ? "重置中..." : "重置"}
        </button>
        <button
          type="button"
          onClick={handleRefit}
          disabled={refitting}
          title={`用 attempts_raw 全量记录重算 BKT 参数（至少 5 条才拟合）${state.last_refit_at ? `\n上次拟合: ${new Date(state.last_refit_at * 1000).toLocaleString()}` : ""}`}
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-violet-300 bg-violet-50 px-2 py-1 text-[11px] text-violet-700 hover:bg-violet-100 disabled:opacity-50"
        >
          <RefreshCw size={11} className={refitting ? "animate-spin" : ""} />
          {refitting ? "拟合中..." : "拟合并"}
        </button>
        <button
          type="button"
          onClick={exportState}
          title="下载当前学习者画像（含 BKT / SR / 已掌握 KCs）为 JSON"
          className="flex shrink-0 items-center justify-center gap-1 rounded border border-slate-300 bg-slate-50 px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
        >
          <Download size={11} /> 导出
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
