import { useState, useRef, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAppStore } from "@/stores/app-store"
import { Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { useUserStore } from "@/stores/user-store"
import { Send, Loader2, Plus, Trash2, MessageSquare, MessageCircle, Square, BookOpen, ImagePlus, User, RefreshCw, Pencil, Copy, Download, Link as LinkIcon, X, Bot } from "lucide-react"

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
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const importSelectedSource = useAppStore((s) => s.importSelectedSource)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState<string | null>(null)
  const [stoppedMessageIds, setStoppedMessageIds] = useState<Set<string>>(() => new Set())
  const [stoppedAt, setStoppedAt] = useState<Map<string, number>>(() => new Map())
  const [convTitle, setConvTitle] = useState("")
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [scopeType, setScopeType] = useState<ScopeType>("whole_wiki")
  const [chatStatus, setChatStatus] = useState<string | null>(null)
  const [recognizingImage, setRecognizingImage] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const skipLoadRef = useRef(false)
  const convIdRef = useRef(convId)
  convIdRef.current = convId
  const userId = useUserStore((s) => s.userId)
  const [llmModel, setLlmModel] = useState<string>("")
  useEffect(() => {
    api.getLlmSettings().then((s) => setLlmModel(s.llm_model)).catch(() => {})
  }, [])

  const selectedSourceName = selectedSource?.filename || importSelectedSource || null
  const chatScope = {
    type: scopeType,
    page_path: scopeType === "current_page" ? selectedPage?.path || null : null,
    source_name: scopeType === "selected_source" ? selectedSourceName : null,
  }

  // Load conversation list on mount / project change
  useEffect(() => {
    setLoadingConversations(true)
    api.listConversations()
      .then(setConversations)
      .catch(() => {})
      .finally(() => setLoadingConversations(false))
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
      setStoppedMessageIds(new Set())
      setUnreadCount(0)
      lastSeenIndex.current = (c.messages || []).length
    }).catch(() => {})
  }, [convId])

  // Auto-scroll: only when the user is already at (or near) the bottom of
  // the message list. Once they scroll up to read, leave them alone and
  // surface a button to jump back to the latest message.
  const scrollHostRef = useRef<HTMLDivElement | null>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenIndex = useRef(0)
  useEffect(() => {
    if (messages.length > lastSeenIndex.current) {
      if (!stickToBottom) {
        setUnreadCount((c) => c + (messages.length - lastSeenIndex.current))
      }
    }
    lastSeenIndex.current = messages.length
    if (!stickToBottom) return
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streaming, stickToBottom])
  useEffect(() => {
    const el = scrollHostRef.current
    if (!el) return
    const onScroll = () => {
      const distance = el.scrollHeight - el.clientHeight - el.scrollTop
      setStickToBottom(distance < 80)
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

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
    regenerateNextRef.current = false
    if (streaming) {
      setStoppedMessageIds((prev) => {
        const next = new Set(prev)
        next.add(streaming)
        return next
      })
      setStoppedAt((prev) => {
        const next = new Map(prev)
        next.set(streaming, Date.now())
        return next
      })
    }
    setStreaming(null)
    setChatStatus(null)
    // Persist whatever we already streamed so the partial response is
    // not lost on reload. Use messagesRef so the call sees the most
    // recent streamed chunks.
    if (convIdRef.current) {
      autoSave(messagesRef.current, convTitle)
    }
  }

  const handleSendRef = useRef<(() => void) | null>(null)
  // Mirror of `messages` so non-React callbacks (handleStop, handleNewConv)
  // always see the latest streamed content.
  const messagesRef = useRef<Message[]>([])
  useEffect(() => { messagesRef.current = messages }, [messages])
  // When true, the next handleSend call will stream a new assistant response
  // without re-appending the last user message (used by "regenerate").
  const regenerateNextRef = useRef(false)
  const handleSend = useCallback(async () => {
    if (!input.trim() || streaming) return

    let currentConvId = convId
    if (!currentConvId) {
      currentConvId = nextId()
      skipLoadRef.current = true
      setConvId(currentConvId)
    }

    const assistantId = nextId()
    let baseMsgs = messages
    if (regenerateNextRef.current) {
      // Drop the most recent user message; it will be re-sent as part of the
      // chat history to the model, but we do not want to append a duplicate
      // "user" bubble in the UI.
      baseMsgs = messages.slice(0, -1)
      regenerateNextRef.current = false
    } else {
      const userMsg: Message = { id: nextId(), role: "user", content: input }
      baseMsgs = [...messages, userMsg]
    }
    const newMsgs = [...baseMsgs, { id: assistantId, role: "assistant" as const, content: "" }]
    setMessages(newMsgs)
    setInput("")
    setStreaming(assistantId)
    setChatStatus("Understanding question...")
    textareaRef.current?.focus()

    if (!convTitle && messages.length === 0) {
      const lastUser = [...messages].reverse().find((m) => m.role === "user")
      const titleSeed = lastUser?.content?.trim() || input.trim()
      setConvTitle(titleSeed.slice(0, 50))
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
        user_id: userId,
        conversation_id: currentConvId ?? "default",
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
        const lastUser = [...prev].reverse().find((m) => m.role === "user")
        const titleSeed = lastUser?.content?.trim() || convTitle
        autoSave(prev, titleSeed.slice(0, 50))
        return prev
      })
    } catch (e: any) {
      if (e?.name === "AbortError") { setStreaming(null); return }
      const message = e?.message || "请求失败，请稍后再试"
      toast({ type: "error", message })
      setMessages((prev) => prev.map((m) =>
        m.id === assistantId && !m.content ? { ...m, content: `Error: ${message}` } : m
      ))
    }
    setStreaming(null)
    setChatStatus(null)
  }, [input, messages, streaming, convId, convTitle, autoSave, setConvId, chatScope, userId])
  handleSendRef.current = handleSend

  const openPage = async (path: string) => {
    if (!path) return
    try {
      const page = await api.getPage(path)
      setSelectedPage(page)
      setActiveView("wiki")
    } catch (e: any) {
      toast({ type: "error", message: e?.message || `加载页面失败：${path}` })
    }
  }

  const handleNewConv = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    regenerateNextRef.current = false
    if (convIdRef.current && messagesRef.current.length > 0) {
      autoSave(messagesRef.current, convTitle)
    }
    setStreaming(null)
    setChatStatus(null)
    setConvId(null)
    setMessages([])
    setConvTitle("")
    setInput("")
    setStoppedMessageIds(new Set())
    setUnreadCount(0)
    lastSeenIndex.current = 0
  }

  const copyMessage = async (text: string, label = "已复制") => {
    if (!text) return
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        toast({ type: "success", message: label })
        return
      }
    } catch {
      // fall through to legacy fallback
    }
    if (typeof document === "undefined") return
    const ta = document.createElement("textarea")
    ta.value = text
    ta.style.position = "fixed"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand("copy")
      toast({ type: "success", message: label })
    } catch {
      toast({ type: "error", message: "复制失败，请手动复制" })
    } finally {
      document.body.removeChild(ta)
    }
  }

  const exportConv = () => {
    if (!convId) {
      toast({ type: "error", message: "当前没有可导出的对话" })
      return
    }
    const md = messages
      .map((m) => {
        const role = m.role === "user" ? "User" : "Assistant"
        const cite = m.cited && m.cited.length
          ? "\n\nSources:\n" + m.cited.map((c, i) => `  [${i + 1}] ${c.title} — ${c.path}`).join("\n")
          : ""
        return `## ${role}\n\n${m.content}${cite}`
      })
      .join("\n\n---\n\n")
    const header = `# ${convTitle || "Conversation"}\n\nExported: ${new Date().toLocaleString()}\n\n---\n\n`
    const blob = new Blob([header + md], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${(convTitle || "conversation").replace(/[\\\\/:*?"<>|]+/g, "_").slice(0, 64)}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast({ type: "success", message: "对话已导出为 Markdown" })
  }

  const regenerate = useCallback((target: Message) => {
    if (streaming) return
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    if (!lastUser) return
    // Remove the errored assistant message but keep the last user message.
    // Flag handleSend to skip appending a duplicate user bubble.
    setMessages((prev) => prev.filter((m) => m.id !== target.id))
    regenerateNextRef.current = true
    setInput(lastUser.content)
    setTimeout(() => handleSendRef.current?.(), 0)
  }, [messages, streaming])

  const handleRenameConv = async (id: string, currentTitle: string) => {
    const next = typeof window === "undefined"
      ? currentTitle
      : (window.prompt("重命名对话", currentTitle) || "").trim()
    if (!next || next === currentTitle) return
    try {
      const conv = await api.getConversation(id)
      await api.saveConversation({ id, title: next, messages: conv.messages || [] })
      const list = await api.listConversations()
      setConversations(list)
      if (convId === id) setConvTitle(next)
      toast({ type: "success", message: "对话已重命名" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "重命名失败" })
    }
  }

  const handleDeleteConv = async (id: string) => {
    const confirmed = typeof window === "undefined"
      || window.confirm("删除该对话？该操作无法撤销。")
    if (!confirmed) return
    try {
      await api.deleteConversation(id)
      if (convId === id) {
        setConvId(null)
        setMessages([])
        setConvTitle("")
      }
      await api.listConversations().then(setConversations).catch(() => {})
      toast({ type: "success", message: "对话已删除" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "删除对话失败" })
    }
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
        <div className="p-2 border-b flex gap-1.5">
          <button
            onClick={handleNewConv}
            aria-label="新建对话"
            title="新建对话"
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-lg border border-dashed border-[var(--border)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors"
          >
            <Plus size={12} /> New Chat
          </button>
          <button
            onClick={exportConv}
            disabled={!convId}
            aria-label="导出当前对话为 Markdown"
            title="导出当前对话为 Markdown"
            className="shrink-0 flex items-center justify-center px-2 py-1.5 text-xs rounded-lg border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--primary)] disabled:opacity-40"
          >
            <Download size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConversations ? (
            <div className="flex items-center justify-center gap-1 px-3 py-6 text-xs text-[var(--muted-foreground)]">
              <Loader2 size={12} className="animate-spin" /> 加载对话…
            </div>
          ) : null}
          {!loadingConversations && conversations.length === 0 ? (
            <p className="px-3 py-6 text-xs text-[var(--muted-foreground)] text-center">
              No saved conversations
            </p>
          ) : null}
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
                onClick={(e) => { e.stopPropagation(); handleRenameConv(c.id, c.title) }}
                className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition-opacity"
                title="重命名"
              >
                <Pencil size={11} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteConv(c.id) }}
                className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 text-red-500 transition-opacity"
                title="删除"
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
          <span className="ml-auto flex items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
            {llmModel ? (
              <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5" title={`当前 LLM 模型: ${llmModel}`}>
                <Bot size={10} /> {llmModel}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5" title="当前学习者 ID">
              <User size={10} /> {userId}
            </span>
          </span>
        </div>

        {/* Messages */}
        <div ref={scrollHostRef} className="relative flex-1 overflow-y-auto p-4 space-y-4">
          {isEmpty && (
            <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
              <div className="text-center">
                <BookOpen className="h-10 w-10 mx-auto mb-3 opacity-20" />
                <p className="text-lg mb-2">Knowledge Wiki Assistant</p>
                <p>Ask with citations from your selected scope.</p>
                <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
                  当前学习者：<span className="font-medium text-[var(--foreground)]">{userId}</span>
                </p>
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  知识库为空？到 <button
                    type="button"
                    onClick={() => useAppStore.getState().setActiveView("sources")}
                    className="font-medium text-[var(--primary)] underline-offset-2 hover:underline"
                  >导入资料</button> 上传文档后这里会有答案。
                </p>
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
                    {stoppedMessageIds.has(msg.id) ? (
                      <span
                        className="mb-1 inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700"
                        title={(stoppedAt.get(msg.id) ? `你在模型回答完整前手动停止了生成 (${new Date(stoppedAt.get(msg.id) as number).toLocaleTimeString()})` : "你在模型回答完整前手动停止了生成")}
                      >
                        (已停止)
                      </span>
                    ) : null}
                    <Markdown>{msg.content || "..."}</Markdown>
                    {(msg.content?.startsWith("Error:") || stoppedMessageIds.has(msg.id)) ? (
                      <button
                        type="button"
                        onClick={() => regenerate(msg)}
                        className="ml-2 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        title="重新生成"
                      >
                        <RefreshCw size={10} /> {msg.content?.startsWith("Error:") ? "重试" : "继续"}
                      </button>
                    ) : null}
                    {msg.content && !msg.content.startsWith("Error:") ? (
                      <button
                        type="button"
                        onClick={() => copyMessage(msg.content)}
                        className="ml-2 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        title="复制回答"
                      >
                        <Copy size={10} /> 复制
                      </button>
                    ) : null}
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
                      {msg.cited.map((c, i) => (
                        <div
                          key={c.path}
                          className="group flex items-start gap-1 rounded border border-transparent px-1 py-1 hover:border-[var(--border)] hover:bg-[var(--accent)]"
                        >
                          <button
                            type="button"
                            onClick={() => openPage(c.path)}
                            className="flex-1 text-left text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                            title={`打开 ${c.path}`}
                          >
                            <span className="font-medium">[{i + 1}] {c.title}</span>
                            <span className="block truncate opacity-80">— {c.snippet.slice(0, 100)}…</span>
                            <span className="block truncate opacity-60">{c.path}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => copyMessage(c.path, "已复制路径")}
                            className="shrink-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 hover:bg-[var(--background)] hover:text-[var(--foreground)] group-hover:opacity-100"
                            title="复制引用路径"
                          >
                            <LinkIcon size={11} />
                          </button>
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
        {!stickToBottom ? (
          <button
            type="button"
            onClick={() => {
              bottomRef.current?.scrollIntoView({ behavior: "smooth" })
              setStickToBottom(true)
              setUnreadCount(0)
            }}
            className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full border bg-[var(--background)] px-3 py-1 text-[11px] text-[var(--muted-foreground)] shadow hover:text-[var(--foreground)]"
            title="跳到最新消息"
          >
            {unreadCount > 0 ? `${unreadCount} 条新消息 ↓` : "跳到最新 ↓"}
          </button>
        ) : null}

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
            <div className="relative flex-1">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                maxLength={4000}
                onKeyDown={handleKeyDown}
                placeholder={convId ? "Ask a follow-up..." : "Ask a question about your knowledge base..."}
                className="w-full resize-none rounded-lg border px-3 py-2 pr-7 text-sm bg-[var(--background)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                rows={2}
              />
              {input.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setInput("")}
                  aria-label="清空输入"
                  title="清空输入"
                  className="absolute right-1.5 top-1.5 rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                >
                  <X size={12} />
                </button>
              ) : null}
            </div>
            {input.length > 1500 ? (
              <p className="mt-1 text-right text-[10px] text-amber-600">
                内容较长 ({input.length}/4000)，建议拆分后再发
              </p>
            ) : null}
            {streaming ? (
              <button
                onClick={handleStop}
                aria-label="停止生成"
                className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors"
                title="停止生成"
              >
                <Square size={14} />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                aria-label="发送消息"
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
