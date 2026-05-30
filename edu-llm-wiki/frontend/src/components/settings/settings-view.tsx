import { useState, useEffect } from "react"
import { api, type LlmSettings, type EmbeddingSettings } from "@/lib/api"
import { Eye, EyeOff, Save, Check, Loader } from "lucide-react"
import { toast } from "@/components/ui/toast"

const PROVIDERS = [
  { value: "openai", label: "OpenAI", baseUrl: "" },
  { value: "anthropic", label: "Anthropic", baseUrl: "" },
  { value: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1" },
  { value: "google", label: "Google Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/" },
  { value: "azure", label: "Azure OpenAI", baseUrl: "" },
  { value: "groq", label: "Groq", baseUrl: "https://api.groq.com/openai/v1" },
  { value: "together", label: "Together AI", baseUrl: "https://api.together.xyz/v1" },
  { value: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1" },
  { value: "ollama", label: "Ollama (Local)", baseUrl: "http://localhost:11434/v1" },
  { value: "custom", label: "Custom (OpenAI-compatible)", baseUrl: "" },
]

const DEFAULT_MODELS: Record<string, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-sonnet-4-6",
  deepseek: "deepseek-chat",
  google: "gemini-2.0-flash",
  azure: "gpt-4o-mini",
  groq: "llama-4-maverick-17b-128e-instruct",
  together: "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
  openrouter: "openai/gpt-4o-mini",
  ollama: "llama3.2",
  custom: "gpt-4o-mini",
}

export function SettingsView() {
  // LLM
  const [llm, setLlm] = useState<LlmSettings>({
    llm_provider: "openai",
    llm_api_key: "",
    llm_model: "gpt-4o-mini",
    llm_base_url: "",
    llm_max_tokens: 8192,
    llm_temperature: 0.3,
  })
  const [showKey, setShowKey] = useState(false)
  const [llmSaved, setLlmSaved] = useState(false)
  const [llmTesting, setLlmTesting] = useState(false)

  // Embedding
  const [emb, setEmb] = useState<EmbeddingSettings>({
    embedding_enabled: false,
    embedding_endpoint: "http://localhost:11434/v1/embeddings",
    embedding_api_key: "",
    embedding_model: "nomic-embed-text",
  })
  const [embSaved, setEmbSaved] = useState(false)

  // Purpose / Schema
  const [purpose, setPurpose] = useState("")
  const [schema, setSchema] = useState("")
  const [purposeSaved, setPurposeSaved] = useState(false)

  useEffect(() => {
    api.getLlmSettings().then(setLlm).catch(console.error)
    api.getEmbeddingSettings().then(setEmb).catch(console.error)
    api.getPurpose().then((r) => setPurpose(r.content)).catch(console.error)
    api.getSchema().then((r) => setSchema(r.content)).catch(console.error)
  }, [])

  const saveLlm = async () => {
    setLlmTesting(true)
    toast({ type: "loading", message: "Testing connection..." })
    try {
      const result = await api.testLlmConnection(llm)
      if (result.ok) {
        toast({ type: "success", message: result.message })
        setLlmSaved(true)
        setTimeout(() => setLlmSaved(false), 2000)
      } else {
        toast({ type: "error", message: result.message })
      }
    } catch (e: any) {
      toast({ type: "error", message: e.message || "Connection test failed" })
    }
    setLlmTesting(false)
  }

  const saveEmb = async () => {
    await api.saveEmbeddingSettings(emb)
    setEmbSaved(true)
    setTimeout(() => setEmbSaved(false), 2000)
  }

  const savePurpose = async () => {
    await api.updatePurpose(purpose)
    setPurposeSaved(true)
    setTimeout(() => setPurposeSaved(false), 2000)
  }

  const needsCustomUrl = ["google", "azure", "deepseek", "groq", "together", "openrouter", "ollama", "custom"].includes(llm.llm_provider)

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="p-6 max-w-2xl space-y-10">
        <h2 className="text-lg font-semibold">Settings</h2>

        {/* ===== LLM Provider ===== */}
        <section className="space-y-4">
          <h3 className="text-sm font-medium border-b pb-1">LLM Provider</h3>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">Provider</label>
            <select
              value={llm.llm_provider}
              onChange={(e) => {
                const p = PROVIDERS.find((x) => x.value === e.target.value)
                setLlm({
                  ...llm,
                  llm_provider: e.target.value,
                  llm_base_url: p?.baseUrl ?? "",
                  llm_model: DEFAULT_MODELS[e.target.value] ?? "gpt-4o-mini",
                })
              }}
              className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">API Key</label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={llm.llm_api_key}
                onChange={(e) => setLlm({ ...llm, llm_api_key: e.target.value })}
                placeholder="sk-..."
                className="w-full rounded-lg border px-3 py-2 pr-10 text-sm bg-[var(--background)] font-mono"
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">Model</label>
            <input
              type="text"
              value={llm.llm_model}
              onChange={(e) => setLlm({ ...llm, llm_model: e.target.value })}
              placeholder="gpt-4o-mini"
              className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
            />
          </div>

          {needsCustomUrl && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--muted-foreground)]">Base URL</label>
              <input
                type="text"
                value={llm.llm_base_url}
                onChange={(e) => setLlm({ ...llm, llm_base_url: e.target.value })}
                placeholder={PROVIDERS.find((p) => p.value === llm.llm_provider)?.baseUrl || "https://api.example.com/v1"}
                className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--muted-foreground)]">Max Tokens</label>
              <input
                type="number"
                value={llm.llm_max_tokens}
                onChange={(e) => setLlm({ ...llm, llm_max_tokens: parseInt(e.target.value) || 8192 })}
                className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--muted-foreground)]">Temperature</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={llm.llm_temperature}
                onChange={(e) => setLlm({ ...llm, llm_temperature: parseFloat(e.target.value) || 0.3 })}
                className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
              />
            </div>
          </div>

          <button
            onClick={saveLlm}
            disabled={llmTesting}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {llmTesting ? <Loader size={14} className="animate-spin" /> : llmSaved ? <Check size={14} /> : <Save size={14} />}
            {llmTesting ? "Testing..." : llmSaved ? "Saved" : "Save & Test Connection"}
          </button>
        </section>

        {/* ===== Embedding ===== */}
        <section className="space-y-4">
          <h3 className="text-sm font-medium border-b pb-1">Vector Embedding (Optional)</h3>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={emb.embedding_enabled}
              onChange={(e) => setEmb({ ...emb, embedding_enabled: e.target.checked })}
              className="w-4 h-4 rounded"
            />
            Enable vector semantic search
          </label>

          {emb.embedding_enabled && (
            <>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Embedding Endpoint</label>
                <input
                  type="text"
                  value={emb.embedding_endpoint}
                  onChange={(e) => setEmb({ ...emb, embedding_endpoint: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Embedding Model</label>
                <input
                  type="text"
                  value={emb.embedding_model}
                  onChange={(e) => setEmb({ ...emb, embedding_model: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">API Key (optional)</label>
                <input
                  type="password"
                  value={emb.embedding_api_key}
                  onChange={(e) => setEmb({ ...emb, embedding_api_key: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
                />
              </div>
            </>
          )}

          <button
            onClick={saveEmb}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity"
          >
            {embSaved ? <Check size={14} /> : <Save size={14} />}
            {embSaved ? "Saved" : "Save Embedding Config"}
          </button>
        </section>

        {/* ===== Teaching Purpose ===== */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium border-b pb-1">
            Teaching Purpose
            <span className="text-[var(--muted-foreground)] font-normal ml-2 text-xs">— Goals, scope, key questions</span>
          </h3>
          <textarea
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            className="w-full h-36 rounded-lg border px-3 py-2 text-sm font-mono bg-[var(--background)] resize-y"
          />
          <button
            onClick={savePurpose}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity"
          >
            {purposeSaved ? <Check size={14} /> : <Save size={14} />}
            {purposeSaved ? "Saved" : "Save Purpose"}
          </button>
        </section>

        {/* ===== Wiki Schema ===== */}
        <section className="space-y-3 pb-6">
          <h3 className="text-sm font-medium border-b pb-1">
            Wiki Schema
            <span className="text-[var(--muted-foreground)] font-normal ml-2 text-xs">— Page types & structure rules</span>
          </h3>
          <textarea
            value={schema}
            onChange={(e) => setSchema(e.target.value)}
            className="w-full h-36 rounded-lg border px-3 py-2 text-sm font-mono bg-[var(--background)] resize-y"
          />
          <button
            onClick={async () => { await api.updateSchema(schema); setSchema(true as any); setTimeout(() => setSchema(schema), 2000) }}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity"
          >
            <Save size={14} />
            Save Schema
          </button>
        </section>
      </div>
    </div>
  )
}
