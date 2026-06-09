import { useEffect, useState, useCallback, useRef } from "react"
import { Check, X, AlertTriangle, Loader } from "lucide-react"

export interface ToastState {
  type: "success" | "error" | "loading"
  message: string
}

let pushToast: (t: ToastState | null) => void = () => {}

export function toast(state: ToastState | null) {
  pushToast(state)
}

export function ToastContainer() {
  const [toast, setToast] = useState<ToastState | null>(null)
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  pushToast = useCallback((t: ToastState | null) => {
    clearTimer()
    if (t === null) {
      setVisible(false)
      timerRef.current = setTimeout(() => setToast(null), 300)
    } else {
      setToast(t)
      requestAnimationFrame(() => setVisible(true))
      if (t.type !== "loading") {
        timerRef.current = setTimeout(() => {
          setVisible(false)
          timerRef.current = setTimeout(() => setToast(null), 300)
        }, 3000)
      }
    }
  }, [clearTimer])

  if (!toast) return null

  const icon = toast.type === "success"
    ? <Check size={16} />
    : toast.type === "error"
    ? <AlertTriangle size={16} />
    : <Loader size={16} className="animate-spin" />

  const bg = toast.type === "success"
    ? "bg-green-600"
    : toast.type === "error"
    ? "bg-red-600"
    : "bg-[var(--primary)]"

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-lg text-white text-sm shadow-lg transition-all duration-300 ${bg}`}
      style={{ opacity: visible ? 1 : 0, transform: visible ? "translateY(0)" : "translateY(16px)" }}
    >
      {icon}
      <span>{toast.message}</span>
    </div>
  )
}