import { useState, useRef, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { Send, Loader2, Plus, Trash2, MessageSquare, MessageCircle, Square, BookOpen, ImagePlus } from "lucide-react"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  cited?: { path: string; title: string; snippet: string }[]
}

type ScopeType = "whole_wiki" | "current_page" | "selected_source"

let idCounter = Date.now()
function nextId() { return `${++idCounter}-${Math.random().toString(36).slice(2, 8)}` }

export function ChatPanel() {
  const conversations = useAppStore((s) => s.conversations)
  const setConversations = useAppStore((s) => s.setConversations)
  const convId = useAppStore((s) => s.currentConversationId)
  const setConvId = useAppStore((s) => s.setCurrentConversationId)
  const selectedPage = useAppStore((s) => s.selectedPage)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const importSelectedSource = useAppStore((s) => s.importSelectedSource)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState<string | null>(null)
  const [convTitle, setConvTitle] = useState("")
  const [scopeType, setScopeType] = useState<ScopeType>("whole_wiki")
  const [chatStatus, setChatStatus] = useState<string | null>(null)
  const [recognizingImage, setRecognizingImage] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const skipLoadRef = useRef(false)
  const convIdRef = useRef(convId)
  convIdRef.current = convId

  const selectedSourceName = selectedSource?.filename || importSelectedSource || null
  const chatScope = {
    type: scopeType,
    page_path: scopeType === "current_page" ? selectedPage?.path || null : null,
    source_name: scopeType === "selected_source" ? selectedSourceName : null,
  }

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
    }).catch(() => {})
  }, [convId])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streaming])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  // Auto-save with debounce
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

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setStreaming(null)
    setChatStatus(null)
  }

  const handleSend = useCallback(async () => {
    if (!input.trim() || streaming) return

    let currentConvId = convId
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
    setChatStatus("Understanding question...")

    if (!convTitle && messages.length === 0) {
      setConvTitle(input.slice(0, 50))
    }

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const effectiveScope = {
        ...chatScope,
        type:
          chatScope.type === "current_page" && !chatScope.page_path
            ? "whole_wiki"
            : chatScope.type === "selected_source" && !chatScope.source_name
              ? "whole_wiki"
              : chatScope.type,
      }
      const apiMessages = newMsgs.filter((m) => m.content !== "").map((m) => ({
        role: m.role,
        content: m.content,
      }))

      let lastContent = ""
      for await (const event of api.chatStream(apiMessages, controller.signal, {
        mode: "ask",
        scope: effectiveScope,
        options: {
          citation_required: true,
          answer_style: "concise",
        },
      })) {
        if (event.type === "status") {
          setChatStatus(event.text)
        } else if (event.type === "cited" || event.type === "sources" || event.type === "final_citations") {
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, cited: event.pages } : m))
        } else if (event.type === "content") {
          lastContent += event.text
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: lastContent } : m))
        } else if (event.type === "replace") {
          lastContent = event.text
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: lastContent } : m))
        }
      }

      setMessages((prev) => {
        autoSave(prev, input.slice(0, 50))
        return prev
      })
    } catch (e: any) {
      if (e?.name === "AbortError") { setStreaming(null); return }
      setMessages((prev) => prev.map((m) =>
        m.id === assistantId && !m.content ? { ...m, content: `Error: ${e.message || e}` } : m
      ))
    }
    setStreaming(null)
    setChatStatus(null)
  }, [input, messages, streaming, convId, convTitle, autoSave, setConvId, chatScope])

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
    const nativeEvent = e.nativeEvent as KeyboardEvent & { isComposing?: boolean }
    if (nativeEvent.isComposing || nativeEvent.keyCode === 229) return
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleImageUpload = async (file: File | null | undefined) => {
    if (!file) return
    setRecognizingImage(true)
    setChatStatus("正在识别图片...")
    try {
      const res = await api.recognizeChatImage(file)
      const extracted = res.text.trim()
      if (!extracted) {
        toast({ type: "error", message: "没有识别到可用文字" })
        return
      }
      const block = `我拍照上传了一道题，请先基于识别内容回答。如果识别有误，请指出需要我确认的地方。\n\n## 图片识别结果\n\n${extracted}`
      setInput((prev) => prev.trim() ? `${prev.trim()}\n\n${block}` : block)
      toast({ type: "success", message: "图片已识别，结果已填入输入框" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "图片识别失败" })
    } finally {
      setRecognizingImage(false)
      setChatStatus(null)
      if (imageInputRef.current) imageInputRef.current.value = ""
    }
  }

  const isEmpty = messages.length === 0 && !convId

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
        {/* Scope */}
        <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b bg-[var(--background)]">
          <div className="flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-xs text-[var(--primary-foreground)]">
            <MessageCircle size={12} />
            Ask
          </div>
          <div className="ml-2 h-4 w-px bg-[var(--border)]" />
          <select
            value={scopeType}
            onChange={(e) => setScopeType(e.target.value as ScopeType)}
            className="h-7 rounded-md border bg-[var(--background)] px-2 text-xs text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
            title="Knowledge scope"
          >
            <option value="whole_wiki">Whole Wiki</option>
            <option value="current_page" disabled={!selectedPage}>Current Page</option>
            <option value="selected_source" disabled={!selectedSourceName}>Selected Source</option>
          </select>
          <span className="min-w-0 truncate text-[11px] text-[var(--muted-foreground)]">
            {scopeType === "current_page" && selectedPage ? selectedPage.title : null}
            {scopeType === "selected_source" && selectedSourceName ? selectedSourceName : null}
            {scopeType === "whole_wiki" ? "Using all wiki pages" : null}
          </span>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isEmpty && (
            <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
              <div className="text-center">
                <BookOpen className="h-10 w-10 mx-auto mb-3 opacity-20" />
                <p className="text-lg mb-2">Knowledge Wiki Assistant</p>
                <p>Ask with citations from your selected scope.</p>
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
                  <details className="mt-2 border-t border-[var(--border)] pt-2">
                    <summary className="cursor-pointer list-none text-[10px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                      Sources ({msg.cited.length})
                    </summary>
                    <div className="mt-1 space-y-1">
                      {msg.cited.map((c) => (
                        <div key={c.path} className="text-[10px] text-[var(--muted-foreground)]">
                          <span className="font-medium">{c.title}</span> — {c.snippet.slice(0, 80)}...
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </div>
          ))}
          {streaming && (
            <div className="flex justify-start">
              <div className="bg-[var(--muted)] rounded-xl px-4 py-2.5 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin text-[var(--muted-foreground)]" />
                <span className="text-[11px] text-[var(--muted-foreground)]">{chatStatus || "Thinking..."}</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 p-3 border-t">
          <div className="flex gap-2">
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => handleImageUpload(e.target.files?.[0])}
            />
            <button
              onClick={() => imageInputRef.current?.click()}
              disabled={!!streaming || recognizingImage}
              className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg border text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)] disabled:opacity-50 transition-colors"
              title="拍照或上传题目图片"
            >
              {recognizingImage ? <Loader2 size={14} className="animate-spin" /> : <ImagePlus size={14} />}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={convId ? "Ask a follow-up..." : "Ask a question about your knowledge base..."}
              className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm bg-[var(--background)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              rows={2}
            />
            {streaming ? (
              <button
                onClick={handleStop}
                className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors"
                title="Stop generating"
              >
                <Square size={14} />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-[var(--primary)] text-white disabled:opacity-50 transition-opacity"
              >
                <Send size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
