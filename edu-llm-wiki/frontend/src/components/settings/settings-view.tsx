import { useState, useEffect } from "react"
import { api, type LlmSettings, type EmbeddingSettings, type PaddleocrSettings } from "@/lib/api"
import { Eye, EyeOff, Save, Check, Loader, FileScan, ExternalLink } from "lucide-react"
import { toast } from "@/components/ui/toast"

const PROVIDERS = [
  { value: "openai", label: "OpenAI", baseUrl: "" },
  { value: "anthropic", label: "Anthropic", baseUrl: "" },
  { value: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com" },
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
  deepseek: "deepseek-v4-flash",
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
  const updateLlm = (patch: Partial<LlmSettings>) => { setLlm((p) => ({ ...p, ...patch })); setLlmSaved(false) }

  // Embedding
  const [emb, setEmb] = useState<EmbeddingSettings>({
    embedding_enabled: false,
    embedding_endpoint: "http://localhost:11434/v1/embeddings",
    embedding_api_key: "",
    embedding_model: "nomic-embed-text",
  })
  const [embSaved, setEmbSaved] = useState(false)
  const updateEmb = (patch: Partial<EmbeddingSettings>) => { setEmb((p) => ({ ...p, ...patch })); setEmbSaved(false) }

  // PaddleOCR Document Parsing
  const [paddle, setPaddle] = useState<PaddleocrSettings>({
    paddleocr_token: "",
    paddleocr_model: "PaddleOCR-VL-1.6",
    paddleocr_orientation: false,
    paddleocr_unwarping: false,
    paddleocr_chart: false,
  })
  const [paddleSaved, setPaddleSaved] = useState(false)
  const [showPaddleToken, setShowPaddleToken] = useState(false)
  const updatePaddle = (patch: Partial<PaddleocrSettings>) => { setPaddle((p) => ({ ...p, ...patch })); setPaddleSaved(false) }

  // Purpose / Schema
  const [purpose, setPurpose] = useState("")
  const [schema, setSchema] = useState("")
  const [purposeSaved, setPurposeSaved] = useState(false)
  const [schemaSaved, setSchemaSaved] = useState(false)

  useEffect(() => {
    api.getLlmSettings().then(setLlm).catch(console.error)
    api.getEmbeddingSettings().then(setEmb).catch(console.error)
    api.getPaddleocrSettings().then(setPaddle).catch(console.error)
    api.getPurpose().then((r) => setPurpose(r.content)).catch(console.error)
    api.getSchema().then((r) => setSchema(r.content)).catch(console.error)
  }, [])

  const saveLlm = async () => {
    setLlmTesting(true)
    try {
      await api.saveLlmSettings(llm)
      toast({ type: "loading", message: "Settings saved. Testing connection..." })
      const result = await api.testLlmConnection(llm)
      if (result.ok) {
        toast({ type: "success", message: result.message })
        setLlmSaved(true)
      } else {
        toast({ type: "error", message: result.message })
      }
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to save settings" })
    }
    setLlmTesting(false)
  }

  const saveEmb = async () => {
    try {
      await api.saveEmbeddingSettings(emb)
      setEmbSaved(true)
      toast({ type: "success", message: "Embedding settings saved" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to save embedding settings" })
    }
  }

  const savePaddle = async () => {
    try {
      await api.savePaddleocrSettings(paddle)
      setPaddleSaved(true)
      toast({ type: "success", message: "Document parsing settings saved" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to save document parsing settings" })
    }
  }

  const savePurpose = async () => {
    try {
      await api.updatePurpose(purpose)
      setPurposeSaved(true)
      toast({ type: "success", message: "Purpose saved" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to save purpose" })
    }
  }

  const saveSchema = async () => {
    try {
      await api.updateSchema(schema)
      setSchemaSaved(true)
      toast({ type: "success", message: "Schema saved" })
    } catch (e: any) {
      toast({ type: "error", message: e?.message || "Failed to save schema" })
    }
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
                updateLlm({
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
                onChange={(e) => updateLlm({ llm_api_key: e.target.value })}
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
              onChange={(e) => updateLlm({ llm_model: e.target.value })}
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
                onChange={(e) => updateLlm({ llm_base_url: e.target.value })}
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
                onChange={(e) => updateLlm({ llm_max_tokens: parseInt(e.target.value) || 8192 })}
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
                onChange={(e) => updateLlm({ llm_temperature: parseFloat(e.target.value) || 0.3 })}
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
              onChange={(e) => updateEmb({ embedding_enabled: e.target.checked })}
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
                  onChange={(e) => updateEmb({ embedding_endpoint: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Embedding Model</label>
                <input
                  type="text"
                  value={emb.embedding_model}
                  onChange={(e) => updateEmb({ embedding_model: e.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">API Key (optional)</label>
                <input
                  type="password"
                  value={emb.embedding_api_key}
                  onChange={(e) => updateEmb({ embedding_api_key: e.target.value })}
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

        {/* ===== Document Parsing (PaddleOCR-VL) ===== */}
        <section className="space-y-4">
          <h3 className="text-sm font-medium border-b pb-1 flex items-center gap-2">
            <FileScan size={14} />
            Document Parsing (PaddleOCR-VL)
            <a
              href="https://aistudio.baidu.com/paddleocr"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--muted-foreground)] hover:text-[var(--primary)]"
              title="Apply for an access token"
            >
              <ExternalLink size={12} />
            </a>
            <span className="text-[var(--muted-foreground)] font-normal text-xs ml-auto">PDF & images → structured Markdown</span>
          </h3>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">API Token</label>
            <div className="relative">
              <input
                type={showPaddleToken ? "text" : "password"}
                value={paddle.paddleocr_token}
                onChange={(e) => updatePaddle({ paddleocr_token: e.target.value })}
                className="w-full rounded-lg border px-3 py-2 pr-10 text-sm bg-[var(--background)] font-mono"
                placeholder="Enter your AI Studio PaddleOCR token"
              />
              <button
                type="button"
                onClick={() => setShowPaddleToken((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {showPaddleToken ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              Apply for a free token at aistudio.baidu.com/paddleocr. Parsed documents appear alongside the original in the Import view.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">Model</label>
            <input
              type="text"
              value={paddle.paddleocr_model}
              onChange={(e) => updatePaddle({ paddleocr_model: e.target.value })}
              className="w-full rounded-lg border px-3 py-2 text-sm bg-[var(--background)]"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">Optional processing</label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={paddle.paddleocr_orientation}
                onChange={(e) => updatePaddle({ paddleocr_orientation: e.target.checked })}
                className="w-4 h-4 rounded"
              />
              Detect document orientation
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={paddle.paddleocr_unwarping}
                onChange={(e) => updatePaddle({ paddleocr_unwarping: e.target.checked })}
                className="w-4 h-4 rounded"
              />
              Unwarp distorted scans
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={paddle.paddleocr_chart}
                onChange={(e) => updatePaddle({ paddleocr_chart: e.target.checked })}
                className="w-4 h-4 rounded"
              />
              Recognize charts
            </label>
          </div>

          <button
            onClick={savePaddle}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity"
          >
            {paddleSaved ? <Check size={14} /> : <Save size={14} />}
            {paddleSaved ? "Saved" : "Save Parsing Config"}
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
            onChange={(e) => { setPurpose(e.target.value); setPurposeSaved(false) }}
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
            onChange={(e) => { setSchema(e.target.value); setSchemaSaved(false) }}
            className="w-full h-36 rounded-lg border px-3 py-2 text-sm font-mono bg-[var(--background)] resize-y"
          />
          <button
            onClick={saveSchema}
            className="flex items-center gap-2 px-4 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm hover:opacity-90 transition-opacity"
          >
            {schemaSaved ? <Check size={14} /> : <Save size={14} />}
            {schemaSaved ? "Saved" : "Save Schema"}
          </button>
        </section>
      </div>
    </div>
  )
}
