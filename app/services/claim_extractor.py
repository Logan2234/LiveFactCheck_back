import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MIN_WORDS = 3
VALID_STATUSES = {"verified", "false", "uncertain", "unverifiable"}


def _log_usage(label: str, usage) -> None:
    """Log token usage so cache hits/misses are observable (prefix is small)."""
    logger.info(
        "%s: in=%s cache_write=%s cache_read=%s out=%s",
        label,
        usage.input_tokens,
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
        usage.output_tokens,
    )

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 2,
}

CLAIM_TOOL: anthropic.types.ToolParam = {
    "name": "submit_claims",
    "description": "Soumet les affirmations factuelles extraites et vérifiées.",
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": list(VALID_STATUSES),
                        },
                        "explanation": {"type": "string"},
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "URLs des sources (si recherche web)",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "politique",
                                "économie",
                                "science",
                                "santé",
                                "histoire",
                                "sport",
                                "société",
                                "technologie",
                                "culture",
                                "autre",
                            ],
                        },
                        "confidence": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 10,
                            "description": "Confiance de 0 (très incertain) à 10 (certain)",
                        },
                        "counter_claim": {
                            "type": "string",
                            "description": "Si le claim est faux : la réalité correcte. Vide sinon.",
                        },
                        "web_search_used": {
                            "type": "boolean",
                            "description": "True si une recherche web a été utilisée pour vérifier ce claim",
                        },
                    },
                    "required": [
                        "text",
                        "status",
                        "explanation",
                        "sources",
                        "category",
                        "confidence",
                        "counter_claim",
                        "web_search_used",
                    ],
                },
            }
        },
        "required": ["claims"],
    },
}

SYSTEM_PROMPT = """Tu es un fact-checker francophone expert.

Extraction : n'extrais QUE les faits vérifiables (chiffres, dates, statistiques, événements, déclarations attribuées). Ignore les opinions et déclarations personnelles. Si un fait peut être vérifié mais tu n'as pas assez d'infos pour le faire de façon fiable, classe-le comme "uncertain" et explique pourquoi. Si aucun fait vérifiable, liste vide.

Vérification — par défaut, vérifie avec tes connaissances internes SANS recherche web. N'utilise web_search QUE si le fait dépend d'informations récentes ou changeantes que tu ne peux pas connaître de façon fiable (actualité, événements récents, chiffres ou statuts qui évoluent, déclarations très récentes).
N'utilise JAMAIS web_search pour des faits établis et immuables (dates historiques, mesures physiques, géographie, faits scientifiques connus) : tu les connais déjà.
Quand tu as effectué une recherche, mets les URLs dans "sources".

Remplis confidence (0-10) et, pour un claim "false", counter_claim. Termine par submit_claims."""



def _parse_claims(claims_raw: list) -> list[dict]:
    return [
        {
            "text": r["text"],
            "status": r["status"] if r.get("status") in VALID_STATUSES else "uncertain",
            "explanation": r.get("explanation", ""),
            "sources": r.get("sources") or [],
            "category": r.get("category", "autre"),
            "confidence": max(0, min(10, int(r["confidence"])))
            if isinstance(r.get("confidence"), (int, float))
            else 0,
            "counter_claim": r.get("counter_claim", ""),
            "web_search_used": r.get("web_search_used", False) is True,
        }
        for r in claims_raw
        if isinstance(r, dict) and "text" in r
    ]


async def extract_and_verify(text: str, web_search: bool = True) -> list[dict]:
    if len(text.split()) < MIN_WORDS:
        return []

    # Dropping the web_search tool entirely is more reliable than a prompt
    # instruction: Claude physically cannot search when it isn't offered.
    tools = [WEB_SEARCH_TOOL, CLAIM_TOOL] if web_search else [CLAIM_TOOL]

    messages: list[dict] = [
        {"role": "user", "content": f"Analyse ce texte :\n\n{text}"}
    ]

    response = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=tools,
        tool_choice={"type": "auto"},
    )
    _log_usage("extract", response.usage)

    # Happy path: submit_claims present in first response (with or without prior web_search)
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_claims":
            return _parse_claims(block.input.get("claims", []))

    # Fallback: Claude did web searches but didn't call submit_claims yet
    # Continue the conversation and force the structured output
    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": "Utilise maintenant submit_claims pour structurer les claims identifiés.",
            }
        )
        response2 = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[WEB_SEARCH_TOOL, CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "submit_claims"},
        )
        _log_usage("extract-fallback", response2.usage)
        for block in response2.content:
            if block.type == "tool_use" and block.name == "submit_claims":
                return _parse_claims(block.input.get("claims", []))

    return []


async def debug_extract(text: str, web_search: bool = True) -> dict:
    """Like extract_and_verify but also returns token usage and turn count."""
    if len(text.split()) < MIN_WORDS:
        return {"claims": [], "turns": 0, "usage": {}, "model": settings.ANTHROPIC_MODEL,
                "web_search_enabled": web_search, "web_search_called": False}

    tools = [WEB_SEARCH_TOOL, CLAIM_TOOL] if web_search else [CLAIM_TOOL]
    messages: list[dict] = [{"role": "user", "content": f"Analyse ce texte :\n\n{text}"}]

    response = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=tools,
        tool_choice={"type": "auto"},
    )
    _log_usage("debug-extract", response.usage)

    web_search_called = any(
        getattr(b, "type", None) == "tool_use" and b.name == "web_search"
        for b in response.content
    )
    total_usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0),
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
    }

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_claims":
            return {
                "claims": _parse_claims(block.input.get("claims", [])),
                "turns": 1,
                "usage": total_usage,
                "model": settings.ANTHROPIC_MODEL,
                "web_search_enabled": web_search,
                "web_search_called": web_search_called,
            }

    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": "Utilise maintenant submit_claims pour structurer les claims identifiés."})
        response2 = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[WEB_SEARCH_TOOL, CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "submit_claims"},
        )
        _log_usage("debug-extract-fallback", response2.usage)
        total_usage["input_tokens"] += response2.usage.input_tokens
        total_usage["output_tokens"] += response2.usage.output_tokens
        total_usage["cache_write"] += getattr(response2.usage, "cache_creation_input_tokens", 0)
        total_usage["cache_read"] += getattr(response2.usage, "cache_read_input_tokens", 0)
        for block in response2.content:
            if block.type == "tool_use" and block.name == "submit_claims":
                return {
                    "claims": _parse_claims(block.input.get("claims", [])),
                    "turns": 2,
                    "usage": total_usage,
                    "model": settings.ANTHROPIC_MODEL,
                    "web_search_enabled": web_search,
                    "web_search_called": web_search_called,
                }

    return {
        "claims": [],
        "turns": 1,
        "usage": total_usage,
        "model": settings.ANTHROPIC_MODEL,
        "web_search_enabled": web_search,
        "web_search_called": web_search_called,
    }
