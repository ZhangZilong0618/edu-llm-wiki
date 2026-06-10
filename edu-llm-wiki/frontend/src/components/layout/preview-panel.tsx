import { useEffect, useRef, useState, type DragEvent } from "react"
import { Group, Panel, Separator } from "react-resizable-panels"
import { useAppStore } from "@/stores/app-store"
import { api } from "@/lib/api"
import { InlineMarkdown, Markdown } from "@/components/markdown"
import { toast } from "@/components/ui/toast"
import { BookOpenCheck, CheckCircle2, ChevronDown, ChevronRight, HelpCircle, ImagePlus, Loader2, Microscope, Network, RotateCcw, Save, Sparkles, X } from "lucide-react"
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
  exercise: [
    { id: "hint", label: "分步提示", description: "给提示，不直接暴露最终答案。" },
    { id: "check_answer", label: "解题标准", description: "生成判分标准、错因和标准路径。" },
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

function extractExerciseQuestion(markdown: string): string | null {
  const section = extractMarkdownSection(markdown, ["题目", "Question", "Problem"])
  if (section) return section

  const headingAfterQuestion = markdown.match(/^##\s*(?:题目|Question|Problem)\s*\n+\s*##\s+(.+)\s*$/im)
  const title = headingAfterQuestion?.[1]?.trim()
  if (title && !/^(解答|答案|Answer|Solution)$/i.test(title)) return title
  return null
}

function stripLeadingPageTitle(markdown: string, title: string): string {
  return markdown
    .replace(new RegExp(`^#\\s*${escapeRegExp(title)}\\s*\\n+`, "i"), "")
    .trim()
}

function cleanExerciseQuestion(markdown: string): string {
  return markdown
    .replace(/^#{1,6}\s+/, "")
    .replace(/^(题目|question|problem)\s*\n+/i, "")
    .trim()
}

function parseChoiceOptions(markdown: string | null): ChoiceOption[] {
  if (!markdown) return []
  const options: ChoiceOption[] = []
  for (const line of markdown.split("\n")) {
    const match = line.match(/^\s*(?:[-*]\s*)?([A-Ha-h])[\.\)、:：]\s*(.+)$/)
    if (match) {
      options.push({ key: match[1].toUpperCase(), text: match[2].trim() })
    } else if (line.trim() && options.length > 0) {
      options[options.length - 1] = {
        ...options[options.length - 1],
        text: `${options[options.length - 1].text}\n${line.trim()}`,
      }
    }
  }
  return options
}

type AnswerCheck = {
  level: "empty" | "weak" | "partial" | "good"
  title: string
  detail: string
  matched: string[]
  missing: string[]
}

type ChoiceOption = {
  key: string
  text: string
}

type ExerciseKind = {
  kind: "choice" | "blank" | "open"
  prompt: string
  options: ChoiceOption[]
  blankCount: number
}

const LOW_EFFORT_RE = /^(不会|不太会|不知道|不清楚|没思路|不会做|不懂|随便|不知道怎么做|no idea|idk)$/i
const STOP_TERMS = new Set([
  "题目", "解答", "答案", "计算", "如何", "通过", "已知", "实际", "实验室", "样品",
  "其中", "得到", "可以", "根据", "因此", "需要", "进行", "如下", "所以",
  "请结合", "文档中", "定义", "图表", "分析", "考察知识点", "待补充",
  "frac", "left", "right", "text", "begin", "end",
])
const PLACEHOLDER_SOLUTION_RE = /(请结合文档|待补充|暂无|todo|见原始文档|结合文档中的定义)/i

function normalizeAnswerText(text: string): string {
  return plainText(text)
    .toLowerCase()
    .replace(/ρ/g, "rho")
    .replace(/＝/g, "=")
}

function extractKeyTerms(text: string): string[] {
  const normalized = normalizeAnswerText(text)
  const terms = new Set<string>()

  const domainTerms = [
    "阿基米德", "密度", "质量", "体积", "浮力", "重力", "视重", "空气", "液体", "排开液体",
    "公式", "原理", "单位", "变量", "代入", "推导", "晶格", "常数",
    "热容", "电导率", "热导率", "能量", "力", "功率因子",
  ]
  for (const term of domainTerms) {
    if (normalized.includes(term)) terms.add(term)
  }

  for (const match of normalized.matchAll(/[a-z][a-z0-9']{0,8}/g)) {
    const term = match[0]
    if (STOP_TERMS.has(term)) continue
    if (/^rhos?$/.test(term)) continue
    if (term.length >= 2 || /^[a-z][0-9]$/.test(term)) terms.add(term)
  }

  for (const match of normalized.matchAll(/[\u4e00-\u9fff]{2,10}/g)) {
    const phrase = match[0]
    if (!STOP_TERMS.has(phrase)) terms.add(phrase)
  }

  for (const match of normalized.matchAll(/[a-z0-9']+\s*[=＋+\-*/／]\s*[a-z0-9'()+\-*/／]+/g)) {
    terms.add(match[0].replace(/\s+/g, ""))
  }

  return [...terms].filter((term) => term.length >= 2).slice(0, 18)
}

function hasUsefulSolution(solution: string | null): boolean {
  if (!solution) return false
  const text = plainText(solution)
  if (text.length < 12) return false
  return !PLACEHOLDER_SOLUTION_RE.test(text)
}

function inferReferenceAnswer(question: string, solution: string | null): string | null {
  if (hasUsefulSolution(solution)) return solution

  const text = normalizeAnswerText(question)
  const hasMassPair = /m\s*1|m1/.test(text) && /m\s*2|m2/.test(text)
  const hasLiquidDensity = text.includes("rho") || text.includes("密度")
  const isDensityQuestion = text.includes("样品密度") || text.includes("密度") || text.includes("液体")
  if (hasMassPair && hasLiquidDensity && isDensityQuestion) {
    return [
      "## 解答",
      "",
      "这类题用阿基米德原理。样品在液体中少掉的称量质量对应浮力，也就是排开液体的质量：",
      "",
      "$$m_1 - m_2 = \\rho_0 V$$",
      "",
      "所以样品体积为：",
      "",
      "$$V = \\frac{m_1 - m_2}{\\rho_0}$$",
      "",
      "样品密度为：",
      "",
      "$$\\rho_s = \\frac{m_1}{V} = \\frac{m_1\\rho_0}{m_1 - m_2}$$",
      "",
      "如果题目把已知液体密度直接记为 $\\rho$，则可写作：",
      "",
      "$$\\rho_s = \\frac{m_1\\rho}{m_1 - m_2}$$",
    ].join("\n")
  }

  return null
}

function buildHint(question: string, solution: string | null): string {
  const source = solution || question
  const terms = extractKeyTerms(source).filter((term) => !LOW_EFFORT_RE.test(term)).slice(0, 4)
  if (terms.length > 0) {
    return `先不要急着看答案。试着写出要用的原理/公式，并明确这些量之间的关系：${terms.join("、")}。`
  }
  return "先找出已知量、未知量，再写出要用的概念或公式；如果是计算题，先列式再代入。"
}

function parseExerciseKind(question: string, explicitType: string | null, explicitOptions: string | null, referenceAnswer: string | null): ExerciseKind {
  const lines = question.split("\n")
  const options: ChoiceOption[] = parseChoiceOptions(explicitOptions)
  const promptLines: string[] = []
  let collectingOptions = false

  for (const line of lines) {
    const match = line.match(/^\s*(?:[-*]\s*)?([A-Ha-h])[\.\)、:：]\s*(.+)$/)
    if (match) {
      collectingOptions = true
      if (!explicitOptions) options.push({ key: match[1].toUpperCase(), text: match[2].trim() })
    } else if (!collectingOptions) {
      promptLines.push(line)
    } else if (!explicitOptions && line.trim() && options.length > 0) {
      options[options.length - 1] = {
        ...options[options.length - 1],
        text: `${options[options.length - 1].text}\n${line.trim()}`,
      }
    }
  }

  const normalizedType = (explicitType || "").toLowerCase().replace(/[\s_-]+/g, "")
  const answerLooksChoice = !!referenceAnswer && /^\s*(?:答案[:：]?\s*)?[A-H][\.\)、:：\s]/i.test(referenceAnswer.trim())
  const blankMatches = [
    ...question.matchAll(/_{2,}|（\s*）|\(\s*\)|\[\s*]/g),
  ]
  if (normalizedType.includes("blank") || normalizedType.includes("填空")) {
    return {
      kind: "blank",
      prompt: question,
      options: [],
      blankCount: Math.min(Math.max(blankMatches.length, 1), 8),
    }
  }

  const shouldBeChoice = normalizedType.includes("choice") || normalizedType.includes("选择") || answerLooksChoice

  if (options.length >= 2 || shouldBeChoice) {
    return {
      kind: "choice",
      prompt: promptLines.join("\n").trim() || question,
      options,
      blankCount: 0,
    }
  }

  if (blankMatches.length > 0) {
    return {
      kind: "blank",
      prompt: question,
      options: [],
      blankCount: Math.min(blankMatches.length, 8),
    }
  }

  return { kind: "open", prompt: question, options: [], blankCount: 0 }
}

function cleanReferenceAnswerForKind(answer: string | null, kind: ExerciseKind): string | null {
  if (!answer || kind.kind !== "blank" || kind.options.length > 0) return answer
  return answer.replace(/^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：]\s*/, "").trim() || answer
}

function formatBlankAnswer(values: string[]): string {
  return values.map((value, index) => `第 ${index + 1} 空：${value.trim()}`).filter((line) => !line.endsWith("：")).join("\n")
}

function checkAnswer(answer: string, solution: string | null): AnswerCheck {
  const raw = answer.trim()
  const normalized = normalizeAnswerText(raw)
  if (!raw) {
    return {
      level: "empty",
      title: "还没有作答",
      detail: "先写一点你的思路：已知量是什么、要求什么、准备用哪个公式或原理。",
      matched: [],
      missing: [],
    }
  }
  if (normalized.length < 8 || LOW_EFFORT_RE.test(normalized)) {
    return {
      level: "weak",
      title: "这个回答还不能判分",
      detail: "现在更像是在表达“不会”。请至少写出一个可检查的步骤，例如使用的原理、关键公式、变量含义或最终表达式。",
      matched: [],
      missing: solution ? extractKeyTerms(solution).slice(0, 5) : [],
    }
  }
  if (!solution) {
    return {
      level: "partial",
      title: "已记录你的回答",
      detail: "这道题没有解析区，暂时无法自动对照标准答案；建议补充标准解答后再检查。",
      matched: [],
      missing: [],
    }
  }

  const user = normalizeAnswerText(answer)
  const keyTerms = extractKeyTerms(solution)
  const matched = keyTerms.filter((term) => user.includes(term)).slice(0, 6)
  const missing = keyTerms.filter((term) => !user.includes(term)).slice(0, 6)
  const coverage = keyTerms.length === 0 ? 0 : matched.length / Math.min(keyTerms.length, 10)

  if (coverage >= 0.55 || matched.length >= 5) {
    return {
      level: "good",
      title: "方向基本正确",
      detail: "你的回答覆盖了主要要点。下一步可以对照解析检查符号、单位、推导顺序和最终表达式是否完整。",
      matched,
      missing,
    }
  }
  if (coverage >= 0.25 || matched.length >= 2) {
    return {
      level: "partial",
      title: "有一部分思路，但还不完整",
      detail: "建议补上缺失的关键量、公式或推导关系。计算题不要只写结论，最好写出从已知量到目标量的列式过程。",
      matched,
      missing,
    }
  }
  return {
    level: "weak",
    title: "还没有抓到主要思路",
    detail: "先看提示，尝试写出本题使用的原理和关键公式；目前回答里没有覆盖参考解析中的核心信息。",
    matched,
    missing,
  }
}

function ExerciseContent({ page }: { page: WikiPage }) {
  const content = page.content
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const [showAnswer, setShowAnswer] = useState(false)
  const [showHint, setShowHint] = useState(false)
  const [userAnswer, setUserAnswer] = useState("")
  const [blankAnswers, setBlankAnswers] = useState<string[]>([])
  const [check, setCheck] = useState<AnswerCheck | null>(null)
  const [checking, setChecking] = useState(false)
  const [recognizingImage, setRecognizingImage] = useState(false)
  const [draggingImage, setDraggingImage] = useState(false)
  const [completingAction, setCompletingAction] = useState<"complete" | "regenerate" | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    setShowAnswer(false)
    setShowHint(false)
    setUserAnswer("")
    setBlankAnswers([])
    setCheck(null)
    setDraggingImage(false)
    setCompletingAction(null)
    setDone(false)
  }, [page.path])

  const parts = content.split(/(?=##\s*(?:解|答案|Answer|Solution|解答))/i)
  const rawQuestion = extractExerciseQuestion(content) || parts[0] || content
  const question = cleanExerciseQuestion(stripLeadingPageTitle(rawQuestion, page.title))
  const parsedReferenceAnswer = extractMarkdownSection(content, ["解答", "答案", "Answer", "Solution"])
  const explicitExerciseType = extractMarkdownSection(content, ["题型", "Type"])
  const explicitExerciseOptions = extractMarkdownSection(content, ["选项", "Options", "Choices"])
  const inferredReferenceAnswer = inferReferenceAnswer(question, parsedReferenceAnswer)
  const exerciseKind = parseExerciseKind(question, explicitExerciseType, explicitExerciseOptions, inferredReferenceAnswer || parsedReferenceAnswer)
  const referenceAnswer = cleanReferenceAnswerForKind(inferredReferenceAnswer, exerciseKind)
  const needsSolution = !hasUsefulSolution(parsedReferenceAnswer)
  const hint = buildHint(question, referenceAnswer)
  const feedbackTone = check?.level === "good"
    ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"
    : check?.level === "partial"
      ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
      : "border-slate-200 bg-slate-100 text-[var(--muted-foreground)] dark:border-slate-800 dark:bg-slate-900"

  const runCheck = async () => {
    const answerForCheck = exerciseKind.kind === "blank" ? formatBlankAnswer(blankAnswers) : userAnswer
    const fallback = checkAnswer(answerForCheck, referenceAnswer)
    if (fallback.level === "empty") {
      setCheck(fallback)
      return
    }
    setChecking(true)
    try {
      const res = await api.checkExercise({
        question,
        student_answer: answerForCheck,
        reference_answer: referenceAnswer || parsedReferenceAnswer,
        page_title: page.title,
        page_path: page.path,
        context: content,
      })
      setCheck({
        level: res.level,
        title: res.title,
        detail: res.detail,
        matched: res.matched || [],
        missing: res.missing || [],
      })
    } catch (e: any) {
      setCheck({ ...fallback, title: `${fallback.title}（本地兜底）` })
      toast({ type: "error", message: `AI 判题失败，已使用本地检查: ${e?.message || e}` })
    } finally {
      setChecking(false)
    }
  }

  const completeSolution = async (regenerate = false) => {
    setCompletingAction(regenerate ? "regenerate" : "complete")
    const shouldRepairQuestion = regenerate && exerciseKind.kind === "choice" && exerciseKind.options.length < 2
    try {
      const res = await api.completeExerciseSolution({
        page_path: page.path,
        note: regenerate
          ? shouldRepairQuestion
            ? "请补全题面和选择题选项，并重新生成更完整、清晰、适合教学的解析。当前题目像选择题但缺少 A/B/C/D 选项，请修复题型、题目和解答三部分。"
            : "请重新生成更完整、清晰、适合教学的解析，替换当前解析。不要沿用原解析的错误或占位内容。"
          : undefined,
      })
      setSelectedPage(res.page)
      setShowAnswer(true)
      setCheck(null)
      toast({ type: "success", message: regenerate ? "已重新生成并替换解析" : "已补全并写回答案" })
    } catch (e: any) {
      toast({ type: "error", message: `${regenerate ? "重新生成解析" : "补全答案"}失败: ${e?.message || e}` })
    } finally {
      setCompletingAction(null)
    }
  }

  const recognizeAnswerImage = async (file: File | null | undefined) => {
    if (!file) return
    if (!file.type.startsWith("image/")) {
      toast({ type: "error", message: "请拖入图片文件" })
      return
    }
    setRecognizingImage(true)
    try {
      const res = await api.recognizeChatImage(file)
      const extracted = res.text.trim()
      if (!extracted) {
        toast({ type: "error", message: "没有识别到可用文字" })
        return
      }
      setUserAnswer((prev) => prev.trim() ? `${prev.trim()}\n\n${extracted}` : extracted)
      if (exerciseKind.kind === "blank" && blankAnswers.every((value) => !value.trim())) {
        setBlankAnswers([extracted, ...Array(Math.max(0, exerciseKind.blankCount - 1)).fill("")])
      }
      setCheck(null)
      toast({ type: "success", message: "已识别图片内容并填入作答框" })
    } catch (e: any) {
      toast({ type: "error", message: `图片识别失败: ${e?.message || e}` })
    } finally {
      setRecognizingImage(false)
      if (imageInputRef.current) imageInputRef.current.value = ""
    }
  }

  const handleImageDrag = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    if (recognizingImage || checking) return
    if ([...event.dataTransfer.items].some((item) => item.kind === "file" && item.type.startsWith("image/"))) {
      event.dataTransfer.dropEffect = "copy"
      setDraggingImage(true)
    }
  }

  const handleImageDragLeave = (event: DragEvent<HTMLElement>) => {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
    setDraggingImage(false)
  }

  const handleImageDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setDraggingImage(false)
    if (recognizingImage || checking) return
    const image = [...event.dataTransfer.files].find((file) => file.type.startsWith("image/"))
    if (!image) {
      toast({ type: "error", message: "请拖入图片文件" })
      return
    }
    void recognizeAnswerImage(image)
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">题目</h3>
          {exerciseKind.kind === "choice" && exerciseKind.options.length >= 2 && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-950/30 dark:text-blue-300">
              单选题
            </span>
          )}
        </div>
        <div className="rounded-md border-l-4 border-[var(--primary)]/60 bg-[var(--muted)]/35 px-4 py-3">
          <Markdown>{exerciseKind.kind === "choice" ? exerciseKind.prompt : question}</Markdown>
        </div>
      </section>

      <section
        className={`relative rounded-md border bg-[var(--background)] transition-colors ${
          draggingImage ? "border-[var(--primary)] bg-[var(--primary)]/5 ring-2 ring-[var(--primary)]/20" : ""
        }`}
        onDragEnter={handleImageDrag}
        onDragOver={handleImageDrag}
        onDragLeave={handleImageDragLeave}
        onDrop={handleImageDrop}
      >
        {draggingImage && (
          <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-md border border-dashed border-[var(--primary)] bg-[var(--background)]/85 text-sm font-medium text-[var(--primary)] backdrop-blur-sm">
            <ImagePlus className="mr-2 h-4 w-4" />
            松开图片，识别到作答框
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">作答</h3>
          {done && (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200">
              已完成
            </span>
          )}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => recognizeAnswerImage(e.target.files?.[0])}
          />
          <button
            onClick={() => imageInputRef.current?.click()}
            disabled={recognizingImage || checking}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] disabled:opacity-50"
            title="拍照或上传手写答案图片，先识别到作答框"
          >
            {recognizingImage ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
            {recognizingImage ? "识别中..." : "拍照识别"}
          </button>
        </div>
        <div className="p-3">
          {exerciseKind.kind === "choice" && exerciseKind.options.length >= 2 ? (
            <div className="space-y-4">
              {/* 选择题选项区域 - 类似在线测试 */}
              <div className="space-y-2">
                {exerciseKind.options.map((option, index) => {
                  const selected = userAnswer.startsWith(`${option.key}.`)
                  const checked = check?.level !== undefined
                  const isCorrect = referenceAnswer && referenceAnswer.startsWith(`${option.key}.`)
                  const isUserChoice = selected
                  const showCorrect = checked && isCorrect
                  const showWrong = checked && isUserChoice && !isCorrect

                  return (
                    <button
                      key={option.key}
                      disabled={checked || checking}
                      onClick={() => {
                        if (selected) {
                          setUserAnswer("")
                        } else {
                          setUserAnswer(`${option.key}. ${option.text}`)
                        }
                        setCheck(null)
                      }}
                      className={`group flex w-full items-center gap-4 rounded-xl border-2 px-5 py-4 text-left transition-all duration-200 ${
                        checked
                          ? showCorrect
                            ? "border-emerald-400 bg-emerald-50/80 shadow-sm dark:border-emerald-700 dark:bg-emerald-950/30"
                            : showWrong
                              ? "border-red-400 bg-red-50/80 shadow-sm dark:border-red-700 dark:bg-red-950/30"
                              : "border-slate-200 bg-[var(--muted)]/10 dark:border-slate-800"
                          : selected
                            ? "border-[var(--primary)] bg-[var(--primary)]/5 shadow-md ring-1 ring-[var(--primary)]/20"
                            : "border-slate-200 bg-[var(--background)] hover:border-[var(--primary)]/50 hover:bg-[var(--muted)]/10 hover:shadow-sm dark:border-slate-800"
                      }`}
                    >
                      {/* 选项编号 - 圆形单选按钮样式 */}
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-base font-bold transition-all duration-200 ${
                          checked
                            ? showCorrect
                              ? "border-emerald-500 bg-emerald-500 text-white shadow-sm"
                              : showWrong
                                ? "border-red-500 bg-red-500 text-white shadow-sm"
                                : "border-slate-300 text-slate-400 dark:border-slate-700"
                            : selected
                              ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)] shadow-sm"
                              : "border-slate-300 text-slate-500 group-hover:border-[var(--primary)]/60 dark:border-slate-700"
                        }`}
                      >
                        {option.key}
                      </div>

                      {/* 选项文本 */}
                      <div className="flex-1 min-w-0">
                        <div className="text-base leading-relaxed whitespace-pre-wrap text-[var(--foreground)]">
                          <InlineMarkdown>{option.text}</InlineMarkdown>
                        </div>
                      </div>

                      {/* 正确/错误标记 */}
                      {checked && showCorrect && (
                        <div className="shrink-0 flex items-center gap-1 text-emerald-600 font-bold text-sm">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          正确答案
                        </div>
                      )}
                      {checked && showWrong && (
                        <div className="shrink-0 flex items-center gap-1 text-red-600 font-bold text-sm">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                          错误
                        </div>
                      )}
                      {!checked && selected && (
                        <div className="shrink-0 text-[var(--primary)]">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>

              {/* 操作按钮 */}
              {!check && (
                <div className="flex items-center gap-3 pt-2">
                  <button
                    onClick={runCheck}
                    disabled={!userAnswer.trim() || checking}
                    className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-6 py-3 text-sm font-semibold text-[var(--primary-foreground)] shadow-sm hover:shadow-md transition-shadow disabled:opacity-50"
                  >
                    {checking ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
                    {checking ? "判题中..." : "提交答案"}
                  </button>
                  <button
                    onClick={() => {
                      setUserAnswer("")
                      setCheck(null)
                    }}
                    className="inline-flex items-center gap-2 rounded-lg border px-4 py-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] transition-colors"
                  >
                    <RotateCcw size={16} />
                    清除选择
                  </button>
                  <button
                    onClick={() => setShowHint((v) => !v)}
                    className="inline-flex items-center gap-2 rounded-lg border px-4 py-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] transition-colors"
                  >
                    <HelpCircle size={16} />
                    提示
                  </button>
                </div>
              )}

              {/* 判题反馈 */}
              {check && (
                <div className={`rounded-xl border-2 px-5 py-4 ${
                  check.level === "good"
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100"
                    : check.level === "partial"
                      ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
                      : "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100"
                }`}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`flex h-6 w-6 items-center justify-center rounded-full text-sm font-bold ${
                      check.level === "good"
                        ? "bg-emerald-500 text-white"
                        : check.level === "partial"
                          ? "bg-amber-500 text-white"
                          : "bg-red-500 text-white"
                    }`}>
                      {check.level === "good" ? "✓" : check.level === "partial" ? "△" : "✗"}
                    </div>
                    <div className="font-bold text-base">{check.title}</div>
                  </div>
                  <p className="text-sm leading-relaxed">{check.detail}</p>
                  {(check.matched.length > 0 || check.missing.length > 0) && (
                    <div className="mt-3 space-y-1 text-sm">
                      {check.matched.length > 0 && (
                        <div className="flex items-start gap-2">
                          <span className="font-bold text-emerald-700 dark:text-emerald-300">✓ 已覆盖：</span>
                          <span>{check.matched.join("、")}</span>
                        </div>
                      )}
                      {check.missing.length > 0 && (
                        <div className="flex items-start gap-2">
                          <span className="font-bold text-amber-700 dark:text-amber-300">○ 建议补充：</span>
                          <span>{check.missing.join("、")}</span>
                        </div>
                      )}
                    </div>
                  )}
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      onClick={() => {
                        setCheck(null)
                        setUserAnswer("")
                      }}
                      className="inline-flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] transition-colors"
                    >
                      <RotateCcw size={14} />
                      再试一次
                    </button>
                    <button
                      onClick={() => setShowAnswer(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500 px-4 py-2 text-sm text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950/30 transition-colors"
                    >
                      查看解析
                    </button>
                    <button
                      onClick={() => setDone(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500 px-4 py-2 text-sm text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950/30 transition-colors"
                    >
                      标记完成
                    </button>
                  </div>
                </div>
              )}

              {showHint && !check && (
                <div className="rounded-lg bg-[var(--muted)]/50 px-4 py-3 border border-[var(--border)]">
                  <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                    <span className="font-semibold text-[var(--foreground)]">💡 提示：</span> {hint}
                  </p>
                </div>
              )}
            </div>
          ) : exerciseKind.kind === "blank" ? (
            <div className="space-y-2">
              {Array.from({ length: Math.max(1, exerciseKind.blankCount) }).map((_, index) => (
                <label key={index} className="block">
                  <span className="mb-1 block text-[11px] font-medium text-[var(--muted-foreground)]">第 {index + 1} 空</span>
                  <input
                    value={blankAnswers[index] || ""}
                    onChange={(e) => {
                      const next = [...blankAnswers]
                      next[index] = e.target.value
                      setBlankAnswers(next)
                      setUserAnswer(formatBlankAnswer(next))
                      setCheck(null)
                    }}
                    className="h-9 w-full rounded-md border bg-[var(--background)] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    placeholder="填写答案..."
                  />
                </label>
              ))}
            </div>
          ) : (
            <textarea
              value={userAnswer}
              onChange={(e) => {
                setUserAnswer(e.target.value)
                setCheck(null)
              }}
              placeholder="在这里写你的解题思路或答案..."
              className="min-h-32 w-full resize-y rounded-md border bg-[var(--background)] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
          )}
          {exerciseKind.kind !== "choice" || exerciseKind.options.length < 2 ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                onClick={runCheck}
                disabled={!(exerciseKind.kind === "blank" ? formatBlankAnswer(blankAnswers) : userAnswer).trim() || checking || recognizingImage}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3.5 py-2 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
              >
                {checking ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                {checking ? "判题中..." : "检查"}
              </button>
              <button
                onClick={() => setShowHint((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              >
                <HelpCircle size={13} />
                提示
              </button>
              <button
                onClick={() => {
                  setUserAnswer("")
                  setBlankAnswers([])
                  setCheck(null)
                  setShowAnswer(false)
                  setDone(false)
                }}
                className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              >
                <RotateCcw size={13} />
                重置
              </button>
              <button
                onClick={() => setDone(true)}
                className="sm:ml-auto inline-flex items-center gap-1.5 rounded-md border border-emerald-500 px-3 py-2 text-xs text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
              >
                标记完成
              </button>
            </div>
          ) : null}
          {showHint && (exerciseKind.kind !== "choice" || exerciseKind.options.length < 2) && (
            <p className="mt-2 rounded bg-[var(--muted)] px-2 py-1.5 text-xs text-[var(--muted-foreground)]">
              {hint}
            </p>
          )}
          {check && (exerciseKind.kind !== "choice" || exerciseKind.options.length < 2) && (
            <div className={`mt-2 rounded-md border px-3 py-2 text-xs ${feedbackTone}`}>
              <div className="font-medium">{check.title}</div>
              <p className="mt-1 leading-relaxed">{check.detail}</p>
              {(check.matched.length > 0 || check.missing.length > 0) && (
                <div className="mt-2 grid gap-1 sm:grid-cols-2">
                  {check.matched.length > 0 && (
                    <div>
                      <span className="font-medium">已覆盖：</span>
                      {check.matched.join("、")}
                    </div>
                  )}
                  {check.missing.length > 0 && (
                    <div>
                      <span className="font-medium">建议补充：</span>
                      {check.missing.join("、")}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {referenceAnswer ? (
        <div className="border-t pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowAnswer((v) => !v)}
              className="flex items-center gap-1.5 text-sm font-medium text-emerald-600 hover:text-emerald-700 transition-colors"
            >
              {showAnswer ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              {showAnswer ? "隐藏解析" : "显示解析"}
            </button>
            <button
              onClick={() => completeSolution(!needsSolution)}
              disabled={!!completingAction}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-[var(--primary)] px-2.5 py-1 text-xs text-[var(--primary)] hover:bg-[var(--primary)]/10 disabled:opacity-50"
              title={needsSolution ? "用 AI 生成标准解答并写回当前习题页" : "用 AI 重新生成解析并替换当前解答区"}
            >
              {completingAction === (needsSolution ? "complete" : "regenerate") ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {completingAction === (needsSolution ? "complete" : "regenerate") ? (needsSolution ? "补全中..." : "重生成中...") : (needsSolution ? "补全答案" : (exerciseKind.kind === "choice" && exerciseKind.options.length < 2 ? "修复题目并补全选项" : "重新生成解析"))}
            </button>
          </div>
          {needsSolution && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
              当前答案来自临时推断或原解析占位，可以补全后写回 wiki。
            </p>
          )}
          {showAnswer && (
            <div className="mt-2 pl-3 border-l-2 border-emerald-300 dark:border-emerald-700">
              <Markdown>{referenceAnswer}</Markdown>
            </div>
          )}
        </div>
      ) : (
        <div className="border-t pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs text-[var(--muted-foreground)] italic">尚无解析</p>
            <button
              onClick={() => completeSolution(false)}
              disabled={!!completingAction}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-[var(--primary)] px-2.5 py-1 text-xs text-[var(--primary)] hover:bg-[var(--primary)]/10 disabled:opacity-50"
              title="用 AI 生成标准解答并写回当前习题页"
            >
              {completingAction === "complete" ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {completingAction === "complete" ? "补全中..." : "补全答案"}
            </button>
          </div>
        </div>
      )}
    </div>
  )
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
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const setSelectedPage = useAppStore((s) => s.setSelectedPage)
  const selectPage = useAppStore((s) => s.selectPage)
  const actions = researchActionsFor(page.page_type)
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
    setLoading(true)
    onStateChange({ editingResult: false })
    try {
      const res = await api.runResearch({ page_path: page.path, action: selectedAction, note: state.note })
      onStateChange({ result: res })
    } catch (e: any) {
      toast({ type: "error", message: `深入探究失败: ${e?.message || e}` })
    } finally {
      setLoading(false)
    }
  }

  const saveNote = async () => {
    if (!state.result) return
    setSaving(true)
    try {
      const res = await api.saveResearchNote({ page_path: page.path, title: state.result.title, content: state.result.content })
      setSelectedPage(res.page)
      toast({ type: "success", message: "已保存到当前页面" })
    } catch (e: any) {
      toast({ type: "error", message: `保存失败: ${e?.message || e}` })
    } finally {
      setSaving(false)
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
  const [researchStates, setResearchStates] = useState<Record<string, ResearchPanelState>>({})

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

  const currentResearchState = researchStates[selectedPage.path] || defaultResearchState(selectedPage)
  const updateResearchState = (patch: Partial<ResearchPanelState>) => {
    setResearchStates((prev) => ({
      ...prev,
      [selectedPage.path]: {
        ...(prev[selectedPage.path] || defaultResearchState(selectedPage)),
        ...patch,
      },
    }))
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
            {selectedPage.page_type === "exercise" ? (
              <ExerciseContent page={selectedPage} />
            ) : editingPage ? (
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
