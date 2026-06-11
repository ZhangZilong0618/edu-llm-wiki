"use client"
// 1-5 self-report confidence slider (Karpicke & Roediger 2008 calibration).
// We collect a confidence value alongside the actual correctness to derive
// the overconfidence_gap = mean(confidence) - mean(correct) per learner.
import { useState } from "react"

export function ConfidenceSlider({
  onChange,
  value = 3,
}: {
  onChange: (v: number) => void
  value?: number
}) {
  const [v, setV] = useState(value)
  const labels = ["完全不确定", "有点把握", "中等", "较有把握", "完全确定"]
  return (
    <div className="flex flex-col gap-1 text-xs">
      <label className="text-[10px] text-[var(--muted-foreground)]">
        我的把握
      </label>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={v}
        onChange={(e) => {
          const n = Number(e.target.value)
          setV(n)
          onChange(n)
        }}
        className="w-full accent-violet-500"
      />
      <output className="text-[10px] text-[var(--muted-foreground)]">
        {labels[v - 1]} · {v}/5
      </output>
    </div>
  )
}
