import { useEffect, useRef, useState } from "react"
import { Group, Panel, Separator } from "react-resizable-panels"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { InlineMarkdown, Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { BookOpenCheck, Loader2, Microscope, Network, Save, Sparkles, X } from "lucide-react"
import type { WikiPage } from "@/types/wiki"
import { displayWikiTitle } from "@/lib/wiki-title"

type ResearchAction = {
  id: string
  label: string
  description: string
}

type ResearchResult = {
  title: string
  content: string
  related_pages: { path: string; title: string; type: string }[]
}

type ResearchPanelState = {
  selectedAction: string
  note: string
  editingResult: boolean
  result: ResearchResult | null
}

const COMMON_RESEARCH_ACTIONS: ResearchAction[] = [
  { id: "explain", label: "深入解释", description: "换一种更清楚的讲法，补例子和直觉。" },
  { id: "prerequisites", label: "补前置知识", description: "列出看懂当前页需要先学什么。" },
  { id: "related", label: "关联知识", description: "梳理它和 wiki 里其他页面的关系。" },
  { id: "practice", label: "生成练习", description: "围绕当前页生成可训练的小题。" },
  { id: "completeness", label: "检查完整性", description: "指出当前页还缺哪些教学要素。" },
  { id: "custom", label: "自定义", description: "按你自己写的提示词深入研究当前页面。" },
]

const TYPE_RESEARCH_ACTIONS: Record<string, ResearchAction[]> = {
  concept: [
    { id: "examples", label: "例子/反例", description: "用材料科学场景说明概念边界。" },
    { id: "boundaries", label: "易混边界", description: "说明与相近概念的区别。" },
  ],
  formula: [
    { id: "derive", label: "推导公式", description: "梳理假设、推导步骤和物理意义。" },
    { id: "variables", label: "变量与单位", description: "逐项解释符号、单位和测量方式。" },
    { id: "boundaries", label: "适用边界", description: "说明什么时候能用，什么时候会失效。" },
  ],
  principle: [
    { id: "boundaries", label: "适用边界", description: "整理条件、失效情况和近似假设。" },
    { id: "examples", label: "材料案例", description: "对应真实或教学材料现象。" },
  ],
  source: [
    { id: "outline", label: "提炼大纲", description: "整理文档结构、概念、公式和练习。" },
    { id: "learning_path", label: "学习路线", description: "按顺序生成这份文档的学习路线。" },
  ],
  synthesis: [
    { id: "examples", label: "补充证据", description: "补充例子、证据和对比视角。" },
  ],
}

function researchActionsFor(pageType: string): ResearchAction[] {
  const seen = new Set<string>()
  return [...COMMON_RESEARCH_ACTIONS, ...(TYPE_RESEARCH_ACTIONS[pageType] || [])].filter((action) => {
    if (seen.has(action.id)) return false
    seen.add(action.id)
    return true
  })
}

function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\\(?:rho|theta|alpha|beta|gamma|Delta|delta|pi|mu|sigma|lambda|varepsilon|epsilon)/g, (m) => m.slice(1))
    .replace(/([A-Za-z])_\{?([0-9A-Za-z]+)\}?/g, "$1$2")
    .replace(/[#*_`>$\\{}[\]().,，。；;：:！？!?-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function extractMarkdownSection(markdown: string, headings: string[]): string | null {
  const headingPattern = headings.map(escapeRegExp).join("|")
  const match = markdown.match(new RegExp(`^##\\s*(?:${headingPattern})\\s*\\n([\\s\\S]*?)(?=^##\\s+|\\s*$)`, "im"))
  const section = match?.[1]?.trim()
  return section || null
}

function ResearchPanel({
  page,
  state,
  onStateChange,
  onClose,
}: {
  page: WikiPage
  state: ResearchPanelState
  onStateChange: (patch: Partial<ResearchPanelState>) => void
  onClose: () => void
}) {
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const selectPage = useAppStore((s) => s.selectPage)
  const operations = useAppStore((s) => s.operations)
  const beginOperation = useAppStore((s) => s.beginOperation)
  const endOperation = useAppStore((s) => s.endOperation)
  const actions = researchActionsFor(page.page_type)
  const runKey = `research:run:${page.path}`
  const saveKey = `research:save:${page.path}`
  const loading = Boolean(operations[runKey])
  const saving = Boolean(operations[saveKey])
  const selectedAction = actions.some((action) => action.id === state.selectedAction)
    ? state.selectedAction
    : actions[0]?.id || "explain"
  const activeAction = actions.find((action) => action.id === selectedAction)
  const isCustomAction = selectedAction === "custom"
  const canRunResearch = !loading && (!isCustomAction || state.note.trim().length > 0)

  useEffect(() => {
    if (selectedAction !== state.selectedAction) {
      onStateChange({ selectedAction })
    }
  }, [onStateChange, selectedAction, state.selectedAction])

  const runResearch = async () => {
    if (isCustomAction && !state.note.trim()) {
      toast({ type: "error", message: "先写一下自定义研究提示词" })
      return
    }
    beginOperation(runKey, "深入研究中")
    onStateChange({ editingResult: false })
    try {
      const res = await api.runResearch({ page_path: page.path, action: selectedAction, note: state.note })
      onStateChange({ result: res })
    } catch (e: any) {
      toast({ type: "error", message: `深入探究失败: ${e?.message || e}` })
    } finally {
      endOperation(runKey)
    }
  }

  const saveNote = async () => {
    if (!state.result) return
    beginOperation(saveKey, "保存研究笔记中")
    try {
      const res = await api.saveResearchNote({ page_path: page.path, title: state.result.title, content: state.result.content })
      setSelectedPage(res.page)
      toast({ type: "success", message: "已保存到当前页面" })
    } catch (e: any) {
      toast({ type: "error", message: `保存失败: ${e?.message || e}` })
    } finally {
      endOperation(saveKey)
    }
  }

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-t bg-[var(--background)]">
      <div className="shrink-0 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-[var(--primary)]/10 text-[var(--primary)]">
            <Microscope size={13} />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-xs font-semibold">深入探究</h3>
            <p className="truncate text-[11px] text-[var(--muted-foreground)]">{page.title}</p>
          </div>
          <button
            onClick={onClose}
            className="ml-auto rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title="Close research panel"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-0 overflow-hidden md:grid-cols-[minmax(220px,34%)_minmax(0,1fr)]">
        <div className="min-h-0 space-y-2 overflow-y-auto border-b p-3 md:border-b-0 md:border-r">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(86px,1fr))] gap-1.5">
            {actions.map((action) => (
              <button
                key={action.id}
                onClick={() => {
                  onStateChange({ selectedAction: action.id, result: null, editingResult: false })
                }}
                disabled={loading}
                className={`rounded-md border px-2 py-1.5 text-left transition-colors ${
                  selectedAction === action.id
                    ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                    : "hover:bg-[var(--muted)] disabled:opacity-50"
                }`}
                title={action.description}
              >
                <span className="block truncate text-xs font-medium">{action.label}</span>
              </button>
            ))}
          </div>
          {activeAction && (
            <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">{activeAction.description}</p>
          )}
          <textarea
            value={state.note}
            onChange={(e) => onStateChange({ note: e.target.value })}
            placeholder={isCustomAction ? "写下你想让 AI 深入研究的提示词..." : "可选：补充你想深入的角度..."}
            className="min-h-14 w-full resize-y rounded-md border bg-[var(--background)] px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          />
          <button
            onClick={runResearch}
            disabled={!canRunResearch}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {loading ? "研究中..." : "开始探究"}
          </button>
        </div>

        <div className="min-h-0 overflow-y-auto p-3">
        {!state.result && !loading && (
          <div className="flex h-full items-center justify-center text-center text-xs text-[var(--muted-foreground)]">
            <div>
              <BookOpenCheck className="mx-auto mb-2 h-8 w-8 opacity-30" />
              <p>选择一个动作，让当前页面继续长出可保存的研究笔记。</p>
            </div>
          </div>
        )}
        {loading && (
          <div className="flex h-full items-center justify-center text-xs text-[var(--muted-foreground)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            正在生成深入探究...
          </div>
        )}
        {state.result && !loading && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{state.result.title}</h3>
              <button
                onClick={() => onStateChange({ editingResult: !state.editingResult })}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors ${
                  state.editingResult ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
                title={state.editingResult ? "预览" : "编辑"}
              >
                {state.editingResult ? <BookOpenCheck size={12} /> : <Save size={12} />}
                {state.editingResult ? "预览" : "编辑"}
              </button>
              <button
                onClick={saveNote}
                disabled={saving}
                className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
                title="保存到当前页面"
              >
                {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                保存
              </button>
            </div>
            {state.editingResult ? (
              <textarea
                value={state.result.content}
                onChange={(e) => onStateChange({ result: state.result ? { ...state.result, content: e.target.value } : null })}
                className="min-h-[40vh] w-full flex-1 resize-y rounded-md border bg-[var(--background)] px-3 py-2 font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              />
            ) : (
              <div className="overflow-x-auto rounded-md border p-3">
                <Markdown>{state.result.content}</Markdown>
              </div>
            )}
            {state.result.related_pages.length > 0 && (
              <div className="rounded-md border p-2">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-[var(--muted-foreground)]">
                  <Network size={12} />
                  相关页面
                </div>
                <div className="space-y-1">
                  {state.result.related_pages.map((related) => (
                    <button
                      key={related.path}
                      onClick={() => selectPage(related.path)}
                      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-[var(--muted)]"
                    >
                      <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">{related.type}</span>
                      <span className="truncate">{related.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        </div>
      </div>
    </aside>
  )
}

function PageEditor({
  page,
  onSaved,
  onCancel,
}: {
  page: WikiPage
  onSaved: (updated: WikiPage) => void
  onCancel: () => void
}) {
  const [content, setContent] = useState(page.content)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setContent(page.content)
    setDirty(false)
  }, [page.path, page.content])

  const save = async () => {
    setSaving(true)
    try {
      await api.updatePage(page.path, { content })
      const updated = await api.getPage(page.path)
      onSaved(updated)
      toast({ type: "success", message: "页面已保存" })
    } catch (e: any) {
      toast({ type: "error", message: `保存失败: ${e?.message || e}` })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-[var(--muted-foreground)]">编辑模式</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onCancel}
            className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
          >
            取消
          </button>
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
      <textarea
        value={content}
        onChange={(e) => { setContent(e.target.value); setDirty(true) }}
        className="min-h-[60vh] w-full flex-1 resize-y rounded-md border bg-[var(--background)] px-3 py-2 font-mono text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
      />
    </div>
  )
}

export function PreviewPanel() {
  const selectedPage = useAppStore((s) => s.selectedPage)
  const selectedSource = useAppStore((s) => s.selectedSource)
  const setSelectedSource = useAppStore((s) => s.setSelectedSource)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [researchOpen, setResearchOpen] = useState(false)
  const [editingPage, setEditingPage] = useState(false)
  const researchStates = useAppStore((s) => s.researchStates)
  const updateResearchStateInStore = useAppStore((s) => s.updateResearchState)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, 0)
    setResearchOpen(false)
    setEditingPage(false)
  }, [selectedPage?.path, selectedSource?.filename])

  const defaultResearchState = (page: WikiPage): ResearchPanelState => ({
    selectedAction: researchActionsFor(page.page_type)[0]?.id || "explain",
    note: "",
    editingResult: false,
    result: null,
  })

  if (selectedSource) {
    const isPdf = selectedSource.extension === ".pdf" && selectedSource.view_url

    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="shrink-0 p-3 border-b flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-orange-100 text-orange-700">
            source
          </span>
          <h2 className="text-sm font-semibold truncate">{selectedSource.filename}</h2>
          <button
            onClick={() => setSelectedSource(null)}
            className="ml-auto text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            title="Close source preview"
          >
            &times;
          </button>
        </div>

        <div className="flex-1 overflow-y-auto" ref={scrollRef}>
          {isPdf ? (
            <iframe
              src={selectedSource.view_url!}
              className="w-full h-full border-0"
              title={selectedSource.filename}
              style={{ minHeight: "80vh" }}
            />
          ) : (
            <div className="p-4">
              {selectedSource.images.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-xs font-semibold text-[var(--muted-foreground)] uppercase mb-2">Images</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {selectedSource.images.map((url, i) => (
                      <img
                        key={i}
                        src={url}
                        alt={`Image ${i + 1}`}
                        className="w-full rounded border border-[var(--border)]"
                        loading="lazy"
                      />
                    ))}
                  </div>
                </div>
              )}
              {selectedSource.content && (
                <Markdown>{selectedSource.content}</Markdown>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (!selectedPage) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[var(--muted-foreground)]">
        <p>Select a page to preview</p>
      </div>
    )
  }

  const currentResearchState = (researchStates[selectedPage.path] as ResearchPanelState | undefined) || defaultResearchState(selectedPage)
  const updateResearchState = (patch: Partial<ResearchPanelState>) => {
    updateResearchStateInStore(selectedPage.path, patch, defaultResearchState(selectedPage))
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-3 border-b">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
            {selectedPage.page_type}
          </span>
          <h2 className="text-sm font-semibold truncate">{displayWikiTitle(selectedPage)}</h2>
          <button
            onClick={() => setResearchOpen((v) => !v)}
            className={`ml-auto inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors ${
              researchOpen
                ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
            title="深入探究当前页面"
          >
            <Microscope size={13} />
            深入探究
          </button>
        </div>
        {selectedPage.sources.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {selectedPage.sources.map((s) => (
              <span key={s} className="px-1.5 py-0.5 text-[10px] rounded bg-[var(--muted)] text-[var(--muted-foreground)]">
                {s}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <Group orientation="vertical" className="min-h-0 flex-1 overflow-hidden">
        <Panel
          id="wiki-preview-content"
          defaultSize={researchOpen ? "58%" : "100%"}
          minSize="28%"
          className="min-h-0 overflow-hidden"
        >
          <div className="h-full min-h-0 overflow-y-auto p-4" ref={selectedPage ? scrollRef : undefined}>
            {editingPage ? (
              <PageEditor page={selectedPage} onSaved={(updated) => { setSelectedPage(updated); setEditingPage(false) }} onCancel={() => setEditingPage(false)} />
            ) : (
              <>
                <Markdown>{selectedPage.content || "*No content*"}</Markdown>
                <div className="mt-6 flex items-center gap-2 border-t pt-3">
                  <button
                    onClick={() => setEditingPage(true)}
                    className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                  >
                    <Save size={12} />
                    编辑页面
                  </button>
                </div>
              </>
            )}
          </div>
        </Panel>
        {researchOpen && (
          <>
            <Separator className="h-1.5 shrink-0 cursor-row-resize bg-[var(--border)] transition-colors hover:bg-[var(--primary)] data-[resize-handle-active]:bg-[var(--primary)]" />
            <Panel id="wiki-preview-research" defaultSize="42%" minSize="24%" className="min-h-0 overflow-hidden">
              <ResearchPanel
                page={selectedPage}
                state={currentResearchState}
                onStateChange={updateResearchState}
                onClose={() => setResearchOpen(false)}
              />
            </Panel>
          </>
          )}
      </Group>
    </div>
  )
}
