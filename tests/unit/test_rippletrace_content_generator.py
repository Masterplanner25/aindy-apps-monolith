"""
Unit tests for RippleTrace content generation (LLM path + template fallback).

The LLM call itself is never made in tests (hermetic): `_llm_enabled` / the LLM
helpers are monkeypatched to exercise each path deterministically.
"""
from __future__ import annotations

import json

import pytest

from apps.rippletrace.models import PlaybookDB, StrategyDB
from apps.rippletrace.services import content_generator as cg

pytestmark = pytest.mark.app_profile


def _seed(db, *, themes=("ai",), platform="linkedin", steps=("Do X", "Do Y")) -> str:
    db.add(StrategyDB(id="s1", name="Growth", conditions=json.dumps({"themes": list(themes), "platform": platform})))
    db.add(PlaybookDB(id="p1", strategy_id="s1", steps=json.dumps(list(steps))))
    db.commit()
    return "p1"


_FAKE = {"title": "T", "hook": "H", "body": "B", "cta": "C", "platform_format": "x"}


class TestGenerateContent:

    def test_template_when_llm_disabled(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: False)
        result = cg.generate_content(_seed(db_session), db_session)
        assert result["source"] == "template"
        assert result["content"]["title"] and result["content"]["body"]

    def test_llm_path_marks_source_llm(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: True)
        monkeypatch.setattr(cg, "_llm_generate_content", lambda tone, themes, steps, platform: dict(_FAKE))
        result = cg.generate_content(_seed(db_session), db_session)
        assert result["source"] == "llm"
        assert result["content"] == _FAKE

    def test_llm_failure_falls_back_to_template(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: True)

        def _boom(*args, **kwargs):
            raise RuntimeError("llm unavailable")

        monkeypatch.setattr(cg, "_llm_generate_content", _boom)
        result = cg.generate_content(_seed(db_session), db_session)
        assert result["source"] == "template"
        assert result["content"]["title"]

    def test_playbook_not_found(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: False)
        result = cg.generate_content("missing", db_session)
        assert result["status"] == "playbook_not_found"
        assert result["source"] == "template"


class TestGenerateVariations:

    def test_template_variations_when_disabled(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: False)
        result = cg.generate_variations(_seed(db_session), db_session, count=3)
        assert result["source"] == "template"
        assert len(result["variations"]) == 3

    def test_llm_variations_are_distinct(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: True)
        monkeypatch.setattr(cg, "_llm_generate_content", lambda tone, themes, steps, platform: dict(_FAKE))
        variants = [
            {"title": f"V{i}", "hook": "h", "body": "b", "cta": "c", "platform_format": "x"}
            for i in range(3)
        ]
        monkeypatch.setattr(cg, "_llm_generate_variations", lambda base, count: variants)
        result = cg.generate_variations(_seed(db_session), db_session, count=3)
        assert result["source"] == "llm"
        assert [v["title"] for v in result["variations"]] == ["V0", "V1", "V2"]

    def test_llm_variation_failure_falls_back(self, db_session, monkeypatch):
        monkeypatch.setattr(cg, "_llm_enabled", lambda: True)
        monkeypatch.setattr(cg, "_llm_generate_content", lambda tone, themes, steps, platform: dict(_FAKE))

        def _boom(*args, **kwargs):
            raise RuntimeError("llm unavailable")

        monkeypatch.setattr(cg, "_llm_generate_variations", _boom)
        result = cg.generate_variations(_seed(db_session), db_session, count=2)
        assert result["source"] == "template"
        assert len(result["variations"]) == 2


class TestParsers:

    def test_parse_json_object_strips_code_fence(self):
        assert cg._parse_json_object('```json\n{"a": 1}\n```')["a"] == 1

    def test_parse_json_array_extracts_from_prose(self):
        assert cg._parse_json_array('here: [ {"a": 1} ] done') == [{"a": 1}]
