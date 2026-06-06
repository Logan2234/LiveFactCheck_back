import anthropic

from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MIN_WORDS = 3

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 2,
}

CLAIM_TOOL: anthropic.types.ToolParam = {
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
                            "enum": ["verified", "false", "uncertain", "unverifiable"],
                        },
                        "explanation": {"type": "string"},
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "URLs des sources utilisées (si recherche web effectuée)",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["politique", "économie", "science", "santé", "histoire", "sport", "société", "technologie", "autre"],
                            "description": "Catégorie thématique du claim",
                        },
                        "confidence": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 10,
                            "description": "Score de confiance de la vérification de 0 (très incertain) à 10 (certitude absolue)",
                        },
                        "counter_claim": {
                            "type": "string",
                            "description": "Si le claim est faux, quelle est la réalité correcte ? Laisser vide sinon.",
                        },
                    },
                    "required": ["text", "status", "explanation", "sources", "category", "confidence", "counter_claim"],
                },
            }
        },
        "required": ["claims"],
    },
}

SYSTEM_PROMPT = """Tu es un fact-checker francophone expert.

Règles d'extraction :
- N'extrais QUE les faits objectivement vérifiables : chiffres, dates, statistiques, événements, déclarations attribuées à quelqu'un
- Ignore les opinions, jugements de valeur et déclarations personnelles (ex : "je m'appelle X", "je pense que")
- Maximum 3 claims par texte

Règles de vérification :
- Si une information est susceptible d'être récente, d'actualité, ou si tu n'es pas certain de sa véracité → utilise web_search pour chercher des sources à jour avant de conclure
- Inclus toujours les URLs des sources dans le champ "sources" quand tu as effectué une recherche web
- Si aucun fait vérifiable n'est présent dans le texte, retourne une liste vide

Pour chaque claim, remplis également :
- "category" : catégorie thématique parmi politique, économie, science, santé, histoire, sport, société, technologie, autre
- "confidence" : score de confiance de 0 à 10 (ex: 9 si tu as une source fiable, 5 si tu n'es pas sûr, 2 si c'est très incertain)
- "counter_claim" : si le claim est "false", explique en une phrase ce qui est réellement vrai. Laisse vide pour les autres statuts.

Termine toujours par l'outil submit_claims pour structurer ta réponse."""

VALID_STATUSES = {"verified", "false", "uncertain", "unverifiable"}


def _parse_claims(claims_raw: list) -> list[dict]:
    return [
        {
            "text": r["text"],
            "status": r["status"] if r.get("status") in VALID_STATUSES else "uncertain",
            "explanation": r.get("explanation", ""),
            "sources": r.get("sources") or [],
            "category": r.get("category", "autre"),
            "confidence": max(0, min(10, int(r["confidence"]))) if isinstance(r.get("confidence"), (int, float)) else 0,
            "counter_claim": r.get("counter_claim", ""),
        }
        for r in claims_raw
        if isinstance(r, dict) and "text" in r
    ]


async def extract_and_verify(text: str) -> list[dict]:
    if len(text.split()) < MIN_WORDS:
        return []

    messages: list[dict] = [{"role": "user", "content": f"Analyse ce texte :\n\n{text}"}]

    response = await _client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        tools=[WEB_SEARCH_TOOL, CLAIM_TOOL],
        tool_choice={"type": "auto"},
    )

    # Happy path: submit_claims present in first response (with or without prior web_search)
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_claims":
            return _parse_claims(block.input.get("claims", []))

    # Fallback: Claude did web searches but didn't call submit_claims yet
    # Continue the conversation and force the structured output
    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": "Utilise maintenant submit_claims pour structurer les claims identifiés.",
        })
        response2 = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "submit_claims"},
        )
        for block in response2.content:
            if block.type == "tool_use" and block.name == "submit_claims":
                return _parse_claims(block.input.get("claims", []))

    return []
