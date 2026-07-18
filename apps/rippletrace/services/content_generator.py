"""
RippleTrace content generation.

Post drafts are authored by an LLM when one is reachable, falling back to a
deterministic template otherwise. The port had dropped the LLM path and shipped
template-only copy (`generate_variations` merely appended "(1)/(2)/(3)"); this
restores model-authored drafts through the runtime LLM abstraction
(`perform_external_call` + `chat_completion`, as search/ARM use) while keeping the
template as the offline/deterministic fallback.

Every response carries a ``source`` field ("llm" | "template") so callers can tell
model output from the fallback. Generation is skipped (template only) under
``settings.is_testing`` so app-profile / CI runs stay offline and deterministic; any
LLM error also falls back to the template.
"""
import json
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from apps.rippletrace.models import PlaybookDB, StrategyDB
from apps.rippletrace.services.playbook_engine import match_playbooks


def _safe_list(value):
    return value if isinstance(value, list) else []


def _build_title(strategy: StrategyDB, themes: List[str]) -> str:
    topic = themes[0].title() if themes else "Narrative"
    tone = strategy.name if strategy else "Strategic Insight"
    return f"Why {topic} Thinking Is the Real Advantage in {tone}"


def _build_hook(themes: List[str]) -> str:
    topic = themes[0] if themes else "this approach"
    return f"Most people are treating {topic} like a checkbox—and it’s costing them leverage."


def _build_body(steps: List[str], platform: str) -> str:
    paragraphs = []
    for step in steps:
        paragraphs.append(f"{step}.")
    if platform.lower() == "linkedin":
        return "\n\n".join(paragraphs)
    return " ".join(paragraphs)


def _build_cta() -> str:
    return "What’s your experience with this approach? Share below."


def _platform_format(platform: str) -> str:
    platform = (platform or "general").lower()
    if platform == "linkedin":
        return "short-paragraphs / conversational / spaced"
    if platform == "medium":
        return "long-form / structured / narrative"
    return "flexible / general purpose"


# ── LLM path (runtime abstraction; template is the fallback) ──────────────────

def _llm_enabled() -> bool:
    """Best-effort LLM: off under tests (deterministic app-profile/CI runs)."""
    try:
        from AINDY.config import settings

        return not bool(getattr(settings, "is_testing", False))
    except Exception:
        return False


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text.startswith("{"):
        import re

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
    return json.loads(text)


def _parse_json_array(text: str) -> list:
    text = (text or "").strip()
    if not text.startswith("["):
        import re

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            text = match.group(0)
    return json.loads(text)


def _chat(system_prompt: str, user_prompt: str, *, purpose: str, extra: dict | None = None) -> str:
    from AINDY.config import settings
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

    completion = perform_external_call(
        service_name="openai",
        endpoint="chat.completions.create",
        model="gpt-4o-mini",
        method="openai.chat",
        extra={"purpose": purpose, **(extra or {})},
        operation=lambda: chat_completion(
            get_openai_client(),
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
        ),
    )
    return completion.choices[0].message.content or ""


def _llm_generate_content(tone: str, themes: List[str], steps: List[str], platform: str) -> Dict:
    fmt = _platform_format(platform)
    system_prompt = (
        "You are a content strategist who writes sharp, specific, non-generic social "
        "posts. Return ONLY a JSON object with keys: title, hook, body, cta."
    )
    user_prompt = (
        f"Platform: {platform} — format: {fmt}.\n"
        f"Angle/tone: {tone}.\n"
        f"Themes: {', '.join(themes) if themes else 'general'}.\n"
        f"Playbook steps to weave into the body: {steps}.\n"
        "Write one post: a scroll-stopping title, a one-line hook, a body that develops "
        "the steps into a narrative in the platform's format, and a short CTA."
    )
    parsed = _parse_json_object(_chat(system_prompt, user_prompt, purpose="rippletrace_content", extra={"platform": platform}))
    content = {
        "title": str(parsed.get("title") or "").strip(),
        "hook": str(parsed.get("hook") or "").strip(),
        "body": str(parsed.get("body") or "").strip(),
        "cta": str(parsed.get("cta") or "").strip(),
        "platform_format": fmt,
    }
    if not (content["title"] and content["body"]):
        raise ValueError("LLM content missing title/body")
    return content


