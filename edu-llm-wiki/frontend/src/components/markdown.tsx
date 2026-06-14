import { Children, cloneElement, isValidElement, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { renderToString } from "katex"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeRaw from "rehype-raw"
import rehypeKatex from "rehype-katex"
import { useAppStore } from "@/stores/app-store"

function stripFrontmatter(text: string): string {
  if (text.startsWith("---")) {
    const end = text.indexOf("---", 3)
    if (end !== -1) return text.slice(end + 3).trimStart()
  }
  return text
}

function convertLatexDelimiters(text: string): string {
  // Convert \(...\) inline math to $...$
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => `$${math}$`)
  // Convert \[...\] display math to $$...$$
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `$$${math}$$`)
  // Repair common malformed wrappers produced by OCR/LLM output.
  text = text.replace(/\$\$\\n/g, "$$\n").replace(/\\n\$\$/g, "\n$$")
  text = text.replace(/\$\$\s*\n?\s*\$\$([\s\S]*?)\$\$\s*\n?\s*\$\$/g, "$$\n$1\n$$")
  return text
}

const LATEX_COMMANDS = [
  "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta",
  "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "upsilon",
  "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma",
  "Upsilon", "Phi", "Psi", "Omega", "partial", "infty", "sum", "prod", "int", "oint",
  "sqrt", "frac", "mathrm", "mathbf", "mathit", "mathcal", "mathbb", "mathfrak",
  "left", "right", "langle", "rangle", "lbrace", "rbrace", "lceil", "rceil", "lfloor", "rfloor",
  "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "lim", "max", "min",
  "det", "dim", "ker", "deg", "arg", "gcd", "Pr", "hom", "cdot", "times", "div",
  "le", "ge", "ne", "approx", "propto", "rightarrow", "leftarrow", "to",
]

function protectInlineSegments(text: string): { text: string; restore: (value: string) => string } {
  const segments: string[] = []
  const protect = (match: string) => {
    const token = `@@MD_SEG_${segments.length}@@`
    segments.push(match)
    return token
  }

  const protectedText = text
    .replace(/```[\s\S]*?```/g, protect)
    .replace(/`[^`\n]*`/g, protect)
    .replace(/\$\$[\s\S]*?\$\$/g, protect)
    .replace(/\$[^$\n]*?\$/g, protect)

  return {
    text: protectedText,
    restore(value: string) {
      return value.replace(/@@MD_SEG_(\d+)@@/g, (_m, index) => segments[Number(index)] || "")
    },
  }
}

function wrapBareLatexLine(line: string): string {
  if (!/\\[A-Za-z]+/.test(line)) return line

  const commandPattern = LATEX_COMMANDS.join("|")
  const commandRegex = new RegExp(`\\\\(?:${commandPattern})(?!\\w)`, "g")
  const hasEquationOperator = /[=≈≠≤≥<>]/.test(line)
  const hasCjk = /[\u4e00-\u9fff]/.test(line)
  const leading = line.match(/^\s*/)?.[0] || ""
  const trailing = line.match(/\s*$/)?.[0] || ""
  const trimmed = line.trim()

  if (hasEquationOperator && !hasCjk && trimmed.length <= 300) {
    return `${leading}$${trimmed}$${trailing}`
  }

  if (hasEquationOperator) {
    const firstCommand = line.search(commandRegex)
    if (firstCommand >= 0) {
      const prefix = line.slice(0, firstCommand)
      const expression = line.slice(firstCommand).replace(/[，。；;：:]\s*$/, "")
      const suffix = line.slice(firstCommand + expression.length)
      if (expression.trim()) return `${prefix}$${expression.trim()}$${suffix}`
    }
  }

  return line.replace(commandRegex, (cmd) => `$${cmd}$`)
}

function wrapBareLatexCommands(text: string): string {
  const protectedSegments = protectInlineSegments(text)
  const wrapped = protectedSegments.text
    .split("\n")
    .map(wrapBareLatexLine)
    .join("\n")
  return protectedSegments.restore(wrapped)
}

function processWikiLinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, path: string, label: string) => {
    const clean = path.trim().replace(/\.md$/, "")
    const display = (label || clean.split("/").pop() || clean).trim()
    return `[${display}](/wiki/${clean})`
  })
}

// Inline citation refs.
//
// Two accepted syntaxes inside one [ref: … ]:
//   1) Same file, multiple pages:  [ref:file.pdf#p=5, 8]
//   2) Multiple distinct refs:     [ref:fileA.pdf#p=5, fileB.pdf#p=8]
//
// We tokenize once, then emit one sentinel per (file, page) pair. Sentinels
// round-trip through markdown as plain text and are post-processed back into
// <CitationPopover> nodes by `renderTextWithCitations`.
const CITE_REF_BLOCK_RE = /\[ref:([^\]]+)\]/g

// 容错: LLM 写（p.1） / (p.1, 3) 之类纯括号页码时，前端也当引用处理。
// 升级这些为 [ref:<source>#p=N]，需要 Markdown 接收 defaultSource（页面所在源文件）做兜底。
const INLINE_PAGE_HINT_RE = /[（(]\s*p\.?\s*([0-9,\s]+)\s*[）)]/gi
function upgradeInlinePageHints(text: string, defaultSource: string | undefined): string {
  if (!defaultSource) return text
  return text.replace(INLINE_PAGE_HINT_RE, (_m, pages: string) => {
    const nums = pages.split(",").map((s) => s.trim()).filter((s) => /^\d+$/.test(s))
    if (!nums.length) return _m
    return nums.map((n) => `[ref:${defaultSource}#p=${n}]`).join("")
  })
}

