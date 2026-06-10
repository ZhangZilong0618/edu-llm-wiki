// Subscribes to /api/graph/events via EventSource. Returns the latest
// buffered events since the component mounted (or since ``since`` was
// recorded). Closes the stream on unmount.

import { useEffect, useState } from "react"

const MAX_BUFFER = 64

export interface GraphEvent {
  id: number
  event_type: string
  project_id: string
  payload: Record<string, unknown>
  created_at: number
}

export function useGraphEvents(projectId: string): GraphEvent[] {
  const [events, setEvents] = useState<GraphEvent[]>([])

  useEffect(() => {
    if (typeof window === "undefined") return
    const url = `/api/graph/events/stream?project_id=${encodeURIComponent(projectId)}`
    const es = new EventSource(url)

    const ingest = (raw: MessageEvent<string>) => {
      try {
        const data: GraphEvent = JSON.parse(raw.data)
        setEvents((prev) => {
          const next = [data, ...prev]
          return next.length > MAX_BUFFER ? next.slice(0, MAX_BUFFER) : next
        })
      } catch {
        // ignore malformed lines — SSE best-effort
      }
    }

    es.onmessage = ingest
    es.onerror = () => {
      // EventSource will auto-reconnect; nothing to do here. We just make
      // sure a console error doesn't spam during long sessions.
    }

    return () => es.close()
  }, [projectId])

  return events
}