#!/usr/bin/env python3
"""Translate the cloned `en` project corpus to English via the DeepSeek API.

- Wiki markdown pages: translate YAML frontmatter values and body prose.
  File paths, [[wikilink targets]], code, and LaTeX are preserved so links
  and rendering keep working.
- graph.sqlite node labels / insight titles / community names: translated in
  place (node ids untouched so mastery/review data still binds).

Idempotent-ish: keeps a cache so re-runs don't re-pay for finished items.
"""
import json
import os
import re
import sqlite3
import time
import urllib.request
import ssl
_SSL = ssl._create_unverified_context()

ROOT = "/Users/zzl/文章/edullmwiki/系统/edu-llm-wiki/edu-llm-wiki/data/projects/en"
CACHE = "/tmp/en_corpus_cache.json"

_key = None
_ENV = "/Users/zzl/文章/edullmwiki/系统/edu-llm-wiki/edu-llm-wiki/backend/.env"
for line in open(_ENV, encoding="utf-8"):
    if line.startswith("LLM_API_KEY="):
        _key = line.strip().split("=", 1)[1]
assert _key, "no api key"


def llm(text, system):
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": text}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_key}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except Exception as e:
            print("  retry", attempt, e)
            time.sleep(3)
    raise RuntimeError("llm failed")


MD_SYSTEM = """You translate Chinese wiki pages for a materials-science educational system into English.
Rules:
- Keep the overall Markdown structure (headings, lists, tables, bold) intact.
- Translate YAML frontmatter VALUES to English; keep YAML KEYS unchanged.
- Inside [[wikilinks]] keep the TARGET exactly as-is (file paths stay in Chinese), but if a link has display text after a |, translate the display text.
- Keep LaTeX, math, chemical formulas, numbers, and units unchanged.
- Keep citation markers like [1] unchanged.
- Translate naturally for an undergraduate materials-science course; keep established proper nouns (Seebeck, Peltier, Debye, Bravais, Pauling...).
- Output ONLY the translated document, no commentary."""

LABEL_SYSTEM = """Translate each Chinese knowledge-graph label into a concise English label for a materials-science course graph.
Return a JSON object mapping each input id to its English label. No commentary."""

NODE_MAP_SYSTEM = """Translate the value (a Chinese phrase) into a concise English phrase for a materials-science course. Return JSON mapping id->english."""


def translate_page(path):
    src = open(path, encoding="utf-8").read()
    if not re.search(r"[\u4e00-\u9fff]", src):
        return False
    out = llm(src, MD_SYSTEM).strip()
    if out.startswith("```"):
        out = re.sub(r"^```[a-z]*\n", "", out)
        out = re.sub("\n```$", "", out)
    open(path, "w", encoding="utf-8").write(out)
    return True


def main():
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    # ---- 1. wiki pages ----
    pages = []
    for base, _, files in os.walk(os.path.join(ROOT, "wiki")):
        for f in files:
            if f.endswith(".md"):
                pages.append(os.path.join(base, f))
    pages.sort()
    done = 0
    for p in pages:
        rel = os.path.relpath(p, ROOT)
        key = "page:" + rel
        if cache.get(key) == "done":
            continue
        if translate_page(p):
            cache[key] = "done"
            done += 1
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"page [{done}] {rel}")
    print("pages translated:", done)

    # ---- 2. graph labels ----
    con = sqlite3.connect(os.path.join(ROOT, "graph.sqlite"))
    rows = con.execute("SELECT node_id, title FROM graph_nodes").fetchall()
    todo = {nid: lab for nid, lab in rows if re.search(r"[\u4e00-\u9fff]", lab or "")}
    if todo:
        ids = list(todo)
        # batch in chunks of 20
        mapping = {}
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            payload = {nid: todo[nid] for nid in chunk}
            out = llm(json.dumps(payload, ensure_ascii=False), NODE_MAP_SYSTEM)
            out = out.strip()
            if out.startswith("```"):
                out = re.sub(r"^```[a-z]*\n", "", out)
                out = re.sub("\n```$", "", out)
            mapping.update(json.loads(out))
        for nid, en_label in mapping.items():
            en_label = en_label.strip()
            if en_label:
                con.execute("UPDATE graph_nodes SET title=? WHERE node_id=?",
                            (en_label, nid))
        con.commit()
        print("node labels translated:", len(mapping))
    else:
        print("node labels already translated")

    # insights
    try:
        rows = con.execute("SELECT insight_id, title, description FROM graph_insights").fetchall()
        for iid, title, content in rows:
            if title and re.search(r"[\u4e00-\u9fff]", title):
                nt = llm(title, "Translate to a concise English sentence for a teaching-insight card. Output only the sentence.")
                nc = ""
                if content and re.search(r"[\u4e00-\u9fff]", content):
                    nc = llm(content, "Translate to concise English. Output only the translation.")
                con.execute("UPDATE graph_insights SET title=?, description=? WHERE insight_id=?",
                            (nt, nc or content, iid))
        con.commit()
    except Exception as e:
        print("insights skip:", e)
    try:
        rows = con.execute("SELECT community_id, label FROM graph_communities").fetchall()
        for cid, name in rows:
            if name and re.search(r"[\u4e00-\u9fff]", name):
                nn = llm(name, "Translate to a short English community name (2-5 words). Output only the name.")
                con.execute("UPDATE graph_communities SET label=? WHERE community_id=?", (nn, cid))
        con.commit()
    except Exception as e:
        print("communities skip:", e)
    con.close()
    print("done")


if __name__ == "__main__":
    main()
