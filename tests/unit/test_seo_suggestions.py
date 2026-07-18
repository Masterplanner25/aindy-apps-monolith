"""
SEO improvement suggestions (Search v4 §3.1).

`seo_analysis` previously returned metrics but no actionable suggestions. Tests the
deterministic heuristics + that seo_analysis surfaces them. Hermetic.
"""
from __future__ import annotations

import pytest

from apps.search.services.seo_services import seo_analysis, seo_improvement_suggestions

pytestmark = pytest.mark.app_profile


def _metrics(word_count=500, readability=70.0, densities=None, top_keywords=("ai",)):
    return {
        "word_count": word_count,
        "readability": readability,
        "keyword_densities": densities if densities is not None else {"ai": 1.5},
        "top_keywords": list(top_keywords),
    }


def _by_metric(suggestions):
    return {s["metric"] for s in suggestions}


def test_healthy_analysis_returns_single_ok():
    out = seo_improvement_suggestions(_metrics())
    assert len(out) == 1
    assert out[0]["metric"] == "overall"
    assert out[0]["severity"] == "info"


def test_thin_content_flagged():
    out = seo_improvement_suggestions(_metrics(word_count=120))
    assert "word_count" in _by_metric(out)
    assert any(s["severity"] == "warn" and s["metric"] == "word_count" for s in out)


def test_hard_readability_flagged():
    out = seo_improvement_suggestions(_metrics(readability=20.0))
    assert any(s["metric"] == "readability" and s["severity"] == "warn" for s in out)


def test_difficult_readability_is_info():
    out = seo_improvement_suggestions(_metrics(readability=45.0))
    read = [s for s in out if s["metric"] == "readability"]
    assert read and read[0]["severity"] == "info"


def test_keyword_stuffing_flagged():
    out = seo_improvement_suggestions(_metrics(densities={"ai": 6.5}))
    stuffing = [s for s in out if s["metric"] == "keyword_density"]
    assert stuffing and "ai" in stuffing[0]["issue"]


def test_no_keywords_flagged():
    out = seo_improvement_suggestions(_metrics(top_keywords=(), densities={}))
    assert "keywords" in _by_metric(out)


def test_weak_focus_is_info():
    out = seo_improvement_suggestions(_metrics(densities={"ai": 0.2}))
    focus = [s for s in out if s["metric"] == "keyword_focus"]
    assert focus and focus[0]["severity"] == "info"


def test_seo_analysis_surfaces_suggestions():
    result = seo_analysis("AI systems help teams move faster. " * 5)
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list) and result["suggestions"]
    assert all({"metric", "issue", "suggestion", "severity"} <= set(s) for s in result["suggestions"])
