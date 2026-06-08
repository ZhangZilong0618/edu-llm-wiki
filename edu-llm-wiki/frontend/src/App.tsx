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
    // Clear all per-project state immediately
    setWikiPages([])
    setSourceFiles([])
    setSelectedPage(null)
    useAppStore.getState().setSearchResults([])
    useAppStore.getState().setSearchQuery("")
    useAppStore.getState().setConversations([])
    useAppStore.getState().setCurrentConversationId(null)
    useAppStore.getState().setIngestProgress(null)

    // Load fresh data for new project
    api.listPages().then(setWikiPages).catch(console.error)
    api.listSources().then(setSourceFiles).catch(console.error)
    api.listConversations().then(useAppStore.getState().setConversations).catch(() => {})
  }, [currentProject])

  return (
    <>
      <AppLayout />
      <ToastContainer />
    </>
  )
}
