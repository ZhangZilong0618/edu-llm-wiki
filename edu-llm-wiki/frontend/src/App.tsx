import { useEffect } from "react"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { AppLayout } from "@/components/layout/app-layout"
import { ToastContainer } from "@/components/ui/toast"

export default function App() {
  const setWikiPages = useAppStore((s) => s.setWikiPages)
  const setSourceFiles = useAppStore((s) => s.setSourceFiles)

  // Load initial data
  useEffect(() => {
    api.listPages().then(setWikiPages).catch(console.error)
    api.listSources().then(setSourceFiles).catch(console.error)
  }, [])

  return (
    <>
      <AppLayout />
      <ToastContainer />
    </>
  )
}
