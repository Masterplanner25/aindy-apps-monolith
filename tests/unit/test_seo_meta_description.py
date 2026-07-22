"""Meta descriptions must fit the SERP character budget, not a word budget.

Regression: ``generate_meta_description`` used ``enforce_word_limit``, a WORD limit — so the
default ``limit=160`` produced ~160 words (~900+ characters), far past Google's ~155–160
character truncation. SERP descriptions are measured in characters. These pin the character
budget, sentence-safe trimming, and short-text passthrough.
"""
from __future__ import annotations

import pytest

from apps.search.services.seo_services import generate_meta_description

pytestmark = pytest.mark.app_profile


def test_long_text_is_trimmed_to_the_character_budget():
    long_text = "Search engine optimization improves content visibility. " * 40
    result = generate_meta_description(long_text, 160)
    assert len(result) <= 160, f"meta description is {len(result)} chars, must be <= 160"
    assert len(result) > 40, "should not collapse to almost nothing"


def test_respects_a_custom_shorter_limit():
    long_text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa. " * 10
    result = generate_meta_description(long_text, 80)
    assert len(result) <= 80


def test_short_text_passes_through_unchanged():
    short = "A concise article about SEO best practices."
    assert generate_meta_description(short, 160) == short


def test_prefers_a_sentence_boundary_when_one_fits():
    # The second sentence ends past 60% of the 160-char budget, so trim there — cleanly, and
    # drop the sentence that would overflow rather than cutting it mid-word.
    text = (
        "SEO improves how content ranks in search results. "
        "Keyword density and readability both matter a great deal for ranking. "
        "This third sentence runs well past the budget and should be dropped entirely."
    )
    result = generate_meta_description(text, 160)
    assert result.endswith(".")
    assert len(result) <= 160
    assert "third sentence" not in result


def test_word_boundary_fallback_marks_truncation():
    # No sentence boundary within budget -> cut at a word boundary with an ellipsis.
    text = "word " * 200
    result = generate_meta_description(text, 60)
    assert len(result) <= 61  # 60 + the ellipsis char
    assert result.endswith("…")
    assert not result.endswith(" …")


def test_collapses_whitespace_and_newlines():
    text = "Line one.\n\n   Line two    with   spaces.\tTabbed."
    result = generate_meta_description(text, 160)
    assert "\n" not in result and "\t" not in result
    assert "  " not in result
