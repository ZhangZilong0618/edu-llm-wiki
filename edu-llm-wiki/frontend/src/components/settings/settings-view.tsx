import { useEffect, useState } from "react"
import {
  BookOpen,
  Check,
  Database,
  ExternalLink,
  Eye,
  EyeOff,
  FileScan,
  KeyRound,
  Loader,
  Save,
  Settings2,
  SlidersHorizontal,
} from "lucide-react"
import { api, type EmbeddingSettings, type LlmSettings, type PaddleocrSettings } from "@/lib/api"
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

const NAV_ITEMS = [
  { id: "llm", label: "LLM", icon: Settings2 },
  { id: "embedding", label: "Embedding", icon: Database },
  { id: "parsing", label: "Parsing", icon: FileScan },
  { id: "purpose", label: "Purpose", icon: BookOpen },
  { id: "schema", label: "Schema", icon: SlidersHorizontal },
]

export function SettingsView() {
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
  const updateLlm = (patch: Partial<LlmSettings>) => {
    setLlm((p) => ({ ...p, ...patch }))
    setLlmSaved(false)
  }

  const [emb, setEmb] = useState<EmbeddingSettings>({
    embedding_enabled: false,
    embedding_endpoint: "http://localhost:11434/v1/embeddings",
    embedding_api_key: "",
    embedding_model: "nomic-embed-text",
  })
  const [embSaved, setEmbSaved] = useState(false)
  const updateEmb = (patch: Partial<EmbeddingSettings>) => {
    setEmb((p) => ({ ...p, ...patch }))
    setEmbSaved(false)
  }

  const [paddle, setPaddle] = useState<PaddleocrSettings>({
    paddleocr_token: "",
    paddleocr_model: "PaddleOCR-VL-1.6",
    paddleocr_orientation: false,
    paddleocr_unwarping: false,
    paddleocr_chart: false,
  })
  const [paddleSaved, setPaddleSaved] = useState(false)
  const [showPaddleToken, setShowPaddleToken] = useState(false)
  const updatePaddle = (patch: Partial<PaddleocrSettings>) => {
    setPaddle((p) => ({ ...p, ...patch }))
    setPaddleSaved(false)
  }

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
    } catch (e: unknown) {
      toast({ type: "error", message: errorMessage(e, "Failed to save settings") })
    }
    setLlmTesting(false)
  }

  const saveEmb = async () => {
    try {
      await api.saveEmbeddingSettings(emb)
      setEmbSaved(true)
      toast({ type: "success", message: "Embedding settings saved" })
    } catch (e: unknown) {
      toast({ type: "error", message: errorMessage(e, "Failed to save embedding settings") })
    }
  }

  const savePaddle = async () => {
    try {
      await api.savePaddleocrSettings(paddle)
      setPaddleSaved(true)
      toast({ type: "success", message: "Document parsing settings saved" })
    } catch (e: unknown) {
      toast({ type: "error", message: errorMessage(e, "Failed to save document parsing settings") })
    }
  }

  const savePurpose = async () => {
    try {
      await api.updatePurpose(purpose)
      setPurposeSaved(true)
      toast({ type: "success", message: "Purpose saved" })
    } catch (e: unknown) {
      toast({ type: "error", message: errorMessage(e, "Failed to save purpose") })
    }
  }

  const saveSchema = async () => {
    try {
      await api.updateSchema(schema)
      setSchemaSaved(true)
      toast({ type: "success", message: "Schema saved" })
    } catch (e: unknown) {
      toast({ type: "error", message: errorMessage(e, "Failed to save schema") })
    }
  }

  const needsCustomUrl = ["google", "azure", "deepseek", "groq", "together", "openrouter", "ollama", "custom"].includes(
    llm.llm_provider,
  )

  return (
    <div className="flex h-full overflow-hidden bg-[var(--background)]">
      <aside className="hidden lg:block w-52 shrink-0 border-r bg-[var(--sidebar)]">
        <div className="sticky top-0 p-3">
          <h2 className="px-2 py-2 text-xs font-semibold uppercase text-[var(--muted-foreground)]">Settings</h2>
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              return (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-[var(--sidebar-foreground)] hover:bg-[var(--accent)]"
                >
                  <Icon size={14} />
                  <span>{item.label}</span>
                </a>
              )
            })}
          </nav>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-5 py-5">
          <div className="mb-5 flex items-center justify-between gap-3 border-b pb-4">
            <div>
              <h1 className="text-lg font-semibold">Settings</h1>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                Configure model access, retrieval, document parsing, and wiki rules.
              </p>
            </div>
          </div>

          <Section
            id="llm"
            icon={<Settings2 size={16} />}
            title="LLM Provider"
            summary="Chat, ingest, lint, and exercise generation."
            footer={
              <SaveButton
                saved={llmSaved}
                busy={llmTesting}
                busyLabel="Testing..."
                savedLabel="Saved"
                label="Save & Test"
                onClick={saveLlm}
              />
            }
          >
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Provider">
                <select
                  value={llm.llm_provider}
                  onChange={(e) => {
                    const provider = PROVIDERS.find((p) => p.value === e.target.value)
                    updateLlm({
                      llm_provider: e.target.value,
                      llm_base_url: provider?.baseUrl ?? "",
                      llm_model: DEFAULT_MODELS[e.target.value] ?? "gpt-4o-mini",
                    })
                  }}
                  className={inputClass}
                >
                  {PROVIDERS.map((provider) => (
                    <option key={provider.value} value={provider.value}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Model">
                <input
                  type="text"
                  value={llm.llm_model}
                  onChange={(e) => updateLlm({ llm_model: e.target.value })}
                  placeholder="gpt-4o-mini"
                  className={inputClass}
                />
              </Field>
            </div>

            <Field label="API Key">
              <SecretInput
                value={llm.llm_api_key}
                visible={showKey}
                onToggle={() => setShowKey((v) => !v)}
                onChange={(value) => updateLlm({ llm_api_key: value })}
                placeholder="sk-..."
              />
            </Field>

            {needsCustomUrl && (
              <Field label="Base URL">
                <input
                  type="text"
                  value={llm.llm_base_url}
                  onChange={(e) => updateLlm({ llm_base_url: e.target.value })}
                  placeholder={PROVIDERS.find((p) => p.value === llm.llm_provider)?.baseUrl || "https://api.example.com/v1"}
                  className={inputClass}
                />
              </Field>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Max Tokens">
                <input
                  type="number"
                  value={llm.llm_max_tokens}
                  onChange={(e) => updateLlm({ llm_max_tokens: parseInt(e.target.value) || 8192 })}
                  className={inputClass}
                />
              </Field>
              <Field label="Temperature">
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={llm.llm_temperature}
                  onChange={(e) => updateLlm({ llm_temperature: parseFloat(e.target.value) || 0.3 })}
                  className={inputClass}
                />
              </Field>
            </div>
          </Section>

          <Section
            id="embedding"
            icon={<Database size={16} />}
            title="Vector Embedding"
            summary="Semantic search and RAG retrieval."
            footer={<SaveButton saved={embSaved} label="Save Embedding" savedLabel="Saved" onClick={saveEmb} />}
          >
            <ToggleRow
              checked={emb.embedding_enabled}
              onChange={(checked) => updateEmb({ embedding_enabled: checked })}
              label="Enable vector semantic search"
            />

            {emb.embedding_enabled && (
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Endpoint">
                  <input
                    type="text"
                    value={emb.embedding_endpoint}
                    onChange={(e) => updateEmb({ embedding_endpoint: e.target.value })}
                    className={inputClass}
                  />
                </Field>
                <Field label="Model">
                  <input
                    type="text"
                    value={emb.embedding_model}
                    onChange={(e) => updateEmb({ embedding_model: e.target.value })}
                    className={inputClass}
                  />
                </Field>
                <Field label="API Key">
                  <input
                    type="password"
                    value={emb.embedding_api_key}
                    onChange={(e) => updateEmb({ embedding_api_key: e.target.value })}
                    className={inputClass}
                  />
                </Field>
              </div>
            )}
          </Section>

          <Section
            id="parsing"
            icon={<FileScan size={16} />}
            title="Document Parsing"
            summary="PaddleOCR-VL settings for PDF and image parsing."
            footer={<SaveButton saved={paddleSaved} label="Save Parsing" savedLabel="Saved" onClick={savePaddle} />}
          >
            <div className="flex items-center justify-between gap-3 rounded-md border bg-[var(--muted)]/35 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2 text-xs text-[var(--muted-foreground)]">
                <KeyRound size={13} />
                <span className="truncate">AI Studio access token</span>
              </div>
              <a
                href="https://aistudio.baidu.com/paddleocr"
                target="_blank"
                rel="noreferrer"
                className="flex shrink-0 items-center gap-1 text-xs text-[var(--primary)] hover:underline"
              >
                Apply
                <ExternalLink size={12} />
              </a>
            </div>

            <Field label="API Token">
              <SecretInput
                value={paddle.paddleocr_token}
                visible={showPaddleToken}
                onToggle={() => setShowPaddleToken((v) => !v)}
                onChange={(value) => updatePaddle({ paddleocr_token: value })}
                placeholder="Enter token"
              />
            </Field>

            <Field label="Model">
              <input
                type="text"
                value={paddle.paddleocr_model}
                onChange={(e) => updatePaddle({ paddleocr_model: e.target.value })}
                className={inputClass}
              />
            </Field>

            <div className="grid gap-2 md:grid-cols-3">
              <ToggleRow
                checked={paddle.paddleocr_orientation}
                onChange={(checked) => updatePaddle({ paddleocr_orientation: checked })}
                label="Orientation"
              />
              <ToggleRow
                checked={paddle.paddleocr_unwarping}
                onChange={(checked) => updatePaddle({ paddleocr_unwarping: checked })}
                label="Unwarping"
              />
              <ToggleRow
                checked={paddle.paddleocr_chart}
                onChange={(checked) => updatePaddle({ paddleocr_chart: checked })}
                label="Charts"
              />
            </div>
          </Section>

          <Section
            id="purpose"
            icon={<BookOpen size={16} />}
            title="Teaching Purpose"
            summary="Goals, scope, and key questions used during ingest and chat."
            footer={<SaveButton saved={purposeSaved} label="Save Purpose" savedLabel="Saved" onClick={savePurpose} />}
          >
            <textarea
              value={purpose}
              onChange={(e) => {
                setPurpose(e.target.value)
                setPurposeSaved(false)
              }}
              className={`${inputClass} min-h-44 resize-y font-mono leading-6`}
            />
          </Section>

          <Section
            id="schema"
            icon={<SlidersHorizontal size={16} />}
            title="Wiki Schema"
            summary="Page types, naming rules, and structure guidance."
            footer={<SaveButton saved={schemaSaved} label="Save Schema" savedLabel="Saved" onClick={saveSchema} />}
          >
            <textarea
              value={schema}
              onChange={(e) => {
                setSchema(e.target.value)
                setSchemaSaved(false)
              }}
              className={`${inputClass} min-h-44 resize-y font-mono leading-6`}
            />
          </Section>
        </div>
      </main>
    </div>
  )
}

const inputClass =
  "w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm outline-none transition-shadow focus:ring-2 focus:ring-[var(--primary)]/35"

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function Section({
  id,
  icon,
  title,
  summary,
  children,
  footer,
}: {
  id: string
  icon: React.ReactNode
  title: string
  summary: string
  children: React.ReactNode
  footer: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-4 border-b py-6 last:border-b-0">
      <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--muted)] text-[var(--muted-foreground)]">
              {icon}
            </span>
            {title}
          </div>
          <p className="max-w-sm text-xs leading-5 text-[var(--muted-foreground)]">{summary}</p>
        </div>
        <div className="space-y-4">
          {children}
          <div className="flex justify-end border-t pt-4">{footer}</div>
        </div>
      </div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-[var(--muted-foreground)]">{label}</span>
      {children}
    </label>
  )
}

function SecretInput({
  value,
  visible,
  placeholder,
  onToggle,
  onChange,
}: {
  value: string
  visible: boolean
  placeholder?: string
  onToggle: () => void
  onChange: (value: string) => void
}) {
  return (
    <div className="relative">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${inputClass} pr-10 font-mono`}
      />
      <button
        type="button"
        onClick={onToggle}
        className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
        title={visible ? "Hide" : "Show"}
      >
        {visible ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  )
}

function ToggleRow({
  checked,
  label,
  onChange,
}: {
  checked: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-[var(--accent)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded"
      />
      <span>{label}</span>
    </label>
  )
}

function SaveButton({
  saved,
  busy,
  label,
  savedLabel,
  busyLabel,
  onClick,
}: {
  saved: boolean
  busy?: boolean
  label: string
  savedLabel: string
  busyLabel?: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="flex min-w-32 items-center justify-center gap-2 rounded-md bg-[var(--primary)] px-3 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
    >
      {busy ? <Loader size={14} className="animate-spin" /> : saved ? <Check size={14} /> : <Save size={14} />}
      {busy ? busyLabel || "Saving..." : saved ? savedLabel : label}
    </button>
  )
}
