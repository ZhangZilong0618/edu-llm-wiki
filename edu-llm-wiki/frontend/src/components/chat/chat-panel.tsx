import { useState, useRef, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"
import { Send, Loader2, Plus, Trash2, MessageSquare } from "lucide-react"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  cited?: { path: string; title: string; snippet: string }[]
}

let idCounter = 0
function nextId() { return String(++idCounter) }

export function ChatPanel() {
  const conversations = useAppStore((s) => s.conversations)
  const setConversations = useAppStore((s) => s.setConversations)
  const convId = useAppStore((s) => s.currentConversationId)
  const setConvId = useAppStore((s) => s.setCurrentConversationId)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState<string | null>(null)
  const [convTitle, setConvTitle] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const skipLoadRef = useRef(false)
  const convIdRef = useRef(convId) // always-current ref for async closures
  convIdRef.current = convId

  // Load conversation list on mount / project change
  useEffect(() => {
    api.listConversations().then(setConversations).catch(() => {})
  }, [setConversations])

  // Load conversation when switching
  useEffect(() => {
    if (skipLoadRef.current) {
      skipLoadRef.current = false
      return
    }
    if (!convId) {
      setMessages([])
      setConvTitle("")
      return
    }
    api.getConversation(convId).then((c) => {
      setMessages(c.messages || [])
      setConvTitle(c.title || "")
    }).catch(() => {
      // Don't clear messages for 404 — the conversation hasn't been saved yet
    })
  }, [convId])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streaming])

  // Auto-save with debounce (uses ref for latest convId)
  const autoSave = useCallback((msgs: Message[], title?: string) => {
    const id = convIdRef.current
    if (!id) return
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      api.saveConversation({
        id,
        title: title ?? convTitle,
        messages: msgs.map((m) => ({ id: m.id, role: m.role, content: m.content, cited: m.cited })),
      }).then(() => {
        api.listConversations().then(setConversations).catch(() => {})
      }).catch(() => {})
    }, 500)
  }, [convTitle, setConversations])

  const handleSend = useCallback(async () => {
    if (!input.trim() || streaming) return

    let currentConvId = convId
    // Auto-create conversation if none selected
    if (!currentConvId) {
      currentConvId = nextId()
      skipLoadRef.current = true
      setConvId(currentConvId)
    }

    const userMsg: Message = { id: nextId(), role: "user", content: input }
    const assistantId = nextId()
    const newMsgs = [...messages, userMsg, { id: assistantId, role: "assistant" as const, content: "" }]
    setMessages(newMsgs)
    setInput("")
    setStreaming(assistantId)

    // Auto-title from first user message
    if (!convTitle && messages.length === 0) {
      setConvTitle(input.slice(0, 50))
    }

    try {
      const apiMessages = newMsgs.filter((m) => m.content !== "").map((m) => ({
        role: m.role,
        content: m.content,
      }))

      let lastContent = ""
      for await (const event of api.chatStream(apiMessages)) {
        if (event.type === "cited") {
          setMessages((prev) => {
            const next = prev.map((m) => m.id === assistantId ? { ...m, cited: event.pages } : m)
            return next
          })
        } else if (event.type === "content") {
          lastContent += event.text
          setMessages((prev) => {
            const next = prev.map((m) => m.id === assistantId ? { ...m, content: lastContent } : m)
            return next
          })
        }
      }

      // Save completed
      setMessages((prev) => {
        autoSave(prev, input.slice(0, 50))
        return prev
      })
    } catch (e: any) {
      setMessages((prev) => {
        const next = prev.map((m) =>
          m.id === assistantId && !m.content ? { ...m, content: `Error: ${e.message || e}` } : m
        )
        autoSave(next)
        return next
      })
    }
    setStreaming(null)
  }, [input, messages, streaming, convId, convTitle, autoSave, setConvId])

  const handleNewConv = () => {
    setConvId(null)
    setMessages([])
    setConvTitle("")
  }

  const handleDeleteConv = async (id: string) => {
    await api.deleteConversation(id).catch(() => {})
    if (convId === id) {
      setConvId(null)
      setMessages([])
      setConvTitle("")
    }
    api.listConversations().then(setConversations).catch(() => {})
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full">
      {/* Conversation sidebar */}
      <div className="w-44 shrink-0 border-r flex flex-col bg-[var(--sidebar)]">
        <div className="p-2 border-b">
          <button
            onClick={handleNewConv}
            className="w-full flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-lg border border-dashed border-[var(--border)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors"
          >
            <Plus size={12} /> New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {conversations.length === 0 && (
            <p className="px-3 py-6 text-xs text-[var(--muted-foreground)] text-center">
              No saved conversations
            </p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => setConvId(c.id)}
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer text-xs transition-colors ${
                convId === c.id
                  ? "bg-[var(--accent)] text-[var(--foreground)]"
                  : "text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
              }`}
            >
              <MessageSquare size={12} className="shrink-0" />
              <span className="flex-1 truncate">{c.title}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteConv(c.id) }}
                className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 text-red-500 transition-opacity"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && !convId && (
            <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
              <div className="text-center">
                <p className="text-lg mb-2">Edu-LLM-Wiki</p>
                <p>Ask a question about your knowledge base to get started.</p>
              </div>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${
                  msg.role === "user"
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "bg-[var(--muted)] text-[var(--foreground)]"
                }`}
              >
                {msg.role === "assistant" ? (
                  <div className="text-sm">
                    <Markdown>{msg.content || "..."}</Markdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}

                {msg.cited && msg.cited.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-[var(--border)]">
                    <p className="text-[10px] font-medium text-[var(--muted-foreground)] mb-1">Sources:</p>
                    {msg.cited.map((c) => (
                      <div key={c.path} className="text-[10px] text-[var(--muted-foreground)]">
                        <span className="font-medium">{c.title}</span> — {c.snippet.slice(0, 80)}...
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {streaming && (
            <div className="flex justify-start">
              <div className="bg-[var(--muted)] rounded-xl px-4 py-2.5 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin text-[var(--muted-foreground)]" />
                <span className="text-[11px] text-[var(--muted-foreground)]">Thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 p-3 border-t">
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={convId ? "Ask a follow-up..." : "Ask a question about your knowledge base..."}
              className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm bg-[var(--background)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              rows={2}
            />
            <button
              onClick={handleSend}
              disabled={!!streaming || !input.trim()}
              className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-[var(--primary)] text-white disabled:opacity-50 transition-opacity"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