function tokenizeCiteBlock(body: string): Array<{ file: string; page: number }> {
  // body is the inside of [...], e.g. "fileA.pdf#p=5, fileB.pdf#p=8" or "fileA.pdf#p=5,8".
  const parts = body.split(",").map((s) => s.trim()).filter(Boolean)
  const out: Array<{ file: string; page: number }> = []
  let currentFile: string | null = null
  for (const part of parts) {
    // Match "file#p=N" or just "N" (when a previous entry already supplied the file).
    const m = part.match(/^([^#]+)#p=(\d+)\s*$/)
    if (m) {
      currentFile = m[1].trim()
      const page = Number(m[2])
      if (currentFile && Number.isFinite(page) && page > 0) {
        out.push({ file: currentFile, page })
      }
      continue
    }
    const bare = part.match(/^(\d+)\s*$/)
    if (bare && currentFile) {
      const page = Number(bare[1])
      if (Number.isFinite(page) && page > 0) out.push({ file: currentFile, page })
      continue
    }
    // Malformed chunk — skip silently.
  }
  return out
}

function processCitationRefs(text: string): string {
  return text.replace(CITE_REF_BLOCK_RE, (_m, body: string) => {
    const tokens = tokenizeCiteBlock(body)
    if (!tokens.length) return _m
    // Group consecutive tokens from the same file so the popover shows
    // "multi-page" as tabs (and cross-file splits into multiple popovers).
    const groups: Array<Array<{ file: string; page: number }>> = []
    for (const t of tokens) {
      const last = groups[groups.length - 1]
      if (last && last[0].file === t.file) {
        last.push(t)
      } else {
        groups.push([t])
      }
    }
    return groups
      .map((g) =>
        g
          .map((t) => `@@CITE_REF:${t.file}#p=${t.page}@@`)
          .join("@@CITE_SEP@@"),
      )
      .join("@@CITE_GRP@@")
  })
}

// ────────────────────────────────────────────────────────────────────────────
// Citation popover

type PageCache = { content: string; hit_offsets: number[][]; page_label?: string }

const pageFetchCache = new Map<string, Promise<PageCache | null>>()
async function fetchPage(
  projectId: string,
  file: string,
  page: number,
  q: string,
): Promise<PageCache | null> {
  const key = `${projectId}|${file}|${page}|${q}`
  const cached = pageFetchCache.get(key)
  if (cached) return cached
  const url = `/api/ingest/sources/${encodeURIComponent(file)}/parsed-page/${page}` +
    `?project_id=${encodeURIComponent(projectId)}` +
    (q ? `&q=${encodeURIComponent(q)}` : "")
  const promise = fetch(url)
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => (j ? ({ content: j.content, hit_offsets: j.hit_offsets, page_label: j.page_label } as PageCache) : null))
    .catch(() => null)
  pageFetchCache.set(key, promise)
  return promise
}

function CitationPopover({
  file,
  pages,
  trigger,
  projectId,
  quote,
  verified,
}: {
  file: string
  pages: number[]
  trigger: ReactNode
  projectId: string
  quote?: string
  verified?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [cache, setCache] = useState<Record<number, PageCache | null>>({})
  const closeTimer = useRef<number | null>(null)

  const ensureLoaded = (page: number) => {
    if (cache[page] !== undefined) return
    // Pass quote through so the server can compute hit_offsets and the
    // popover body can highlight the cited sentence.
    fetchPage(projectId, file, page, quote || "").then((p) => {
      setCache((c) => ({ ...c, [page]: p }))
    })
  }

  const enter = () => {
    if (closeTimer.current) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
    setOpen(true)
    // Load all pages on first hover so they stack immediately.
    for (const p of pages) ensureLoaded(p)
  }
  const leave = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
    closeTimer.current = window.setTimeout(() => setOpen(false), 120)
  }

  const imageBase = `/api/ingest/sources/${encodeURIComponent(file)}/parsed-image/`
  const allLoaded = pages.every((p) => cache[p] !== undefined)
  const triggerClass = `cite-ref${verified === false ? " cite-ref--unverified" : ""}`
  const headBadge =
    verified === false ? (
      <span className="cite-popover__unverified-badge">未验证</span>
    ) : quote ? (
      <span className="cite-popover__quote-badge">quote 已定位</span>
    ) : null

  return (
    <span
      className="cite-popover-trigger"
      onMouseEnter={enter}
      onMouseLeave={leave}
      onFocus={enter}
      onBlur={leave}
      tabIndex={0}
    >
      {isValidElement<{ className?: string }>(trigger) && verified === false
        ? cloneElement(trigger, {
            className: [trigger.props.className, "cite-ref--unverified"]
              .filter(Boolean)
              .join(" "),
          })
        : trigger}
      {open && (
        <span
          className="cite-popover"
          role="dialog"
          onMouseEnter={enter}
          onMouseLeave={leave}
        >
          <span className="cite-popover__head">
            <span className="cite-popover__file">{file}</span>
            <span className="cite-popover__pages">
              {pages.length === 1
                ? `第 ${pages[0]} 页`
                : `第 ${pages.join("、")} 页 · 全部展开`}
            </span>
            {headBadge}
          </span>

          <div className="cite-popover__body">
            {!allLoaded && (
              <span className="cite-popover__empty">加载 {pages.length} 页…</span>
            )}
            {pages.map((p, i) => {
              const data = cache[p]
              if (!data) return null
              return (
                <div key={p} className="cite-popover__page">
                  {pages.length > 1 && (
                    <div className="cite-popover__page-label">第 {p} 页</div>
                  )}
                  <HighlightedMarkdown
                    content={data.content}
                    hitOffsets={data.hit_offsets}
                    imageBase={imageBase}
                    projectId={projectId}
                  />
                  {i < pages.length - 1 && (
                    <hr className="cite-popover__divider" />
                  )}
                </div>
              )
            })}
          </div>
        </span>
      )}
    </span>
  )
}

// Renders the page markdown (with image URLs rewritten to absolute) and wraps
// `hitOffsets` ranges in a yellow <mark>. The full set of supported blocks
// is intentionally narrow — the same subset the existing <Markdown> covers.
function HighlightedMarkdown({
  content,
  hitOffsets,
  imageBase,
}: {
  content: string
  hitOffsets: number[][]
  imageBase: string
  projectId: string
}) {
  // Rewrite relative image paths to absolute /api/ingest/.../parsed-image/...
  const rewritten = useMemo(() => {
    return content.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, src) => {
      if (/^https?:\/\//.test(src) || src.startsWith("/api/")) return `![${alt}](${src})`
      // Take the basename — the existing /parsed-image/{name} route accepts just the filename.
      const fname = src.split("/").pop() || src
      return `![${alt}](${imageBase}${encodeURIComponent(fname)})`
    })
  }, [content, imageBase])

  // Pre-mark the hit offsets with sentinel tokens, then post-process in the
  // p component to split into <mark>.
  const marked = useMemo(() => {
    if (!hitOffsets?.length) return rewritten
    const valid = hitOffsets
      .map(([s, e]) => [Math.max(0, s), Math.min(rewritten.length, e)] as [number, number])
      .filter(([s, e]) => e > s)
      .sort((a, b) => a[0] - b[0])
    if (!valid.length) return rewritten
    let out = ""
    let cursor = 0
    for (const [s, e] of valid) {
      if (s < cursor) continue
      out += rewritten.slice(cursor, s)
      out += `@@CITE_HIT@@${rewritten.slice(s, e)}@@/CITE_HIT@@`
      cursor = e
    }
    out += rewritten.slice(cursor)
    return out
  }, [rewritten, hitOffsets])

  // Recursively split a string with our hit sentinels into a list of nodes.
  const splitHits = (text: string, keyPrefix: string): ReactNode => {
    if (!text.includes("@@CITE_HIT@@")) return text
    const nodes: ReactNode[] = []
    const re = /@@CITE_HIT@@([\s\S]*?)@@\/CITE_HIT@@/g
    let last = 0
    let m: RegExpExecArray | null
    let k = 0
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) nodes.push(text.slice(last, m.index))
      nodes.push(
        <mark key={`${keyPrefix}-hit-${k++}`} className="cite-hit">
          {m[1]}
        </mark>,
      )
      last = re.lastIndex
    }
    if (last < text.length) nodes.push(text.slice(last))
    return nodes
  }

  const wrapHits = (children: ReactNode, keyPrefix: string): ReactNode =>
    Children.map(children, (child, idx) => {
      if (typeof child === "string") return splitHits(child, `${keyPrefix}-${idx}`)
      if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
        return cloneElement(child, {
          children: wrapHits(child.props.children, `${keyPrefix}-${idx}`),
        })
      }
      return child
    })

  return (
    <span className="markdown-body cite-popover__md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, rehypeKatex]}
        components={{
          ...components,
          p({ children: pChildren, ...props }: any) {
            return <p {...props}>{wrapHits(pChildren, "pp")}</p>
          },
          li({ children: lChildren, ...props }: any) {
            return <li {...props}>{wrapHits(lChildren, "ll")}</li>
          },
        }}
      >
        {marked}
      </ReactMarkdown>
    </span>
  )
}

