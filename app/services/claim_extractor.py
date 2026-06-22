import logging
from typing import Any, cast

import anthropic
from anthropic.types import (
    Message,
    MessageParam,
    ToolParam,
    ToolUnionParam,
    Usage,
    WebSearchTool20250305Param,
)

from app.config import settings

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MIN_WORDS = 3
VALID_STATUSES = {"verified", "false", "uncertain", "unverifiable"}


def _log_usage(label: str, usage: Usage) -> None:
    """Log token usage so cache hits/misses are observable (prefix is small)."""
    logger.info(
        "%s: in=%s cache_write=%s cache_read=%s out=%s",
        label,
        usage.input_tokens,
        usage.cache_creation_input_tokens or 0,
        usage.cache_read_input_tokens or 0,
        usage.output_tokens,
    )


WEB_SEARCH_TOOL: WebSearchTool20250305Param = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 2,
}

CLAIM_TOOL: ToolParam = {
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
                            "description": (
                                "Confiance de 0 (très incertain) à 10 (certain)"
                            ),
                        },
                        "counter_claim": {
                            "type": "string",
                            "description": (
                                "Si le claim est faux : la réalité correcte. "
                                "Vide sinon."
                            ),
                        },
                        "web_search_used": {
                            "type": "boolean",
                            "description": (
                                "True si une recherche web a été utilisée "
                                "pour vérifier ce claim"
                            ),
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

SYSTEM_PROMPT = (
    "Tu es un fact-checker francophone expert.\n"
    "\n"
    "Extraction — distingue les cas :\n"
    "- Faits vérifiables (chiffres, dates, statistiques, événements passés, "
    "déclarations attribuées) : extrais-les et vérifie-les.\n"
    "- Énoncés à teneur factuelle mais invérifiables par nature (prédictions sur "
    "le futur, événements pas encore survenus, affirmations qu'on ne peut ni "
    'confirmer ni infirmer) : extrais-les avec le statut "unverifiable" et '
    "explique pourquoi (ex. : prédiction sur un résultat futur). Ne les supprime "
    "pas.\n"
    "- Pures opinions, jugements de valeur ou déclarations personnelles "
    '("je suis beau", "ce film est génial") : ignore-les, ne les extrais pas.\n'
    "Si un fait est vérifiable en principe mais que tu n'as pas assez d'infos "
    'pour trancher de façon fiable, classe-le "uncertain" et explique pourquoi. '
    "Si rien à extraire, liste vide.\n"
    "\n"
    "Vérification — par défaut, vérifie avec tes connaissances internes SANS "
    "recherche web. N'utilise web_search QUE si le fait dépend d'informations "
    "récentes ou changeantes que tu ne peux pas connaître de façon fiable "
    "(actualité, événements récents, chiffres ou statuts qui évoluent, "
    "déclarations très récentes).\n"
    "N'utilise JAMAIS web_search pour des faits établis et immuables (dates "
    "historiques, mesures physiques, géographie, faits scientifiques connus) : "
    "tu les connais déjà.\n"
    'Quand tu as effectué une recherche, mets les URLs dans "sources".\n'
    "\n"
    'Remplis confidence (0-10) et, pour un claim "false", counter_claim. '
    "Termine par submit_claims."
)


def _parse_claims(claims_raw: list[Any]) -> list[dict[str, Any]]:
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


def _claims_from_response(response: Message) -> list[dict[str, Any]] | None:
    """Return parsed claims if the response contains a submit_claims tool call.

    ``None`` means the model hasn't called submit_claims yet (e.g. it only
    web-searched), which is what triggers the forced second turn.
    """
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_claims":
            tool_input = cast(dict[str, Any], block.input)
            return _parse_claims(tool_input.get("claims", []))
    return None


def _build_tools(web_search: bool) -> list[ToolUnionParam]:
    # Dropping the web_search tool entirely is more reliable than a prompt
    # instruction: Claude physically cannot search when it isn't offered.
    if web_search:
        return [WEB_SEARCH_TOOL, CLAIM_TOOL]
    return [CLAIM_TOOL]


def _usage_dict(usage: Usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_write": usage.cache_creation_input_tokens or 0,
        "cache_read": usage.cache_read_input_tokens or 0,
    }


def _web_search_called(response: Message) -> bool:
    return any(
        block.type == "server_tool_use" and block.name == "web_search"
        for block in response.content
    )


async def extract_and_verify(
    text: str, web_search: bool = True
) -> list[dict[str, Any]]:
    if len(text.split()) < MIN_WORDS:
        return []

    messages: list[MessageParam] = [
        {"role": "user", "content": f"Analyse ce texte :\n\n{text}"}
    ]

    response = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=_build_tools(web_search),
        tool_choice={"type": "auto"},
    )
    _log_usage("extract", response.usage)

    # Happy path: submit_claims present in first response
    # (with or without prior web_search)
    claims = _claims_from_response(response)
    if claims is not None:
        return claims

    # Fallback: Claude did web searches but didn't call submit_claims yet.
    # Continue the conversation and force the structured output.
    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Utilise maintenant submit_claims pour structurer "
                    "les claims identifiés."
                ),
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
        claims = _claims_from_response(response2)
        if claims is not None:
            return claims

    return []


async def debug_extract(text: str, web_search: bool = True) -> dict[str, Any]:
    """Like extract_and_verify but also returns token usage and turn count."""

    def result(
        claims: list[dict[str, Any]],
        turns: int,
        usage: dict[str, int],
        web_search_called: bool,
    ) -> dict[str, Any]:
        return {
            "claims": claims,
            "turns": turns,
            "usage": usage,
            "model": settings.ANTHROPIC_MODEL,
            "web_search_enabled": web_search,
            "web_search_called": web_search_called,
        }

    if len(text.split()) < MIN_WORDS:
        return result([], 0, {}, False)

    messages: list[MessageParam] = [
        {"role": "user", "content": f"Analyse ce texte :\n\n{text}"}
    ]

    response = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=_build_tools(web_search),
        tool_choice={"type": "auto"},
    )
    _log_usage("debug-extract", response.usage)

    web_search_called = _web_search_called(response)
    total_usage = _usage_dict(response.usage)

    claims = _claims_from_response(response)
    if claims is not None:
        return result(claims, 1, total_usage, web_search_called)

    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Utilise maintenant submit_claims pour structurer "
                    "les claims identifiés."
                ),
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
        _log_usage("debug-extract-fallback", response2.usage)
        for key, value in _usage_dict(response2.usage).items():
            total_usage[key] += value
        claims = _claims_from_response(response2)
        if claims is not None:
            return result(claims, 2, total_usage, web_search_called)

    return result([], 1, total_usage, web_search_called)
