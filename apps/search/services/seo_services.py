from __future__ import annotations

from collections import Counter
import logging
import re

import nltk
import textstat

from AINDY.utils import enforce_word_limit, prepare_input_text

logger = logging.getLogger(__name__)
_TOKENIZER_AVAILABLE: bool | None = None


def _ensure_tokenizer() -> bool:
    global _TOKENIZER_AVAILABLE
    if _TOKENIZER_AVAILABLE is not None:
        return _TOKENIZER_AVAILABLE
    try:
        nltk.data.find("tokenizers/punkt")
        _TOKENIZER_AVAILABLE = True
    except LookupError:
        logger.warning("NLTK punkt tokenizer not available; using regex fallback for SEO tokenization")
        _TOKENIZER_AVAILABLE = False
    return _TOKENIZER_AVAILABLE


def _tokenize_words(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []
    if _ensure_tokenizer():
        try:
            return list(nltk.word_tokenize(normalized))
        except LookupError:
            logger.warning("NLTK tokenizer lookup failed at runtime; falling back to regex tokenization")
        except Exception as exc:
            logger.warning("NLTK tokenization failed; falling back to regex tokenization: %s", exc)
    return re.findall(r"\b\w+\b", normalized)


def extract_keywords(text: str, top_n: int = 10):
    words = _tokenize_words(text.lower())
    words = [word for word in words if word.isalnum()]
    freq_dist = Counter(words)
    return freq_dist.most_common(top_n)


def keyword_density(text: str, keyword: str):
    words = [word for word in _tokenize_words(text.lower()) if word.isalnum()]
    if not words:
        return 0.0
    return round((words.count(keyword.lower()) / len(words)) * 100, 2)


# Thresholds for SEO improvement suggestions (Search v4 §3.1).
_MIN_WORD_COUNT = 300           # thin-content floor
_READABILITY_HARD = 30.0        # Flesch reading ease below this = very hard to read
_READABILITY_DIFFICULT = 50.0   # below this = fairly difficult
_KEYWORD_STUFFING_PCT = 4.0     # single-keyword density above this = stuffing risk
_WEAK_FOCUS_PCT = 0.5           # top keyword density below this = weak topical focus


def seo_improvement_suggestions(analysis: dict) -> list[dict]:
    """Actionable SEO improvement suggestions derived from a ``seo_analysis`` result.

    Deterministic heuristics over the computed metrics (no LLM, no network). Each
    item: ``{metric, issue, suggestion, severity}`` (severity: "warn" | "info").
    Returns a single "healthy" info item when nothing is flagged.
    """
    suggestions: list[dict] = []
    word_count = int(analysis.get("word_count") or 0)
    readability = analysis.get("readability")
    densities = analysis.get("keyword_densities") or {}
    top_keywords = analysis.get("top_keywords") or []

    if word_count < _MIN_WORD_COUNT:
        suggestions.append({
            "metric": "word_count",
            "issue": f"Thin content ({word_count} words).",
            "suggestion": f"Expand to at least {_MIN_WORD_COUNT} words — thin pages rank poorly.",
            "severity": "warn",
        })

    if isinstance(readability, (int, float)):
        if readability < _READABILITY_HARD:
            suggestions.append({
                "metric": "readability",
                "issue": f"Very hard to read (Flesch {round(readability, 1)}).",
                "suggestion": "Shorten sentences and simplify wording to lift readability.",
                "severity": "warn",
            })
        elif readability < _READABILITY_DIFFICULT:
            suggestions.append({
                "metric": "readability",
                "issue": f"Fairly difficult to read (Flesch {round(readability, 1)}).",
                "suggestion": "Consider simpler phrasing for a broader audience.",
                "severity": "info",
            })

    for keyword, density in densities.items():
        if isinstance(density, (int, float)) and density > _KEYWORD_STUFFING_PCT:
            suggestions.append({
                "metric": "keyword_density",
                "issue": f"'{keyword}' density is {density}%.",
                "suggestion": f"Reduce use of '{keyword}' — over {_KEYWORD_STUFFING_PCT}% risks keyword-stuffing penalties.",
                "severity": "warn",
            })

    if not top_keywords:
        suggestions.append({
            "metric": "keywords",
            "issue": "No substantive keywords detected.",
            "suggestion": "Add keyword-rich, topical content so search engines can classify the page.",
            "severity": "warn",
        })
    elif densities:
        max_density = max((d for d in densities.values() if isinstance(d, (int, float))), default=0.0)
        if max_density < _WEAK_FOCUS_PCT:
            suggestions.append({
                "metric": "keyword_focus",
                "issue": f"Weak primary-keyword focus (top density {max_density}%).",
                "suggestion": "Reinforce your main keyword so search engines can identify the topic.",
                "severity": "info",
            })

    if not suggestions:
        suggestions.append({
            "metric": "overall",
            "issue": "No issues detected.",
            "suggestion": "SEO signals look healthy — keep content fresh and on-topic.",
            "severity": "info",
        })
    return suggestions


def seo_analysis(text: str, top_n: int = 10):
    """Performs a basic SEO analysis on given text, with improvement suggestions."""
    prepared_text = prepare_input_text(text)
    words = _tokenize_words(prepared_text)
    word_count = len(words)
    readability = textstat.flesch_reading_ease(prepared_text)
    keywords = extract_keywords(prepared_text, top_n)
    densities = {kw[0]: keyword_density(prepared_text, kw[0]) for kw in keywords}
    result = {
        "word_count": word_count,
        "readability": readability,
        "top_keywords": [kw[0] for kw in keywords],
        "keyword_densities": densities,
    }
    result["suggestions"] = seo_improvement_suggestions(result)
    return result


def generate_meta_description(text: str, limit: int = 160):
    """Generate a concise meta description using text constraints and sentence-safe trimming."""
    description = enforce_word_limit(text, limit, mode="soft", sentence_safe=True)
    return description.strip()