// Counterpart: take the plain-text children react-markdown gives us, find the
// sentinel markers, and split them out into <CitationPopover> nodes.

type CitationStatus = (file: string, page: number) => "verified" | "unverified" | undefined
type CitationQuoteLookup = (file: string, page: number) => string | undefined

function renderTextWithCitations(
  text: string,
  keyPrefix: string,
  projectId: string,
  status: CitationStatus | undefined,
  quoteLookup: CitationQuoteLookup | undefined,
): ReactNode {
  if (!text.includes("@@CITE_REF:")) return text
  const nodes: ReactNode[] = []
  // Match one citation GROUP (one or more same-file refs joined by @@CITE_SEP@@).
  const groupRe = /@@CITE_REF:([^#]+)#p=\d+@@(?:@@CITE_SEP@@@@CITE_REF:\1#p=\d+@@)*/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = groupRe.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    // Split the group back into per-page entries.
    const chunk = m[0]
    const entries: Array<{ file: string; page: number }> = []
    const entryRe = /@@CITE_REF:([^#]+)#p=(\d+)@@/g
    let em: RegExpExecArray | null
    while ((em = entryRe.exec(chunk)) !== null) {
      entries.push({ file: em[1], page: Number(em[2]) })
    }
    if (!entries.length) continue
    const file = entries[0].file
    const pages = entries.map((e) => e.page)
    const label = pages.length === 1 ? `⁽ᵖ${pages[0]}⁾` : `⁽ᵖ${pages.join("·")}⁾`
    // Group status: if any page in the group is unverified, mark the whole
    // group unverified (mixed groups are rare and safer to err on the side
    // of caution).
    let groupVerified: boolean | undefined
    if (status) {
      let anyUnverified = false
      let anyVerified = false
      for (const e of entries) {
        const s = status(e.file, e.page)
        if (s === "unverified") anyUnverified = true
        else if (s === "verified") anyVerified = true
      }
      if (anyUnverified) groupVerified = false
      else if (anyVerified) groupVerified = true
    }
    // The first page's quote is forwarded to the popover so the server can
    // compute hit_offsets and the popover body can highlight the cited span.
    const primaryQuote = quoteLookup?.(file, pages[0])
    nodes.push(
      <CitationPopover
        key={`${keyPrefix}-cite-${k++}`}
        file={file}
        pages={pages}
        projectId={projectId}
        verified={groupVerified}
        quote={primaryQuote}
        trigger={<span className="cite-ref">{label}</span>}
      />,
    )
    last = groupRe.lastIndex
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function withCitations(
  children: ReactNode,
  keyPrefix: string,
  projectId: string,
  status: CitationStatus | undefined,
  quoteLookup: CitationQuoteLookup | undefined,
): ReactNode {
  return Children.map(children, (child, idx) => {
    if (typeof child === "string") {
      return renderTextWithCitations(child, `${keyPrefix}-${idx}`, projectId, status, quoteLookup)
    }
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return cloneElement(child, {
        children: withCitations(child.props.children, `${keyPrefix}-${idx}`, projectId, status, quoteLookup),
      })
    }
    return child
  })
}

function renderFormula(math: string, displayMode: boolean, key: string) {
  try {
    return (
      <span
        key={key}
        className={displayMode ? "block overflow-x-auto my-2" : "inline-block align-middle"}
        dangerouslySetInnerHTML={{
          __html: renderToString(math.trim(), {
            displayMode,
            throwOnError: false,
          }),
        }}
      />
    )
  } catch {
    return displayMode ? `$$${math}$$` : `$${math}$`
  }
}

function renderMathText(text: string, keyPrefix: string): ReactNode {
  const nodes: ReactNode[] = []
  let cursor = 0
  let key = 0

  while (cursor < text.length) {
    const start = text.indexOf("$", cursor)
    if (start === -1) {
      nodes.push(text.slice(cursor))
      break
    }

    if (start > cursor) nodes.push(text.slice(cursor, start))

    const displayMode = text[start + 1] === "$"
    const delimiter = displayMode ? "$$" : "$"
    const contentStart = start + delimiter.length
    const end = text.indexOf(delimiter, contentStart)

    if (end === -1) {
      nodes.push(text.slice(start))
      break
    }

    const math = text.slice(contentStart, end)
    if (math.trim()) {
      nodes.push(renderFormula(math, displayMode, `${keyPrefix}-${key++}`))
    } else {
      nodes.push(text.slice(start, end + delimiter.length))
    }
    cursor = end + delimiter.length
  }

  return nodes.length === 1 ? nodes[0] : nodes
}

function renderMathChildren(children: ReactNode, keyPrefix = "raw-math"): ReactNode {
  return Children.map(children, (child, index) => {
    if (typeof child === "string") return renderMathText(child, `${keyPrefix}-${index}`)
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return cloneElement(child, {
        children: renderMathChildren(child.props.children, `${keyPrefix}-${index}`),
      })
    }
    return child
  })
}

const components: any = {
  h1({ children, ...props }: any) {
    const text = typeof children === "string" ? children : ""
    const isResearch = text.includes("深入探究")
    return (
      <h1 className={`text-xl font-bold mt-6 mb-3 ${isResearch ? "border-l-4 border-purple-500 pl-3 text-purple-700 dark:text-purple-300" : ""}`} {...props}>
        {isResearch && <span className="mr-1.5">🔬</span>}
        {children}
      </h1>
    )
  },
  h2({ children, ...props }: any) {
    const text = typeof children === "string" ? children : ""
    const isResearch = text.includes("深入探究")
    return (
      <h2 className={`text-lg font-semibold mt-5 mb-2 ${isResearch ? "border-l-4 border-purple-500 pl-3 text-purple-700 dark:text-purple-300" : ""}`} {...props}>
        {isResearch && <span className="mr-1.5">🔬</span>}
        {children}
      </h2>
    )
  },
  h3({ children, ...props }: any) {
    return <h3 className="text-base font-semibold mt-4 mb-2" {...props}>{children}</h3>
  },
  a({ href, children, ...props }: any) {
    const selectPage = useAppStore.getState().selectPage
    if (href?.startsWith("/wiki/")) {
      const pagePath = href.replace("/wiki/", "")
      return (
        <button
          onClick={() => selectPage(pagePath)}
          className="text-[var(--primary)] underline hover:opacity-80"
          {...props}
        >
          {children}
        </button>
      )
    }
    return (
      <a href={href} target="_blank" rel="noopener" className="text-[var(--primary)] underline" {...props}>
        {children}
      </a>
    )
  },
  img({ src, alt, ...props }: any) {
    return <img src={src} alt={alt} className="max-w-full rounded-lg my-4 inline-block" loading="lazy" {...props} />
  },
  blockquote({ children, ...props }: any) {
    return <blockquote className="border-l-4 border-[var(--primary)] pl-4 my-4 text-[var(--muted-foreground)] italic" {...props}>{children}</blockquote>
  },
  table({ children, ...props }: any) {
    return <div className="overflow-x-auto my-4"><table className="w-full border-collapse text-sm" {...props}>{children}</table></div>
  },
  th({ children, ...props }: any) {
    return <th className="border px-2 py-1.5 bg-[var(--muted)] font-semibold align-top" {...props}>{renderMathChildren(children, "th")}</th>
  },
  td({ children, ...props }: any) {
    return <td className="border px-2 py-1.5 align-top" {...props}>{renderMathChildren(children, "td")}</td>
  },
  div({ children, ...props }: any) {
    return <div {...props}>{renderMathChildren(children, "div")}</div>
  },
  span({ children, ...props }: any) {
    return <span {...props}>{renderMathChildren(children, "span")}</span>
  },
  hr(props: any) {
    return <hr className="my-6 border-[var(--border)]" {...props} />
  },
}

export function Markdown({
  children,
  projectId,
  enableCitations = false,
  citationStatus,
  citationQuoteLookup,
  defaultSource,
}: {
  children: string
  projectId?: string
  enableCitations?: boolean
  citationStatus?: CitationStatus
  citationQuoteLookup?: CitationQuoteLookup
  defaultSource?: string
}) {
  const processed = useMemo(
    () =>
      wrapBareLatexCommands(
        convertLatexDelimiters(
          processCitationRefs(
            upgradeInlinePageHints(
              processWikiLinks(stripFrontmatter(children)),
              defaultSource,
            ),
          ),
        ),
      ),
    [children, defaultSource],
  )

  const pid = projectId || "default"
  const componentsWithCitations = useMemo(
    () => ({
      ...components,
      p({ children: pChildren, ...props }: any) {
        return (
          <p {...props}>
            {enableCitations
              ? withCitations(pChildren, "p", pid, citationStatus, citationQuoteLookup)
              : renderMathChildren(pChildren, "p")}
          </p>
        )
      },
      li({ children: lChildren, ...props }: any) {
        return (
          <li {...props}>
            {enableCitations
              ? withCitations(lChildren, "li", pid, citationStatus, citationQuoteLookup)
              : renderMathChildren(lChildren, "li")}
          </li>
        )
      },
    }),
    [enableCitations, pid, citationStatus, citationQuoteLookup],
  )

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, rehypeKatex]}
        components={componentsWithCitations}
      >
        {processed}
      </ReactMarkdown>
    </div>
  )
}

export function InlineMarkdown({ children }: { children: string }) {
  const processed = useMemo(() => wrapBareLatexCommands(convertLatexDelimiters(processWikiLinks(stripFrontmatter(children)))), [children])

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeRaw, rehypeKatex]}
      components={{
        ...components,
        p({ children: pChildren, ...props }: any) {
          return <span className="leading-relaxed" {...props}>{renderMathChildren(pChildren, "inline-p")}</span>
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  )
}
