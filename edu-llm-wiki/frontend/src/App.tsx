import { useEffect, useRef } from "react"
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
  const projectRef = useRef(currentProject)
  projectRef.current = currentProject

  // Load projects list on mount
  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error)
  }, [])

  // Sync project ID and load data when project changes
  useEffect(() => {
    const project = currentProject
    setProjectId(project)

    // Clear all per-project state immediately
    setWikiPages([])
    setSourceFiles([])
    setSelectedPage(null)
    useAppStore.getState().setSearchResults([])
    useAppStore.getState().setSearchQuery("")
    useAppStore.getState().setConversations([])
    useAppStore.getState().setCurrentConversationId(null)
    useAppStore.getState().setIngestProgress(null)
    useAppStore.getState().setSelectedSource(null)
    useAppStore.getState().setIsSearching(false)

    // Load fresh data for new project (stale results are discarded)
    api.listPages().then((pages) => {
      if (projectRef.current === project) setWikiPages(pages)
    }).catch(console.error)
    api.listSources().then((files) => {
      if (projectRef.current === project) setSourceFiles(files)
    }).catch(console.error)
    api.listConversations().then((convs) => {
      if (projectRef.current === project) useAppStore.getState().setConversations(convs)
    }).catch(() => {})
  }, [currentProject])

  return (
    <>
      <AppLayout />
      <ToastContainer />
    </>
  )
}
