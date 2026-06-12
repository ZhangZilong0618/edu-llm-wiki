"""Shared output-language helpers for LLM prompts."""

from config import settings


def generation_language() -> str:
    value = (settings.generation_language or "zh").strip().lower()
    return value if value in {"zh", "en"} else "zh"


def language_name() -> str:
    return "English" if generation_language() == "en" else "Chinese"


def language_instruction() -> str:
    if generation_language() == "en":
        return (
            "Output language: English. Use English for prose, headings, page titles, "
            "feedback, synthesis pages, Q&A, and study guides. Preserve "
            "source terminology, symbols, file names, and established proper nouns when needed."
        )
    return (
        "输出语言：中文。正文、标题、页面名称、反馈、综合页、问答和学习指引都使用中文；"
        "必要时保留原文术语、符号、文件名和固定专有名词。"
    )
