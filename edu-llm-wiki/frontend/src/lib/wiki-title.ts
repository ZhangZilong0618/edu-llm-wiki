/**
 * Short, file-name-only label for a wiki path (`concepts/Seebeck-effect.md` →
 * `Seebeck effect`). Used in card lists, chips, and frontmatter footers.
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
    [/2d(?:\\sin|sin).*n(?:\\lambda|lambda|λ)/i, "Bragg's law"],
    [/J=.*(?:\\sigma|sigma|σ).*E/i, "Relationship between current density and electric field"],
    [/(?:\\rho|rho|ρ)=?(?:m\/V|\\frac\{m\}\{V\}|frac\{m\}\{V\})|m\/V|frac\{m\}\{V\}/i, "Density"],
    [/(?:\\DeltaV|DeltaV|ΔV).*?(?:\\alpha|alpha|α).*?(?:\\DeltaT|DeltaT|ΔT)/i, "Seebeck effect"],
    [/Q=.*C.*(?:\\DeltaT|DeltaT|ΔT)/i, "Heat Capacity Relation"],
    [/M=.*(?:\\chi|chi|χ).*H/i, "Susceptibility relation"],
    [/(?:\\ln|ln).*I\/I_?0.*(?:\\alpha|alpha|α).*x/i, "Absorption Law"],
    [/Kohn-?Sham|H_?\{?\{?K\s*S/i, "Kohn-Sham equations"],
    [/a=b=c/i, "Cubic crystal system axis length relationship"],
    [/a=b(?:\\+ne|\\ne|ne|≠|!=)c/i, "Tetragonal crystal system axis length relationship"],
    [/(?:\\alpha|alpha|α)=(?:\\beta|beta|β)=(?:\\gamma|gamma|γ)=90/i, "Crystal Axis Angle Relationships"],
  ]
  const matched = patterns.find(([pattern]) => pattern.test(compact) || pattern.test(plain))
  if (matched) return matched[1]
  const fallback = decodeURIComponent(path.split("/").pop()?.replace(/\.md$/, "") || "").replace(/_/g, " ")
  return looksLikeFormulaTitle(fallback) ? "Physical quantity relation" : fallback
}

function looksLikeFormulaTitle(title: string) {
  if (!title) return false
  if (/\\[a-zA-Z]+|[=≈≠≤≥<>]|[_^{}]/.test(title)) return true
  const symbolCount = (title.match(/[+\-*/=≈≠≤≥<>α-ωΑ-ΩσρλθχβγδεμτκΩ℃°]/g) || []).length
  const letterCount = (title.match(/[A-Za-zα-ωΑ-Ω]/g) || []).length
  return /\s[+\-*/=≈≠≤≥<>]\s/.test(title) || (symbolCount >= 2 && letterCount >= 1 && title.length <= 80)
}
