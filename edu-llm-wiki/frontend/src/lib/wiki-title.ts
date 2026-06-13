/**
 * Short, file-name-only label for a wiki path (`concepts/Seebeck效应.md` →
 * `Seebeck效应`). Used in card lists, chips, and frontmatter footers.
 */
export function pathLabel(path: string): string {
  return path.split("/").pop()?.replace(/\.md$/, "") ?? path
}

export function displayWikiTitle(page: { title: string; type?: string; page_type?: string; path: string }) {
  const type = page.type || page.page_type
  if (type !== "formula") return page.title
  return formulaDisplayTitle(page.title, page.path)
}

function formulaDisplayTitle(title: string, path: string) {
  const clean = title.trim()
  if (!looksLikeFormulaTitle(clean)) return clean
  const compact = clean.replace(/\s+/g, "")
  const plain = compact.replace(/\\/g, "")
  const patterns: [RegExp, string][] = [
    [/2d(?:\\sin|sin).*n(?:\\lambda|lambda|λ)/i, "布拉格定律"],
    [/J=.*(?:\\sigma|sigma|σ).*E/i, "电流密度与电场关系"],
    [/(?:\\rho|rho|ρ)=?(?:m\/V|\\frac\{m\}\{V\}|frac\{m\}\{V\})|m\/V|frac\{m\}\{V\}/i, "密度"],
    [/(?:\\DeltaV|DeltaV|ΔV).*?(?:\\alpha|alpha|α).*?(?:\\DeltaT|DeltaT|ΔT)/i, "塞贝克效应"],
    [/Q=.*C.*(?:\\DeltaT|DeltaT|ΔT)/i, "热容关系"],
    [/M=.*(?:\\chi|chi|χ).*H/i, "磁化率关系"],
    [/(?:\\ln|ln).*I\/I_?0.*(?:\\alpha|alpha|α).*x/i, "吸收定律"],
    [/Kohn-?Sham|H_?\{?\{?K\s*S/i, "Kohn-Sham 方程"],
    [/a=b=c/i, "立方晶系轴长关系"],
    [/a=b(?:\\+ne|\\ne|ne|≠|!=)c/i, "四方晶系轴长关系"],
    [/(?:\\alpha|alpha|α)=(?:\\beta|beta|β)=(?:\\gamma|gamma|γ)=90/i, "晶轴夹角关系"],
  ]
  const matched = patterns.find(([pattern]) => pattern.test(compact) || pattern.test(plain))
  if (matched) return matched[1]
  const fallback = decodeURIComponent(path.split("/").pop()?.replace(/\.md$/, "") || "").replace(/_/g, " ")
  return looksLikeFormulaTitle(fallback) ? "物理量关系" : fallback
}

function looksLikeFormulaTitle(title: string) {
  if (!title) return false
  if (/\\[a-zA-Z]+|[=≈≠≤≥<>]|[_^{}]/.test(title)) return true
  const symbolCount = (title.match(/[+\-*/=≈≠≤≥<>α-ωΑ-ΩσρλθχβγδεμτκΩ℃°]/g) || []).length
  const letterCount = (title.match(/[A-Za-zα-ωΑ-Ω]/g) || []).length
  return /\s[+\-*/=≈≠≤≥<>]\s/.test(title) || (symbolCount >= 2 && letterCount >= 1 && title.length <= 80)
}
