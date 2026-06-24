import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
from anthropic.types import (
    Message,
    MessageParam,
    TextBlockParam,
    ToolChoiceParam,
    ToolParam,
    ToolUnionParam,
    Usage,
    WebSearchTool20250305Param,
)

from app.config import settings
from app.services.normalize import normalize

logger: logging.Logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MIN_WORDS = 3
VALID_STATUSES: set[str] = {"verified", "false", "uncertain", "unverifiable"}

# Output cap per extraction call. Headroom for several claims with explanations and
# counter_claims; a hit on it (stop_reason "max_tokens") truncates the tool JSON and
# is logged.
MAX_TOKENS = 2048

# Process-level LRU cache of verification results, keyed by the normalized
# utterance text. Bounded by settings.VERIFICATION_CACHE_SIZE (0 = disabled).
# Shared across sessions, so a repeated utterance reuses its result regardless of
# which connection produced it first. Only no-web_search results are stored (see
# extract_and_verify) so we never serve a stale web-sourced fact.
_verification_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    if settings.VERIFICATION_CACHE_SIZE <= 0:
        return None
    claims: list[dict[str, Any]] | None = _verification_cache.get(key)
    if claims is None:
        return None
    _verification_cache.move_to_end(key)  # mark as most-recently used
    return claims


def _cache_put(key: str, claims: list[dict[str, Any]]) -> None:
    size: int = settings.VERIFICATION_CACHE_SIZE
    if size <= 0:
        return
    _verification_cache[key] = claims
    _verification_cache.move_to_end(key)
    while len(_verification_cache) > size:
        _verification_cache.popitem(last=False)  # evict least-recently used


@dataclass
class ExtractResult:
    """Outcome of one extraction pass: the claims plus the call's measurements.

    ``usage`` keys mirror :func:`_usage_dict` (input/output/cache_read/cache_write);
    ``api_calls`` is 1, or 2 when the two-turn fallback fired; ``web_search_calls``
    counts the server-side web_search invocations across all turns.
    """

    claims: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)
    api_calls: int = 0
    web_search_calls: int = 0


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
                            # Sorted, not list(set): a set's iteration order varies
                            # between processes (hash randomization), which would make
                            # the tool schema non-deterministic and defeat caching.
                            "enum": sorted(VALID_STATUSES),
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
    "Contexte — le message peut contenir un bloc « Contexte précédent » suivi "
    "d'un « Texte à analyser ». N'extrais et ne vérifie QUE les affirmations du "
    "« Texte à analyser » ; le contexte sert uniquement à lever les références "
    "(« de même », « idem », « donc », pronoms, sujets implicites). Reformule le "
    "champ text de chaque claim pour qu'il soit autosuffisant et compréhensible "
    "sans le contexte. RÈGLE CRITIQUE : reformule toujours l'affirmation telle que "
    "le locuteur la pose, en préservant sa polarité (affirmation ou négation). "
    "Ex. positif : contexte « 1 + 1 = 2 », texte « Il en est de même de 1*2 » "
    "→ text = « 1 * 2 = 2 » (verified). "
    "Ex. négatif : contexte « 1 + 1 = 2 », texte « Ce n'est pas le cas pour 4+4 » "
    "→ text = « 4 + 4 != 2 » (verified, car le locuteur a raison). "
    "Ex. faux : texte « Napoléon a gagné à Waterloo » → text = « Napoléon a gagné "
    "la bataille de Waterloo » (status false, counter_claim « Napoléon a perdu la "
    "bataille de Waterloo en 1815 »). Le locuteur peut se tromper : ton rôle est de "
    "vérifier son affirmation, jamais de lui donner raison par défaut.\n"
    "Ne jamais extraire le fait sous-jacent nié comme si le locuteur l'affirmait.\n"
    "\n"
    "Vérification — par défaut, vérifie avec tes connaissances internes SANS "
    "recherche web. N'utilise web_search QUE si le fait dépend d'informations "
    "récentes ou changeantes que tu ne peux pas connaître de façon fiable "
    "(actualité, événements récents, chiffres ou statuts qui évoluent, "
    "déclarations très récentes).\n"
    "N'utilise JAMAIS web_search pour des faits établis et immuables (dates "
    "historiques, mesures physiques, géographie, faits scientifiques connus) : "
    "tu les connais déjà.\n"
    "Fiabilité des sources — une source web unique ne prouve rien. Recoupe "
    "plusieurs sources indépendantes et reconnues avant de classer « verified », "
    "et juge l'autorité de la source : un domaine inconnu, militant ou "
    "promotionnel n'est pas une preuve. Si une recherche contredit ce que tu sais "
    "de façon fiable, c'est presque toujours la source qui a tort : ne renie pas "
    "une connaissance solide pour un résultat web douteux — classe « false » "
    "d'après ta connaissance, ou « uncertain » si un doute subsiste, plutôt que de "
    "confirmer une source peu fiable.\n"
    'Quand tu as effectué une recherche, mets les URLs dans "sources".\n'
    "\n"
    'Remplis confidence (0-10) et, pour un claim "false", counter_claim. '
    "Réserve 8-10 aux faits solidement établis ; plafonne à 5 ou moins quand tu "
    "t'appuies sur une source web unique ou de faible autorité.\n"
    "Termine par submit_claims."
)

