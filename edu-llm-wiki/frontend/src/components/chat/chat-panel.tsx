import { useState, useRef, useEffect } from "react"
import { api } from "@/lib/api"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import { Send, Loader2 } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
  cited?: { path: string; title: string; snippet: string }[]
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = { role: "user", content: input }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setLoading(true)

    try {
      const allMessages = [...messages, userMsg].map((m) => ({
        role: m.role,
        content: m.content,
      }))
      const resp = await api.chat(allMessages)
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: resp.content,
          cited: resp.cited_pages,
        },
      ])
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${e}` },
      ])
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
            <div className="text-center">
              <p className="text-lg mb-2">Edu-LLM-Wiki</p>
              <p>Ask a question about your knowledge base to get started.</p>
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
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
                <div className="markdown-body text-sm">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm, remarkMath]}
                    rehypePlugins={[rehypeKatex]}
                  >
                    {msg.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}

              {/* Cited pages */}
              {msg.cited && msg.cited.length > 0 && (
                <div className="mt-2 pt-2 border-t border-[var(--border)]">
                  <p className="text-[10px] font-medium text-[var(--muted-foreground)] mb-1">
                    Sources:
                  </p>
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
        {loading && (
          <div className="flex justify-start">
            <div className="bg-[var(--muted)] rounded-xl px-4 py-2.5">
              <Loader2 size={16} className="animate-spin" />
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
            placeholder="Ask a question about your knowledge base..."
            className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm bg-[var(--background)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            rows={2}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-[var(--primary)] text-white disabled:opacity-50 transition-opacity"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
