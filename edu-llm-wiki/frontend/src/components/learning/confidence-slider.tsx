"use client"
// 1-5 self-report confidence slider (Karpicke & Roediger 2008 calibration).
// We collect a confidence value alongside actual correctness to derive the
// overconfidence gap for the learner model.
export function ConfidenceSlider({
  onChange,
  value = 3,
}: {
  onChange: (v: number) => void
  value?: number
}) {
  const labels = ["完全不确定", "有点把握", "中等", "较有把握", "完全确定"]
  const current = Math.min(5, Math.max(1, Math.round(value)))
  return (
    <div className="flex flex-col gap-1 text-xs">
      <label className="text-[10px] text-[var(--muted-foreground)]">我的把握</label>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={current}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-violet-500"
      />
      <output className="text-[10px] text-[var(--muted-foreground)]">
        {labels[current - 1]} · {current}/5
      </output>
    </div>
  )
}
