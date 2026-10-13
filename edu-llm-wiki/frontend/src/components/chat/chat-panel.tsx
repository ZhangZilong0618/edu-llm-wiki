import { useState, useRef, useEffect, useCallback, useMemo } from "react"
import { api, type PracticeEvaluation, type PracticeQuestion } from "@/lib/api"
import { useAppStore } from "@/stores/app-store"
import { InlineMarkdown, Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { useUserStore } from "@/stores/user-store"
import { Send, Loader2, Plus, Trash2, MessageSquare, Square, BookOpen, ImagePlus, User, RefreshCw, Pencil, Copy, Download, Link as LinkIcon, X, Bot, Brain, Lightbulb, CheckCircle2, CircleAlert } from "lucide-react"

interface CitedSource {
  path: string
  title: string
  snippet: string
  // Optional slugified heading; the chat UI scrolls the wiki page here
  // when the citation is opened.
  anchor?: string | null
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  cited?: CitedSource[]
  practice?: PracticeQuestion
  practiceMode?: "practice" | "review"
  evaluation?: PracticeEvaluation
  practiceAttempt?: { answer: string; id: string }
  practiceDismissed?: boolean
  practiceSkipped?: boolean
  assessmentContextQuestionId?: string
}

type ScopeType = "whole_wiki" | "current_page" | "selected_source"

function displayOption(option: string): string {
  // Generated questions often include their own A./B. marker. The card adds
  // the marker for a stable layout, so remove the duplicate from the text.
  return option.replace(/^\s*[A-Za-z][.)、:：]\s*/, "").trim()
}

function isAssessmentFollowup(text: string): boolean {
  const value = text.trim().toLowerCase()
  if (!value) return false
  const compact = value.replace(/[\s\p{P}\p{S}]+/gu, "")

  // Explicit references stay attached even when the learner asks a longer,
  // specific question. Generic requests such as "explain" are accepted only
  // as short follow-ups, so a new topic like "Why is SM-2 useful?" does not
  // inherit the previous question by accident.
  const explicitReferences = [
    "这题", "本题", "这道题", "这个题", "刚才的题", "刚才那题", "上一题",
    "我的答案", "我选的", "这个答案", "参考答案", "为什么选", "为什么对",
    "为什么错", "哪里错", "哪儿错", "批改", "为什么b正确", "b为什么正确",
    "b是正确", "this question", "that question", "my answer", "this option",
  ]
  if (explicitReferences.some((term) => compact.includes(term.replace(/[\s\p{P}\p{S}]+/gu, "")))) return true

  const shortFollowups = new Set([
    "详细解释", "详细解释一下", "解释一下", "展开解释", "展开解释一下", "展开说", "展开讲", "讲详细", "再讲讲",
    "为什么", "为何", "然后呢", "还有呢", "那为什么", "那为什么呢", "为什么呢", "能解释吗",
    "explain", "why", "elaborate", "more detail", "and then",
  ])
  if (shortFollowups.has(value.replace(/[？?。！!，,\s]+$/g, ""))) return true
  return value.length <= 24 && /^(可以|请|能不能|能否|那|所以)?(再|详细|展开|具体)?(解释|讲|说明)(一下|下|清楚|详细)?(吗|呢)?[？?。！!]*$/.test(value)
}

function assessmentFollowupQuestionId(messages: Message[], text: string): string | undefined {
  if (!isAssessmentFollowup(text)) return undefined

  // A marked assistant explanation establishes a multi-turn follow-up chain.
  // Require every intervening learner turn to remain a question follow-up;
  // any unrelated question breaks the chain.
  const lastContextReplyIndex = messages.reduce((last, message, index) =>
    message.role === "assistant" && message.assessmentContextQuestionId ? index : last, -1)
  if (lastContextReplyIndex >= 0) {
    const contextQuestionId = messages[lastContextReplyIndex].assessmentContextQuestionId
    const laterUserTurns = messages.slice(lastContextReplyIndex + 1).filter((message) => message.role === "user")
    if (laterUserTurns.every((message) => isAssessmentFollowup(message.content))) return contextQuestionId
    return undefined
  }

  // For the first follow-up, the most recent practice card must be completed.
  // The first learner turn after the card is their submitted answer; later
  // turns must all refer back to the same assessment.
  let cardIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "assistant" && messages[index].practice) {
      cardIndex = index
      break
    }
  }
  if (cardIndex < 0) return undefined
  const card = messages[cardIndex]
  if (!card.evaluation) return undefined
  const questionId = card.practice?.question_id || card.practice?.id
  if (!questionId) return undefined

  const laterUserTurns = messages.slice(cardIndex + 1).filter((message) => message.role === "user")
  if (laterUserTurns.length === 0) return undefined
  if (laterUserTurns.slice(1).some((message) => !isAssessmentFollowup(message.content))) return undefined
  return questionId
}

function isCurrentPendingPractice(messages: Message[], question: PracticeQuestion | null): boolean {
  if (!question) return false
  const pending = [...messages].reverse().find((message) =>
    message.practice && !message.evaluation && !message.practiceDismissed && !message.practiceSkipped)
  if (!pending?.practice) return false
  const pendingId = pending.practice.question_id || pending.practice.id
  const activeId = question.question_id || question.id
  return Boolean(pendingId && activeId && pendingId === activeId)
}

let idCounter = Date.now()
function nextId() { return `${++idCounter}-${Math.random().toString(36).slice(2, 8)}` }

