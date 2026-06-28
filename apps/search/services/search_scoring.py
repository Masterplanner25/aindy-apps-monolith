from __future__ import annotations

import re
from typing import Optional

# Small stop-word set so common glue words don't inflate query/result overlap.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
        "is", "are", "be", "by", "at", "as", "it", "this", "that", "from",
        "we", "our", "your", "their", "you", "they",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens, dropping stop-words and single chars."""
    return [
        tok
        for tok in _TOKEN_RE.findall((text or "").lower())
        if len(tok) >= 2 and tok not in _STOPWORDS
    ]


def lexical_relevance(query: str, text: str) -> float:
    """Query↔text relevance on 0..1 from token overlap + term frequency.

    Combines *coverage* (how many distinct query terms appear in the text) with
    a saturating *term-frequency* signal (how densely they appear). Pure Python,
    deterministic — no external models. Returns 0.0 when there is no overlap.
    """
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    doc_tokens = tokenize(text)
    if not doc_tokens:
        return 0.0
    overlap = query_tokens.intersection(doc_tokens)
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(query_tokens)
    hits = sum(1 for tok in doc_tokens if tok in query_tokens)
    tf = min(1.0, (hits / len(doc_tokens)) * 3.0)
    return _clamp01(0.7 * coverage + 0.3 * tf)


def composite_score(
    relevance: float,
    quality: Optional[float],
    *,
    relevance_weight: float = 0.6,
) -> float:
    """Blend query relevance with a surface quality score onto 0..1.

    ``relevance_weight`` controls how much the shared relevance signal dominates
    the surface-specific quality score (leadgen fit, research depth, SEO health).
    """
    rel = _clamp01(relevance)
    qual = _clamp01(quality or 0.0)
    return _clamp01(relevance_weight * rel + (1.0 - relevance_weight) * qual)


def score_lead_result(
    *,
    overall_score: Optional[float] = None,
    fit_score: Optional[float] = None,
    intent_score: Optional[float] = None,
    data_quality_score: Optional[float] = None,
) -> float:
    if overall_score is not None:
        return _clamp01(overall_score / 100.0)
    parts = [s for s in (fit_score, intent_score, data_quality_score) if s is not None]
    if not parts:
        return 0.0
    return _clamp01(sum(parts) / (len(parts) * 100.0))


def score_research_result(
    *,
    summary: str,
    memory_context_count: int = 0,
) -> float:
    length_factor = _clamp01(len(summary or "") / 500.0)
    memory_factor = _clamp01(memory_context_count / 5.0)
    return _clamp01(0.7 * length_factor + 0.3 * memory_factor)


def score_seo_result(
    *,
    readability: float,
    avg_keyword_density: float,
    word_count: int,
) -> float:
    readability_score = _clamp01(readability / 100.0)
    density_score = _clamp01(1.0 - (abs(avg_keyword_density - 2.0) / 2.0))
    length_score = _clamp01(word_count / 1000.0)
    return _clamp01(0.7 * readability_score + 0.2 * density_score + 0.1 * length_score)

