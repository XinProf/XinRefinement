"""P3.6 · 三语国际化（zh / en / ja）。

轻量实现：``tr(key)`` 查当前语言字典，缺失时回退中文，再缺则原样返回 key。
GUI 控件在 ``retranslate()`` 时统一刷新文本，语言切换无需重启。
"""
from __future__ import annotations

from .catalog import LANGUAGES, TRANSLATIONS, language_label

_current = "zh"


def tr(key: str, lang: str | None = None) -> str:
    """翻译一个键；缺失按 zh → key 逐级回退。"""
    lang = lang or _current
    table = TRANSLATIONS.get(lang, {})
    if key in table:
        return table[key]
    if key in TRANSLATIONS.get("zh", {}):
        return TRANSLATIONS["zh"][key]
    return key


def set_language(lang: str) -> None:
    """切换语言（未知语言抛 ValueError，避免静默落到英文）。"""
    global _current
    if lang not in LANGUAGES:
        raise ValueError(f"未知语言: {lang!r}（可选 {LANGUAGES}）")
    _current = lang


def get_language() -> str:
    return _current


__all__ = ["tr", "set_language", "get_language", "LANGUAGES",
           "language_label"]