export function ChatPanel() {
  const conversations = useAppStore((s) => s.conversations)
  const setConversations = useAppStore((s) => s.setConversations)
  const convId = useAppStore((s) => s.currentConversationId)
  const setConvId = useAppStore((s) => s.setCurrentConversationId)
  const selectedPage = useAppStore((s) => s.selectedPage)
  const wikiPageCount = useAppStore((s) => s.wikiPages.length)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const setActiveView = useAppStore((s) => s.setActiveView)
  const pendingChatPrompt = useAppStore((s) => s.pendingChatPrompt)
  const setPendingChatPrompt = useAppStore((s) => s.setPendingChatPrompt)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const importSelectedSource = useAppStore((s) => s.importSelectedSource)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState<string | null>(null)
  const [stoppedMessageIds, setStoppedMessageIds] = useState<Set<string>>(() => new Set())
  const [stoppedAt, setStoppedAt] = useState<Map<string, number>>(() => new Map())
  const [convTitle, setConvTitle] = useState("")
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [scopeType, setScopeType] = useState<ScopeType>("whole_wiki")
  const [chatStatus, setChatStatus] = useState<string | null>(null)
  const [recognizingImage, setRecognizingImage] = useState(false)
  const [practiceQuestion, setPracticeQuestion] = useState<PracticeQuestion | null>(null)
  const [practiceSessionId, setPracticeSessionId] = useState<string | null>(null)
  const [practiceHintLevel, setPracticeHintLevel] = useState(0)
  const [practiceConfidence, setPracticeConfidence] = useState<number | null>(null)
  const [gradingPractice, setGradingPractice] = useState(false)
  const practiceAttemptRef = useRef<{ answer: string; id: string } | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const autoResizeTextarea = useCallback(() => {
    const ta = textareaRef.current
    if (!ta) return
    // Reset to zero before measuring. Using `auto` can retain the previous
    // max height after a viewport resize, leaving an empty composer almost
    // 200px tall on narrow screens.
    ta.style.height = "0px"
    const maxHeight = 8 * 24 // ~8 lines at 1.5 line-height
    ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`
    ta.style.overflowY = ta.scrollHeight > maxHeight ? "auto" : "hidden"
  }, [])
  const imageInputRef = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const skipLoadRef = useRef(false)
  const conversationLoadIdRef = useRef(0)
  const convIdRef = useRef(convId)
  const convTitleRef = useRef(convTitle)

  // Set to true once a conversation's row has been refreshed into the
  // sidebar at least once. When the *first* message of a brand-new
  // conversation is sent, wasRefreshedRef is false, so the autoSave
  // refreshes the list immediately. Subsequent saves skip the refresh
  // (the per-title-refresh guard in autoSave still applies) to avoid
  // flicker and round-trips.
  const wasRefreshedRef = useRef(false)

  // Keep the "latest" refs in sync after commit (don't mutate refs in render).
  useEffect(() => {
    convIdRef.current = convId
    convTitleRef.current = convTitle
  }, [convId, convTitle])

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

  // A page/material can disappear while the chat stays mounted (switching
  // projects, closing a source preview, or using the mobile layout). Keep the
  // selector and the request scope in sync instead of leaving a disabled,
  // blank option selected while silently falling back to the whole wiki.
  useEffect(() => {
    if (scopeType === "current_page" && !selectedPage) {
      setScopeType("whole_wiki")
    } else if (scopeType === "selected_source" && !selectedSourceName) {
      setScopeType("whole_wiki")
    }
  }, [scopeType, selectedPage, selectedSourceName])

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
    const loadId = ++conversationLoadIdRef.current
    // A convId change triggered by handleSend creating a new conversation
    // must NOT abort the stream that handleSend just started — the
    // skipLoadRef flag marks exactly that case, so bail out before touching
    // the in-flight request.
    if (skipLoadRef.current) {
      skipLoadRef.current = false
      return
    }
    // Switching conversations should cancel any in-flight stream so the
    // new conversation starts cleanly instead of inheriting stale streaming
    // UI from the previous one.
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    regenerateNextRef.current = false
    setStreaming(null)
    setChatStatus(null)
    setPracticeQuestion(null)
    setPracticeSessionId(null)
    setPracticeHintLevel(0)
    setPracticeConfidence(null)
    practiceAttemptRef.current = null

    if (!convId) {
      setMessages([])
      setConvTitle("")
      setInput("")
      setLoadingConversation(false)
      return
    }
    setLoadingConversation(true)
    setMessages([])
    setConvTitle("")
    setInput("")
    api.getConversation(convId).then((c) => {
      if (loadId !== conversationLoadIdRef.current) return
      const loadedMessages = (c.messages || []) as Message[]
      setMessages(loadedMessages)
      const pendingPractice = [...loadedMessages].reverse().find((message) => message.practice && !message.evaluation && !message.practiceDismissed && !message.practiceSkipped)
      if (pendingPractice?.practice) {
        setPracticeQuestion(pendingPractice.practice)
        setPracticeSessionId(pendingPractice.practice.session_id || null)
        setPracticeHintLevel(0)
        setPracticeConfidence(null)
        practiceAttemptRef.current = pendingPractice.practiceAttempt || null
        setInput(pendingPractice.practiceAttempt?.answer || "")
      } else {
        setInput("")
        setPracticeQuestion(null)
        setPracticeSessionId(null)
        setPracticeHintLevel(0)
        setPracticeConfidence(null)
        practiceAttemptRef.current = null
      }
      setConvTitle(c.title || "")
      wasRefreshedRef.current = true // already in the list (or will be on first save)
      setStoppedMessageIds(new Set())
      setUnreadCount(0)
      lastSeenIndex.current = (c.messages || []).length
    }).catch(() => {}).finally(() => {
      if (loadId === conversationLoadIdRef.current) setLoadingConversation(false)
    })
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

  // Cleanup on unmount. We deliberately *flush* any pending debounced
  // save before cancelling the timer — otherwise navigating away right
  // after a send silently drops the latest message.
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort()
      if (saveTimer.current) {
        clearTimeout(saveTimer.current)
        saveTimer.current = null
        // Fire the save immediately using whatever messages we currently
        // have. Skip if there is no conversation to save into.
        const id = convIdRef.current
        if (id) {
          api.saveConversation({
            id,
            title: convTitleRef.current,
            messages: messagesRef.current.map((m) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              cited: m.cited,
              practice: m.practice,
              practiceMode: m.practiceMode,
              evaluation: m.evaluation,
              practiceAttempt: m.practiceAttempt,
      practiceDismissed: m.practiceDismissed,
      practiceSkipped: m.practiceSkipped,
      assessmentContextQuestionId: m.assessmentContextQuestionId,
            })),
          }).catch(() => {})
        }
      }
    }
  }, [])

  // Re-measure the textarea height whenever the conversation switches or
  // the input length changes meaningfully.
  useEffect(() => {
    autoResizeTextarea()
  }, [autoResizeTextarea, input.length])

  // The available width changes when the app collapses its side panels on a
  // small viewport. Re-measure after that layout change so a placeholder that
  // briefly wrapped into many lines does not leave the composer oversized.
  useEffect(() => {
    const ta = textareaRef.current
    const parent = ta?.parentElement
    if (!parent || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(() => autoResizeTextarea())
    observer.observe(parent)
    return () => observer.disconnect()
  }, [autoResizeTextarea])

  // Auto-save with debounce. We deliberately do NOT refetch the entire
  // conversation list on every content save -- only when the title
  // changes (rename or first user message) so the sidebar doesn’t flicker
  // and we don’t waste a round-trip per keystroke.
  const autoSave = useCallback((msgs: Message[], title?: string) => {
    const id = convIdRef.current
    if (!id) return
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      const nextTitle = title ?? convTitle
      api.saveConversation({
        id,
        title: nextTitle,
        messages: msgs.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          cited: m.cited,
          practice: m.practice,
          practiceMode: m.practiceMode,
          evaluation: m.evaluation,
          practiceAttempt: m.practiceAttempt,
          practiceDismissed: m.practiceDismissed,
          practiceSkipped: m.practiceSkipped,
          assessmentContextQuestionId: m.assessmentContextQuestionId,
        })),
      }).then(() => {
        const wasFirstSave = !wasRefreshedRef.current
        if (nextTitle !== convTitleRef.current) {
          convTitleRef.current = nextTitle
          wasRefreshedRef.current = true
          api.listConversations().then(setConversations).catch(() => {})
        } else if (wasFirstSave) {
          wasRefreshedRef.current = true
          api.listConversations().then(setConversations).catch(() => {})
        }
      }).catch(() => {})
    }, 500)
  }, [convTitle, setConversations])

  const submitPracticeAnswer = useCallback(async () => {
    if (!practiceQuestion || streaming || gradingPractice || !input.trim()) return
    if (practiceConfidence == null) {
      toast({ type: "error", message: "请先选择信心程度（1–5）再提交答案" })
      return
    }
    const questionId = practiceQuestion.id || practiceQuestion.question_id
    if (!questionId) return
    const answer = input.trim()
    const attemptId = practiceAttemptRef.current?.answer === answer
      ? practiceAttemptRef.current.id
      : crypto.randomUUID()
    practiceAttemptRef.current = { answer, id: attemptId }
    setGradingPractice(true)
    const attemptMessages = messagesRef.current.map((message) =>
      message.practice?.id === questionId || message.practice?.question_id === questionId
        ? { ...message, practiceAttempt: { answer, id: attemptId } }
        : message,
    )
    // Keep the imperative snapshot in lockstep with the optimistic React
    // update. A very fast local grading response can resolve before the
    // effect that mirrors `messages` runs; without this assignment the
    // evaluation append could otherwise be based on the pre-attempt array.
    messagesRef.current = attemptMessages
    setMessages(attemptMessages)
    autoSave(attemptMessages, convTitle)
    const userMsg: Message = { id: nextId(), role: "user", content: answer }
    setInput("")
    setChatStatus("正在批改答案…")
    try {
      const sessionId = practiceSessionId || practiceQuestion.session_id
      if (!sessionId) throw new Error("练习会话已过期，请重新出题。")
      const evaluation = await api.submitPracticeAnswer(sessionId, {
        question_id: questionId,
        answer,
        confidence: practiceConfidence,
        hint_ladder: practiceHintLevel,
        attempt_id: attemptId,
      }, userId)
      practiceAttemptRef.current = null
      const nextMessages = [...messagesRef.current, userMsg].map((message) =>
        message.practice?.id === questionId || message.practice?.question_id === questionId
          ? { ...message, evaluation, practiceAttempt: undefined }
          : message,
      )
      messagesRef.current = nextMessages
      setMessages(nextMessages)
      setPracticeQuestion(null)
      setPracticeSessionId(null)
      setPracticeHintLevel(0)
      setPracticeConfidence(null)
      autoSave(nextMessages, convTitle)
    } catch (e: any) {
      setInput(answer)
      toast({ type: "error", message: e?.message || "答案批改失败" })
    } finally {
      setGradingPractice(false)
      setChatStatus(null)
    }
  }, [autoSave, convTitle, gradingPractice, input, practiceConfidence, practiceHintLevel, practiceQuestion, practiceSessionId, streaming, userId])

  const requestAnotherPractice = useCallback((messageId: string) => {
    if (streaming || gradingPractice) return
    // Keep the completed/current card visible in the conversation. Starting
    // another question only moves the active answer target to the new card;
    // it must not mark the previous card dismissed and make its prompt and
    // explanation disappear from the transcript.
    const currentMessages = messagesRef.current
    if (!currentMessages.some((message) => message.id === messageId && message.practice)) return
    setMessages(currentMessages)
    setPracticeQuestion(null)
    setPracticeSessionId(null)
    setPracticeHintLevel(0)
    setPracticeConfidence(null)
    practiceAttemptRef.current = null
    setInput("再来一道题")
    autoSave(currentMessages, convTitle)
    textareaRef.current?.focus()
    setTimeout(() => handleSendRef.current?.(), 0)
  }, [autoSave, convTitle, gradingPractice, streaming])

  const pausePracticeForChat = useCallback((messageId: string) => {
    if (streaming || gradingPractice) return
    const currentMessages = messagesRef.current.map((message) =>
      message.id === messageId ? { ...message, practiceSkipped: true } : message,
    )
    setMessages(currentMessages)
    setPracticeQuestion(null)
    setPracticeSessionId(null)
    setPracticeHintLevel(0)
    setPracticeConfidence(null)
    practiceAttemptRef.current = null
    setInput("")
    autoSave(currentMessages, convTitle)
  }, [autoSave, convTitle, gradingPractice, streaming])

  const resumePractice = useCallback((message: Message) => {
    if (streaming || gradingPractice || !message.practice || message.evaluation) return
    const currentMessages = messagesRef.current.map((item) =>
      item.id === message.id ? { ...item, practiceSkipped: false } : item,
    )
    setMessages(currentMessages)
    setPracticeQuestion(message.practice)
    setPracticeSessionId(message.practice.session_id || null)
    setPracticeHintLevel(0)
    setPracticeConfidence(null)
    practiceAttemptRef.current = message.practiceAttempt || null
    setInput(message.practiceAttempt?.answer || "")
    autoSave(currentMessages, convTitle)
    textareaRef.current?.focus()
  }, [autoSave, convTitle, gradingPractice, streaming])

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    userStoppedRef.current = true
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
  // Set to true when the user explicitly clicks Stop. Lets the catch block
  // tell apart a deliberate abort (no toast) from a connection drop or other
  // network failure (toast so the user knows the partial response isn't
  // the final one).
  const userStoppedRef = useRef(false)
  useEffect(() => { messagesRef.current = messages }, [messages])
  // When true, the next handleSend call will stream a new assistant response
  // without re-appending the last user message (used by "regenerate").
  const regenerateNextRef = useRef(false)
  const handleSend = useCallback(async () => {
    if (!input.trim() || streaming || gradingPractice || loadingConversation) return

    // A normal chat send must never be interpreted as an answer just because
    // an unfinished card exists. Pause that card, keep it in the transcript,
    // and let the learner resume it explicitly when they want to continue.
    let baseMsgs = messages
    if (isCurrentPendingPractice(messages, practiceQuestion)) {
      const activeId = practiceQuestion?.question_id || practiceQuestion?.id
      const activeMessage = [...messages].reverse().find((message) => {
        const questionId = message.practice?.question_id || message.practice?.id
        return Boolean(message.practice && questionId && questionId === activeId && !message.evaluation)
      })
      if (activeMessage) {
        baseMsgs = messages.map((message) =>
          message.id === activeMessage.id ? { ...message, practiceSkipped: true } : message,
        )
        messagesRef.current = baseMsgs
        setMessages(baseMsgs)
        autoSave(baseMsgs, convTitle)
      }
      setPracticeQuestion(null)
      setPracticeSessionId(null)
      setPracticeHintLevel(0)
      setPracticeConfidence(null)
      practiceAttemptRef.current = null
    }

    let currentConvId = convId
    if (!currentConvId) {
      currentConvId = nextId()
      skipLoadRef.current = true
      setConvId(currentConvId)
    }

    const assistantId = nextId()
    if (regenerateNextRef.current) {
      // The user message we are regenerating from is already the last item
      // in `messages` (the errored / stopped assistant was filtered out
      // before handleSend was invoked). Keep it in the chat history so the
      // LLM still sees the question; just don't append a duplicate UI bubble.
      regenerateNextRef.current = false
    } else {
      const userMsg: Message = { id: nextId(), role: "user", content: input }
      baseMsgs = [...baseMsgs, userMsg]
    }
    const assessmentContextQuestionId = assessmentFollowupQuestionId(messages, input)
    const newMsgs = [...baseMsgs, {
      id: assistantId,
      role: "assistant" as const,
      content: "",
      assessmentContextQuestionId,
    }]
    setMessages(newMsgs)
    setInput("")
    setStreaming(assistantId)
    setChatStatus("Understanding the question...")
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
        mode: "auto",
        scope: effectiveScope,
        user_id: userId,
        conversation_id: currentConvId ?? "default",
        options: {
          citation_required: true,
          answer_style: "concise",
          agent_mode: "auto",
          assessment_context_question_id: assessmentContextQuestionId,
        },
      })) {
        if (event.type === "status") {
          setChatStatus(event.text)
        } else if (event.type === "practice_question") {
          const raw = (event.question || event.payload || event) as Partial<PracticeQuestion> & { session_id?: string }
          if (raw.prompt) {
            const question = { ...raw, id: raw.id || raw.question_id || nextId() } as PracticeQuestion
            setPracticeQuestion(question)
            practiceAttemptRef.current = null
            setPracticeSessionId((event.session_id || raw.session_id || null) as string | null)
            setPracticeHintLevel(0)
            setPracticeConfidence(null)
            setMessages((prev) => prev.map((message) => message.id === assistantId
              ? { ...message, content: "", practice: question, practiceMode: event.mode === "review" ? "review" : "practice" }
              : message,
            ))
          }
        } else if (event.type === "queue_empty") {
          setPracticeQuestion(null)
          setPracticeSessionId(null)
          setPracticeHintLevel(0)
          setPracticeConfidence(null)
          setChatStatus(null)
        } else if (event.type === "cited" || event.type === "sources" || event.type === "final_citations") {
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, cited: event.pages } : m))
        } else if (event.type === "content") {
          lastContent += event.text
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: lastContent } : m))
        } else if (event.type === "replace") {
          lastContent = event.text
          setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: lastContent } : m))
        } else if (event.type === "error") {
          // Pipeline or LLM stream failed mid-flight; surface a clear error
          // and stop streaming so the UI can recover.
          toast({ type: "error", message: event.message || "请求失败，请稍后重试" })
          let latest: Message[] = messages
          setMessages((prev) => {
            const next = prev.map((m) =>
              m.id === assistantId && !m.content
                ? { ...m, content: `错误：${event.message || "请求失败"}` }
                : m
            )
            latest = next
            return next
          })
          // Persist immediately so the saved conversation includes the
          // error annotation. We capture the new array via `latest` so we
          // don't race the React commit + messagesRef ref update.
          if (convIdRef.current) autoSave(latest, convTitle)
        }
      }

      setMessages((prev) => {
        const lastUser = [...prev].reverse().find((m) => m.role === "user")
        const titleSeed = lastUser?.content?.trim() || convTitle
        autoSave(prev, titleSeed.slice(0, 50))
        return prev
      })
    } catch (e: any) {
      const userStopped = userStoppedRef.current
      userStoppedRef.current = false
      if (e?.name === "AbortError") {
        if (!userStopped) {
          toast({ type: "error", message: "连接中断，回答可能不完整。" })
        }
        setStreaming(null)
        return
      }
      const message = e?.message || "请求失败，请稍后重试"
      toast({ type: "error", message })
      setMessages((prev) => prev.map((m) =>
        m.id === assistantId && !m.content ? { ...m, content: `错误：${message}` } : m
      ))
    }
    setStreaming(null)
    setChatStatus(null)
  }, [input, messages, practiceQuestion, gradingPractice, streaming, loadingConversation, convId, convTitle, autoSave, setConvId, chatScope, userId])
  handleSendRef.current = handleSend

  // Page-level actions enter the same composer used for normal chat. Keep the
  // handoff one-shot so switching conversations cannot replay an old prompt.
  useEffect(() => {
    if (!pendingChatPrompt) return
    if (selectedPage) setScopeType("current_page")
    setInput(pendingChatPrompt)
    setPendingChatPrompt(null)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [pendingChatPrompt, selectedPage, setPendingChatPrompt])

  const openPage = async (raw: string) => {
    if (!raw) return
    // Citation paths can carry a `#section-id` fragment so the page jumps
    // straight to the cited section instead of landing at the top.
    const hashIdx = raw.indexOf("#")
    const path = hashIdx >= 0 ? raw.slice(0, hashIdx) : raw
    const anchor = hashIdx >= 0 ? raw.slice(hashIdx + 1) : null
    if (!path) {
      // Path-less anchor (e.g. "##my-section") is malformed; refuse to
      // call the wiki API with an empty path which would 404.
      toast({ type: "error", message: "Citation path missing; cannot open" })
      return
    }
    try {
      const page = await api.getPage(path)
      setSelectedPage(page)
      setActiveView("wiki")
      // Defer the scroll until the wiki view mounts and renders the
      // heading. Two RAFs covers the fast path; for slow renders (long
      // page, lots of citations) we poll briefly so the user always
      // lands on the cited section rather than the page top.
      if (anchor) {
        const decoded = decodeURIComponent(anchor)
        let attempts = 0
        const tryScroll = () => {
          const el = document.getElementById(decoded)
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" })
            el.classList.add("ring-2", "ring-[var(--primary)]", "ring-offset-2")
            window.setTimeout(() => {
              el.classList.remove("ring-2", "ring-[var(--primary)]", "ring-offset-2")
            }, 1800)
            return
          }
          if (attempts++ < 12) {
            window.setTimeout(tryScroll, 120)
          }
        }
        requestAnimationFrame(tryScroll)
      }
    } catch (e: any) {
      toast({ type: "error", message: e?.message || `Failed to load page: ${path}` })
    }
  }

  const handleNewConv = () => {
    if (gradingPractice) return
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
    setStoppedAt(new Map())
    setUnreadCount(0)
    lastSeenIndex.current = 0
  }

  const copyMessage = async (text: string, label = "Copied") => {
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
      toast({ type: "error", message: "Copy failed; please copy manually" })
    } finally {
      document.body.removeChild(ta)
    }
  }

  const exportConv = () => {
    if (!convId) {
      toast({ type: "error", message: "No conversation available to export" })
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
    toast({ type: "success", message: "Conversation exported as Markdown" })
  }

  const regenerate = useCallback((target: Message) => {
    if (streaming) return
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    if (!lastUser) return
    // Remove the errored assistant message but keep the last user message.
    // Flag handleSend to skip appending a duplicate user bubble.
    setMessages((prev) => prev.filter((m) => m.id !== target.id))
    regenerateNextRef.current = true
    // Clear any residual text the user might have been drafting; the
    // previous user message we are regenerating from is already kept in
    // `messages` (since we only removed the assistant), so we must NOT
    // overwrite the textarea with it.
    setInput("")
    setTimeout(() => handleSendRef.current?.(), 0)
  }, [messages, streaming])

  const handleRenameConv = async (id: string, currentTitle: string) => {
    const next = typeof window === "undefined"
      ? currentTitle
      : (window.prompt("Rename conversation", currentTitle) || "").trim()
    if (!next || next === currentTitle) return
    try {
      const conv = await api.getConversation(id)
      // Cancel any pending content autoSave first — otherwise the stale
      // timer can fire a few hundred ms later and overwrite the new title
      // with the OLD title captured in its closure.
      if (saveTimer.current) {
        clearTimeout(saveTimer.current)
        saveTimer.current = null
      }
      await api.saveConversation({ id, title: next, messages: conv.messages || [] })
      const list = await api.listConversations()
      setConversations(list)
      if (convId === id) setConvTitle(next)
      toast({ type: "success", message: "Conversation renamed" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Rename failed" })
    }
  }

  const handleDeleteConv = async (id: string) => {
    const confirmed = typeof window === "undefined"
      || window.confirm("Delete this conversation? This action cannot be undone.")
    if (!confirmed) return
    try {
      await api.deleteConversation(id)
      if (convId === id) {
        setConvId(null)
        setMessages([])
        setConvTitle("")
      }
      await api.listConversations().then(setConversations).catch(() => {})
      toast({ type: "success", message: "Conversation deleted" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to delete conversation" })
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
    setChatStatus("正在识别图片…")
    try {
      const res = await api.recognizeChatImage(file)
      const extracted = res.text.trim()
      if (!extracted) {
        toast({ type: "error", message: "没有识别到可用文字" })
        return
      }
      const block = `我拍了一张题目图片。请根据识别出的内容作答，并指出需要我确认的地方。\n\n## OCR 结果\n\n${extracted}`
      setInput((prev) => prev.trim() ? `${prev.trim()}\n\n${block}` : block)
      toast({ type: "success", message: "图片识别完成，结果已填入输入框" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Image recognition failed" })
    } finally {
      setRecognizingImage(false)
      setChatStatus(null)
      if (imageInputRef.current) imageInputRef.current.value = ""
    }
  }

  // The "Retry/Continue" + "Stopped" badge only make sense on the latest
  // assistant message, since regenerate() acts on the most recent user
  // turn. Older stopped messages keep their (Stopped) badge for context
  // but no longer expose the regenerate button.
  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].id
    }
    return null
  }, [messages])

  // Only the newest question card can start another question. Keeping this
  // separate from `practiceQuestion` also leaves the action available after
  // the current card has been graded, when that state is intentionally reset.
  const latestPracticeId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].practice) return messages[i].id
    }
    return null
  }, [messages])

  const isEmpty = messages.length === 0 && !convId

  return (
    <div className="flex h-full min-w-0">
      {/* Conversation sidebar */}
      <div className="hidden sm:flex sm:w-44 shrink-0 border-r flex-col bg-[var(--sidebar)]">
        <div className="p-2 border-b flex gap-1.5">
          <button
            onClick={handleNewConv}
            disabled={gradingPractice}
            aria-label="New Conversation"
            title="New Conversation"
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-lg border border-dashed border-[var(--border)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={12} /> <span className="hidden sm:inline">新对话</span>
          </button>
          <button
            onClick={exportConv}
            disabled={!convId}
            aria-label="Export current conversation as Markdown"
            title="Export current conversation as Markdown"
            className="shrink-0 flex items-center justify-center px-2 py-1.5 text-xs rounded-lg border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--primary)] disabled:opacity-40"
          >
            <Download size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConversations ? (
            <div className="flex items-center justify-center gap-1 px-3 py-6 text-xs text-[var(--muted-foreground)]">
              <Loader2 size={12} className="animate-spin" /> 正在加载对话…
            </div>
          ) : null}
          {!loadingConversations && conversations.length === 0 ? (
            <p className="px-3 py-6 text-xs text-[var(--muted-foreground)] text-center">
              暂无已保存的对话
            </p>
          ) : null}
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => { if (!gradingPractice) setConvId(c.id) }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  if (!gradingPractice) setConvId(c.id)
                }
              }}
              role="button"
              tabIndex={0}
              aria-label={`Open conversation ${c.title}`}
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[var(--primary)] ${
                convId === c.id
                  ? "bg-[var(--accent)] text-[var(--foreground)]"
                  : "text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
              }`}
            >
              <MessageSquare size={12} className="shrink-0" />
              <span className="hidden sm:block flex-1 truncate">{c.title}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleRenameConv(c.id, c.title) }}
                className="hidden sm:block shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition-opacity"
                title="Rename"
              >
                <Pencil size={11} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteConv(c.id) }}
                className="hidden sm:block shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 text-red-500 transition-opacity"
                title="Delete"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Scope */}
        <div className="shrink-0 flex min-w-0 flex-wrap items-center gap-2 px-3 py-1.5 border-b bg-[var(--background)]">
          <button
            type="button"
            onClick={handleNewConv}
            disabled={gradingPractice}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50 sm:hidden"
            aria-label="New Conversation"
            title="New Conversation"
          >
            <Plus size={13} />
          </button>
          <select
            value={scopeType}
            onChange={(e) => setScopeType(e.target.value as ScopeType)}
            className="h-7 rounded-md border bg-[var(--background)] px-2 text-xs text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
            title="Knowledge scope"
          >
            <option value="whole_wiki">全部知识库</option>
            <option value="current_page" disabled={!selectedPage}>当前页面</option>
            <option value="selected_source" disabled={!selectedSourceName}>当前材料</option>
          </select>
          <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--muted-foreground)]">
            {scopeType === "current_page" && selectedPage ? selectedPage.title : null}
            {scopeType === "selected_source" && selectedSourceName ? selectedSourceName : null}
            {scopeType === "whole_wiki" ? "使用全部知识页面" : null}
          </span>
          <span className="ml-auto hidden items-center gap-1.5 text-[10px] text-[var(--muted-foreground)] sm:flex">
            {llmModel ? (
              <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5" title={`LLM model: ${llmModel}`}>
                <Bot size={10} /> {llmModel}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5" title="Current learner ID">
              <User size={10} /> {userId}
            </span>
          </span>
        </div>

        {/* Messages */}
        <div ref={scrollHostRef} className="relative flex-1 min-w-0 overflow-y-auto p-4 space-y-4">
          {isEmpty && (
            <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
              <div className="text-center">
                <BookOpen className="h-10 w-10 mx-auto mb-3 opacity-20" />
                <p className="text-lg mb-2">知识库对话助手</p>
                <p>基于当前范围提问，回答会附带引用。</p>
                <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
                  Current learner:<span className="font-medium text-[var(--foreground)]">{userId}</span>
                </p>
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  {wikiPageCount === 0 ? (
                    <>知识库还是空的？前往 <button
                      type="button"
                      onClick={() => useAppStore.getState().setActiveView("sources")}
                      className="font-medium text-[var(--primary)] underline-offset-2 hover:underline"
                    >导入材料</button> 添加文档。</>
                  ) : (
                    <>你可以提问，或使用下面的快捷入口从 {wikiPageCount} 个知识页面开始学习。</>
                  )}
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setInput("请基于当前知识库出一道题测试我。")
                      requestAnimationFrame(() => textareaRef.current?.focus())
                    }}
                    className="rounded-full border border-[var(--primary)]/40 px-3 py-1.5 text-[11px] text-[var(--primary)] hover:bg-[var(--primary)]/10"
                  >
                    出一道题
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setInput("帮我复习今天到期的内容。")
                      requestAnimationFrame(() => textareaRef.current?.focus())
                    }}
                    className="rounded-full border px-3 py-1.5 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                  >
                    复习到期内容
                  </button>
                </div>
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex min-w-0 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`min-w-0 max-w-[85%] break-words rounded-xl px-4 py-2.5 text-sm [overflow-wrap:anywhere] ${
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
                        title={(stoppedAt.get(msg.id) ? `You manually stopped generation before the model finished responding (${new Date(stoppedAt.get(msg.id) as number).toLocaleTimeString()})` : "You manually stopped generation before the model finished responding")}
                      >
                        (Stopped)
                      </span>
                    ) : null}
                    {msg.content ? <Markdown>{msg.content}</Markdown> : msg.practice ? null : <Markdown>...</Markdown>}
                    {msg.practice && !msg.practiceDismissed ? (
                      <div className="mt-3 min-w-0 overflow-hidden rounded-lg border border-[var(--primary)]/30 bg-[var(--background)] p-3 [overflow-wrap:anywhere]">
                        {(() => {
                          const questionId = msg.practice?.id || msg.practice?.question_id
                          const activeQuestionId = practiceQuestion?.id || practiceQuestion?.question_id
                          const isActivePractice = Boolean(questionId && activeQuestionId && questionId === activeQuestionId)
                          const selectedOption = isActivePractice
                            ? input.trim().match(/^([A-H])(?:\.|\s|$)/i)?.[1]?.toUpperCase() || ""
                            : ""
                          return (
                            <>
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-[var(--primary)]">
                            <Brain size={14} className="shrink-0" />
                            <span className="break-words">{msg.practiceMode === "review" ? "复习题" : "练习题"}</span>
                            {msg.practice.difficulty ? <span className="break-words rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px]">{msg.practice.difficulty}</span> : null}
                          </div>
                          <button
                            type="button"
                            onClick={() => requestAnotherPractice(msg.id)}
                            disabled={!!streaming || gradingPractice || latestPracticeId !== msg.id}
                            className="text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
                          >
                            再来一道题
                          </button>
                          {!msg.evaluation && !isActivePractice ? (
                            <button
                              type="button"
                              onClick={() => resumePractice(msg)}
                              disabled={!!streaming || gradingPractice}
                              className="rounded border border-[var(--primary)]/40 px-2 py-1 text-[10px] text-[var(--primary)] hover:bg-[var(--primary)]/10 disabled:opacity-50"
                            >
                              继续答题
                            </button>
                          ) : null}
                          {isActivePractice && !msg.evaluation ? (
                            <button
                              type="button"
                              onClick={() => pausePracticeForChat(msg.id)}
                              disabled={!!streaming || gradingPractice}
                              className="text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
                            >
                              暂停答题
                            </button>
                          ) : null}
                        </div>
                        <div className="min-w-0 break-words text-sm text-[var(--foreground)] [overflow-wrap:anywhere] [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex-display]:my-2 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_p]:my-1 [&_p]:leading-relaxed">
                          <Markdown>{msg.practice.prompt}</Markdown>
                        </div>
                        {msg.practice.options?.length ? (
                          <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                            {msg.practice.options.map((option, index) => (
                              <button
                                key={`${option}-${index}`}
                                type="button"
                                onClick={() => setInput(String.fromCharCode(65 + index))}
                                disabled={!!msg.evaluation || !!streaming || gradingPractice || !isActivePractice}
                                className={`min-w-0 break-words rounded-md border px-2.5 py-2 text-left text-xs hover:border-[var(--primary)] hover:bg-[var(--accent)] disabled:opacity-60 [overflow-wrap:anywhere] ${selectedOption === String.fromCharCode(65 + index) ? "border-[var(--primary)] bg-[var(--accent)]" : ""}`}
                              >
                                <span className="mr-1.5 font-medium">{String.fromCharCode(65 + index)}.</span>{" "}
                                <span className="inline-block min-w-0 max-w-full align-middle overflow-x-auto [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex]:whitespace-nowrap">
                                  <InlineMarkdown>{displayOption(option)}</InlineMarkdown>
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {!msg.evaluation && isActivePractice ? (
                          <>
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              {msg.practice.hints?.length ? (
                                <button
                                  type="button"
                                  onClick={() => setPracticeHintLevel((level) => Math.min(level + 1, msg.practice?.hints?.length || 0))}
                                  disabled={practiceHintLevel >= msg.practice.hints.length || !!streaming || gradingPractice || !isActivePractice}
                                  className="inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
                                >
                                  <Lightbulb size={11} /> 提示 {practiceHintLevel}/{msg.practice.hints.length}
                                </button>
                              ) : null}
                              <span className="text-[10px] text-[var(--muted-foreground)]">答题信心（提交时必选）</span>
                              {[1, 2, 3, 4, 5].map((value) => (
                                <button
                                  key={value}
                                  type="button"
                                  aria-label={`信心 ${value}/5`}
                                  onClick={() => setPracticeConfidence(value)}
                                  disabled={!!streaming || gradingPractice || !isActivePractice}
                                  className={`h-5 w-5 rounded-full border text-[10px] disabled:opacity-60 ${isActivePractice && practiceConfidence === value ? "border-[var(--primary)] bg-[var(--primary)] text-white" : "text-[var(--muted-foreground)] hover:border-[var(--primary)]"}`}
                                >
                                  {value}
                                </button>
                              ))}
                              {isActivePractice && practiceConfidence == null ? (
                                <span className="w-full text-[10px] text-amber-700">仅提交这道题时需要选择 1–5</span>
                              ) : null}
                            </div>
                            {isActivePractice && practiceHintLevel > 0 && msg.practice.hints ? (
                              <div className="mt-2 min-w-0 break-words rounded bg-[var(--accent)] px-2.5 py-2 text-xs text-[var(--muted-foreground)] [overflow-wrap:anywhere] [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex-display]:my-1 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_p]:my-1 [&_p]:leading-relaxed">
                                <Lightbulb size={11} className="mr-1 inline" />
                                <Markdown>{msg.practice.hints.slice(0, practiceHintLevel).join(" ")}</Markdown>
                              </div>
                            ) : null}
                            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                              <span className="text-[10px] text-[var(--muted-foreground)]">普通消息仍由下方发送按钮发送</span>
                              <button
                                type="button"
                                onClick={submitPracticeAnswer}
                                disabled={!input.trim() || !!streaming || gradingPractice}
                                className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                提交答案
                              </button>
                            </div>
                          </>
                        ) : msg.evaluation ? (
                          <div className="mt-3 rounded-md border bg-[var(--muted)] px-3 py-2 text-xs">
                            <div className="flex flex-wrap items-center gap-1 font-medium">
                              {msg.evaluation.correct ? <CheckCircle2 size={13} className="text-emerald-600" /> : <CircleAlert size={13} className="text-amber-600" />}
                              {msg.evaluation.correct ? "答对了" : "继续巩固"}
                              {typeof msg.evaluation.score === "number" ? ` · ${Math.round(msg.evaluation.score * 100)}%` : null}
                            </div>
                            {msg.evaluation.feedback ? (
                              <div className="mt-1 min-w-0 break-words text-[var(--muted-foreground)] [overflow-wrap:anywhere] [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex-display]:my-1 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_p]:my-1 [&_p]:leading-relaxed">
                                <Markdown>{msg.evaluation.feedback}</Markdown>
                              </div>
                            ) : null}
                            {msg.evaluation.correct_answer != null && String(Array.isArray(msg.evaluation.correct_answer) ? msg.evaluation.correct_answer.join(" / ") : msg.evaluation.correct_answer).trim() ? (
                              <div className="mt-2 min-w-0 break-words [overflow-wrap:anywhere] [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex-display]:my-1 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_p]:my-1 [&_p]:leading-relaxed">
                                <span className="font-medium">参考答案：</span>
                                <Markdown>{Array.isArray(msg.evaluation.correct_answer) ? msg.evaluation.correct_answer.join(" / ") : String(msg.evaluation.correct_answer)}</Markdown>
                              </div>
                            ) : null}
                            {msg.evaluation.explanation ? (
                              <div className="mt-1 min-w-0 break-words text-[var(--muted-foreground)] [overflow-wrap:anywhere] [&_.katex]:inline-block [&_.katex]:max-w-full [&_.katex]:overflow-x-auto [&_.katex-display]:my-1 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_p]:my-1 [&_p]:leading-relaxed">
                                <span className="font-medium text-[var(--foreground)]">解析：</span>
                                <Markdown>{msg.evaluation.explanation}</Markdown>
                              </div>
                            ) : null}
                            {msg.evaluation.learning_update?.bkt?.p_known != null ? (
                              <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                                掌握度 {Math.round(msg.evaluation.learning_update.bkt.p_known * 100)}% · 已安排下一次复习
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                            </>
                          )
                        })()}
                      </div>
                    ) : null}
                    {!streaming && msg.id === lastAssistantId && (!msg.content?.trim() || msg.content.startsWith("Error:") || msg.content.startsWith("错误：") || stoppedMessageIds.has(msg.id)) ? (
                      <button
                        type="button"
                        onClick={() => regenerate(msg)}
                        className="ml-2 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        title="Regenerate"
                      >
                        <RefreshCw size={10} /> {msg.content?.startsWith("Error:") || msg.content?.startsWith("错误：") ? "重试" : "继续"}
                      </button>
                    ) : null}
                    {msg.content && !msg.content.startsWith("Error:") && !msg.content.startsWith("错误：") ? (
                      <button
                        type="button"
                        onClick={() => copyMessage(msg.content)}
                        className="ml-2 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        title="复制答案"
                      >
                        <Copy size={10} /> 复制
                      </button>
                    ) : null}
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{msg.content}</p>
                )}

                {msg.cited && msg.cited.length > 0 && (
                  <details className="mt-2 w-full min-w-0 max-w-full overflow-hidden border-t border-[var(--border)] pt-2">
                    <summary className="cursor-pointer list-none break-words text-[10px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] [overflow-wrap:anywhere]">
                      来源 ({msg.cited.length})
                    </summary>
                    <div className="mt-1 min-w-0 max-w-full space-y-1">
                      {msg.cited.map((c, i) => (
                        <div
                          key={`${c.path}-${c.anchor || "source"}-${i}`}
                          className="group flex min-w-0 max-w-full items-start gap-1 rounded border border-transparent px-1 py-1 hover:border-[var(--border)] hover:bg-[var(--accent)]"
                        >
                          <button
                            type="button"
                            onClick={() => openPage(c.anchor ? `${c.path}#${c.anchor}` : c.path)}
                            className="min-w-0 flex-1 break-words text-left text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] [overflow-wrap:anywhere]"
                            title={c.anchor ? `打开 ${c.path}（定位到 ${c.anchor}）` : `打开 ${c.path}`}
                          >
                            <span className="block break-words font-medium [overflow-wrap:anywhere]">[{i + 1}] {c.title}</span>
                            {c.anchor ? (
                              <span
                                className="ml-1 rounded bg-[var(--primary)]/10 px-1 py-0.5 text-[9px] font-medium text-[var(--primary)]"
                                title="点击跳转到此小节"
                              >
                                §{c.anchor}
                              </span>
                            ) : null}
                            <span className="block break-words opacity-80 [overflow-wrap:anywhere]">— {c.snippet.slice(0, 100)}…</span>
                            <span className="block break-words opacity-60 [overflow-wrap:anywhere]">{c.path}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => copyMessage(c.path, "Path copied")}
                            className="shrink-0 rounded p-1 text-[var(--muted-foreground)] opacity-60 hover:bg-[var(--background)] hover:text-[var(--foreground)] sm:opacity-0 sm:group-hover:opacity-100"
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
                <span className="text-[11px] text-[var(--muted-foreground)]">{chatStatus || "思考中…"}</span>
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
            title="跳转到最新消息"
          >
            {unreadCount > 0 ? `${unreadCount} 条新消息 ↓` : "跳转到最新 ↓"}
          </button>
        ) : null}

        {/* Input */}
        <div className="shrink-0 border-t p-3">
          <div className="flex min-w-0 items-end gap-2">
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
            <div className="relative min-w-0 flex-1">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value)
                  autoResizeTextarea()
                }}
                disabled={gradingPractice}
                maxLength={4000}
                onKeyDown={handleKeyDown}
                placeholder={convId ? "继续对话或追问…（答题请点题卡里的“提交答案”）" : "询问知识库内容…"}
                className="w-full resize-none rounded-lg border bg-[var(--background)] px-3 py-2 pr-16 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                rows={2}
              />
              {input.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setInput("")}
                  aria-label="Clear Input"
                  title="Clear Input"
                  className="absolute right-1.5 top-1.5 rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                >
                  <X size={12} />
                </button>
              ) : null}
              {input.length > 300 ? (
                <p
                  className={`pointer-events-none absolute bottom-1.5 right-2 text-[10px] ${input.length > 1500 ? "text-amber-600" : "text-[var(--muted-foreground)]"}`}
                >
                  {input.length}/4000{input.length > 1500 ? " · Suggest splitting before sending" : ""}
                </p>
              ) : null}
            </div>
            {streaming ? (
              <button
                onClick={handleStop}
                aria-label="Stop Generating"
                className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors"
                title="Stop Generating"
              >
                <Square size={14} />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() || gradingPractice}
                aria-label="Send Message"
                title="发送消息"
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
