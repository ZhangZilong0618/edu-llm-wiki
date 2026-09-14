"""Tests for the chat citation anchor helper."""

from routes import chat


def test_best_anchor_picks_section_matching_query():
    content = (
        "## 定义\n失效是指产品因外观形态或微观结构发生变化而丧失规定功能。\n\n"
        "## 解释\n失效分析旨在找出失效的根本原因，从而预防同类失效再次发生。\n\n"
        "## 相关知识\n失效模式包括断裂、腐蚀、磨损等。"
    )
    # Query about "原因" should land on the 解释 section, not 定义.
    anchor = chat._best_anchor("失效分析的根本原因是什么？", content, "fallback")
    assert anchor == chat._slugify("解释")


def test_best_anchor_falls_back_to_first_heading_when_no_overlap():
    content = "## 定义\nx\n\n## 解释\ny"
    anchor = chat._best_anchor("完全不相关的查询", content, "fallback")
    assert anchor == chat._slugify("定义")


def test_best_anchor_returns_empty_when_page_has_no_headings():
    anchor = chat._best_anchor("anything", "just some prose without headings", "fallback")
    assert anchor == ""


def test_best_anchor_uses_fallback_when_no_sections():
    anchor = chat._best_anchor("anything", "", "Fallback Title")
    assert anchor == chat._slugify("Fallback Title")


def test_slugify_handles_cjk_and_punctuation():
    assert chat._slugify("Hello, World!") == "hello-world"
    assert chat._slugify("材料 失效 分析") == "材料-失效-分析"
    assert chat._slugify("失效分析") == "失效分析"
    assert chat._slugify("   ") == "section"
