import { useEffect } from "react"
import { useAppStore } from "@/stores/app-store"
import { api, setProjectId } from "@/lib/api"
import { AppLayout } from "@/components/layout/app-layout"
import { ToastContainer } from "@/components/ui/toast"

export default function App() {
  const currentProject = useAppStore((s) => s.currentProject)
  const setWikiPages = useAppStore((s) => s.setWikiPages)
  const setSourceFiles = useAppStore((s) => s.setSourceFiles)
  const setProjects = useAppStore((s) => s.setProjects)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)

  // Sync project ID to API module
  useEffect(() => {
    setProjectId(currentProject)
  }, [currentProject])

  // Load projects list on mount
  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error)
  }, [])

  // Load wiki pages and sources when project changes
  useEffect(() => {
    // Clear stale data immediately
    setWikiPages([])
    setSourceFiles([])
    setSelectedPage(null)
    api.listPages().then(setWikiPages).catch(console.error)
    api.listSources().then(setSourceFiles).catch(console.error)
  }, [currentProject])

  return (
    <>
      <AppLayout />
      <ToastContainer />
    </>
  )
}
