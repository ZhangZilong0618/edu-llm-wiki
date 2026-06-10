import { Children, cloneElement, isValidElement, useMemo, type ReactNode } from "react"
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

export function Markdown({ children }: { children: string }) {
  const processed = useMemo(() => wrapBareLatexCommands(convertLatexDelimiters(processWikiLinks(stripFrontmatter(children)))), [children])

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, rehypeKatex]}
        components={components}
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