def _llm_generate_variations(base_content: Dict, count: int) -> List[Dict]:
    fmt = base_content.get("platform_format", "general")
    system_prompt = (
        "You rewrite a social post into distinct variations — each a genuinely different "
        f"angle/hook, not a cosmetic tweak. Return ONLY a JSON array of exactly {count} "
        "objects, each with keys: title, hook, body, cta."
    )
    user_prompt = (
        "Base post:\n"
        f"Title: {base_content.get('title')}\n"
        f"Hook: {base_content.get('hook')}\n"
        f"Body: {base_content.get('body')}\n"
        f"CTA: {base_content.get('cta')}\n"
        f"Produce {count} distinct variations."
    )
    parsed = _parse_json_array(_chat(system_prompt, user_prompt, purpose="rippletrace_variations"))
    variations = []
    for item in parsed[:count]:
        if not isinstance(item, dict):
            continue
        variations.append(
            {
                "title": str(item.get("title") or "").strip(),
                "hook": str(item.get("hook") or "").strip(),
                "body": str(item.get("body") or "").strip(),
                "cta": str(item.get("cta") or "").strip(),
                "platform_format": fmt,
            }
        )
    if not variations:
        raise ValueError("no LLM variations parsed")
    return variations


# ── public API ────────────────────────────────────────────────────────────────

def generate_content(playbook_id: str, db: Session) -> Dict:
    playbook = db.query(PlaybookDB).filter(PlaybookDB.id == playbook_id).first()
    if not playbook:
        return {
            "status": "playbook_not_found",
            "source": "template",
            "content": {
                "title": "Strategy in Progress",
                "hook": "We are shaping new narratives.",
                "body": "Stay tuned for the next wave of storytelling.",
                "cta": "What would you like to explore?",
                "platform_format": "general",
            },
        }

    strategy = db.query(StrategyDB).filter(StrategyDB.id == playbook.strategy_id).first()
    conditions = {}
    try:
        conditions = json.loads(strategy.conditions) if strategy and strategy.conditions else {}
    except Exception:
        conditions = {}

    themes = _safe_list(conditions.get("themes"))
    steps = json.loads(playbook.steps) if playbook.steps else []
    platform = conditions.get("platform") or "general"

    content = {
        "title": _build_title(strategy, themes),
        "hook": _build_hook(themes),
        "body": _build_body(steps, platform),
        "cta": _build_cta(),
        "platform_format": _platform_format(platform),
    }
    source = "template"

    if _llm_enabled():
        tone = strategy.name if strategy else "Strategic Insight"
        try:
            content = _llm_generate_content(tone, themes, steps, platform)
            source = "llm"
        except Exception:
            source = "template"  # any LLM error -> deterministic template

    return {
        "playbook_id": playbook_id,
        "content": content,
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_content_for_drop(drop_point_id: str, db: Session) -> Dict:
    matches = match_playbooks(drop_point_id, db)
    if not matches:
        return {
            "status": "no_playbook_match",
            "content": None,
        }
    playbook_id = matches[0]["playbook_id"]
    return generate_content(playbook_id, db)


def generate_variations(playbook_id: str, db: Session, count: int = 3) -> Dict:
    base = generate_content(playbook_id, db)
    if base.get("status"):
        return base

    # Genuinely different variants when the base was model-authored.
    if base.get("source") == "llm" and _llm_enabled():
        try:
            variations = _llm_generate_variations(base["content"], count)
            return {
                "playbook_id": playbook_id,
                "variations": variations,
                "source": "llm",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            pass  # fall through to the template variations

    variations = []
    for idx in range(count):
        variations.append(
            {
                "title": f"{base['content']['title']} ({idx + 1})",
                "hook": base["content"]["hook"],
                "body": base["content"]["body"],
                "cta": f"{base['content']['cta']} ({idx + 1})",
                "platform_format": base["content"]["platform_format"],
            }
        )
    return {
        "playbook_id": playbook_id,
        "variations": variations,
        "source": "template",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