# Cache breakpoint on the system block, so tools + system are cached together
# (render order is tools → system → messages — a breakpoint on the tool would cache
# only the tools, not this larger prompt). Below the model's minimum cacheable prefix
# (Haiku 4.5: 4096 tokens) it's a silent no-op; check cache_read/cache_write in the
# _log_usage output to confirm whether it engages.
_SYSTEM: list[TextBlockParam] = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]


def _build_analysis_prompt(text: str, context: list[str] | None) -> str:
    """Build the user message, prepending recent utterances as read-only context.

    Without context the model sees the utterance alone and can't resolve a
    back-reference ("Il en est de même de…"). We label the two blocks so the
    system prompt can tell the model to extract only from the current text.
    """
    if not context:
        return f"Analyse ce texte :\n\n{text}"
    preceding: str = "\n".join(context)
    return (
        "Contexte précédent (pour comprendre les références ; "
        "n'en extrais AUCUN claim) :\n\n"
        f"{preceding}\n\n"
        f"Texte à analyser :\n\n{text}"
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
            tool_input: dict[str, Any] = cast(dict[str, Any], block.input)
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


def _add_usage(total: dict[str, int], usage: Usage) -> None:
    """Accumulate one response's usage into a running per-call total."""
    for key, value in _usage_dict(usage).items():
        total[key] = total.get(key, 0) + value


def _count_web_search(response: Message) -> int:
    return sum(
        block.type == "server_tool_use" and block.name == "web_search"
        for block in response.content
    )


_FORCE_SUBMIT_MSG = (
    "Utilise maintenant submit_claims pour structurer les claims identifiés."
)


async def extract_and_verify(
    text: str, context: list[str] | None = None, web_search: bool = True
) -> ExtractResult:
    """Extract and verify claims, returning the claims plus the call's measurements.

    The measurements (token usage, number of API calls, web_search count) are what
    the persistence layer records on the transcript segment; callers that only need
    the claims read ``result.claims``.
    """
    if len(text.split()) < MIN_WORDS:
        return ExtractResult(claims=[])

    # A cache hit short-circuits the API call entirely: usage/api_calls stay at 0,
    # which the persistence layer correctly records as "no call for this segment".
    cache_key: str = normalize(text)
    cached: list[dict[str, Any]] | None = _cache_get(cache_key)
    if cached is not None:
        logger.info("Verification cache hit")
        return ExtractResult(claims=cached)

    messages: list[MessageParam] = [
        {"role": "user", "content": _build_analysis_prompt(text, context)}
    ]
    usage_total: dict[str, int] = {}
    web_search_calls = 0
    api_calls = 0

    # Fast path (no web_search) offers only submit_claims, so force it: one call,
    # guaranteed structured output, no reliance on the two-turn fallback, and no silent
    # drop if the model were to answer in plain text. Thorough keeps "auto" so the
    # model can web_search first.
    first_tool_choice: ToolChoiceParam = (
        {"type": "auto"} if web_search else {"type": "tool", "name": "submit_claims"}
    )
    response: Message = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=messages,
        tools=_build_tools(web_search),
        tool_choice=first_tool_choice,
    )
    api_calls += 1
    _log_usage("extract", response.usage)
    _add_usage(usage_total, response.usage)
    web_search_calls += _count_web_search(response)
    if response.stop_reason == "max_tokens":
        logger.warning(
            "Extraction hit max_tokens (%d); output may be truncated", MAX_TOKENS
        )

    # Happy path: submit_claims present in the first response (with or without a
    # prior web_search). Otherwise, if Claude searched but stopped before calling
    # submit_claims, continue the conversation and force the structured output.
    claims: list[dict[str, Any]] | None = _claims_from_response(response)
    if claims is None and response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": _FORCE_SUBMIT_MSG})
        response2: Message = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            messages=messages,
            tools=[WEB_SEARCH_TOOL, CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "submit_claims"},
        )
        api_calls += 1
        _log_usage("extract-fallback", response2.usage)
        _add_usage(usage_total, response2.usage)
        web_search_calls += _count_web_search(response2)
        if response2.stop_reason == "max_tokens":
            logger.warning(
                "Extraction fallback hit max_tokens (%d); output may be truncated",
                MAX_TOKENS,
            )
        claims: list[dict[str, Any]] | None = _claims_from_response(response2)

    final_claims: list[dict[str, Any]] = claims or []
    # Cache only when no web_search was used: those facts are immutable, so reusing
    # the result is safe; a web-sourced result could go stale. An empty result is
    # worth caching too (e.g. a repeated pure opinion) — it spares the same call.
    if web_search_calls == 0:
        _cache_put(cache_key, final_claims)

    return ExtractResult(
        claims=final_claims,
        usage=usage_total,
        api_calls=api_calls,
        web_search_calls=web_search_calls,
    )


async def debug_extract(
    text: str, context: list[str] | None = None, web_search: bool = True
) -> dict[str, Any]:
    """Shape ``extract_and_verify`` for the admin model-test panel."""
    result: ExtractResult = await extract_and_verify(
        text, context=context, web_search=web_search
    )
    return {
        "claims": result.claims,
        "turns": result.api_calls,
        "usage": result.usage,
        "model": settings.ANTHROPIC_MODEL,
        "web_search_enabled": web_search,
        "web_search_called": result.web_search_calls > 0,
    }
