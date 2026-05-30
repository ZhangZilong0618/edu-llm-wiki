import { useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import { useAppStore } from "@/stores/app-store"

function stripFrontmatter(text: string): string {
  if (text.startsWith("---")) {
    const end = text.indexOf("---", 3)
    if (end !== -1) return text.slice(end + 3).trimStart()
  }
  return text
}

function processWikiLinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, path: string, label: string) => {
    const clean = path.trim().replace(/\.md$/, "")
    const display = (label || clean.split("/").pop() || clean).trim()
    return `[${display}](/wiki/${clean})`
  })
}

const components: any = {
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
    return <img src={src} alt={alt} className="max-w-full rounded-lg my-4" loading="lazy" {...props} />
  },
  blockquote({ children, ...props }: any) {
    return <blockquote className="border-l-4 border-[var(--primary)] pl-4 my-4 text-[var(--muted-foreground)] italic" {...props}>{children}</blockquote>
  },
  table({ children, ...props }: any) {
    return <div className="overflow-x-auto my-4"><table className="w-full border-collapse" {...props}>{children}</table></div>
  },
  hr(props: any) {
    return <hr className="my-6 border-[var(--border)]" {...props} />
  },
}

export function Markdown({ children }: { children: string }) {
  const processed = useMemo(() => processWikiLinks(stripFrontmatter(children)), [children])

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {processed}
      </ReactMarkdown>
    </div>
  )
}
