"""Render a session to a shareable Markdown document.

Pure formatting over the read schemas (no DB, no I/O), so it's trivially testable
and reusable by both the JSON and Markdown export paths. The JSON export is just
the ``SessionDetail`` serialized as-is; this module covers the human-readable form.
"""

from app.schemas.history import SessionDetail


def _format_dt(value: object) -> str:
    return str(value) if value is not None else "—"


def session_to_markdown(detail: SessionDetail) -> str:
    s = detail.stats
    lines: list[str] = []

    lines.append(f"# LiveFactChecker — session {detail.id}")
    lines.append("")
    lines.append(f"- **Started**: {_format_dt(detail.started_at)}")
    lines.append(
        f"- **Ended**: {'active' if detail.active else _format_dt(detail.ended_at)}"
    )
    if s.duration_s is not None:
        lines.append(f"- **Duration**: {s.duration_s} s")
    lines.append(f"- **Client**: {detail.client_host}")
    lines.append("")

    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- Transcripts: {s.transcripts_count}")
    by_status = ", ".join(f"{k} {v}" for k, v in sorted(s.claims_by_status.items()))
    claims_line = f"- Claims: {s.claims_count}"
    if by_status:
        claims_line += f" ({by_status})"
    lines.append(claims_line)
    lines.append(f"- Rejects (verified, no claim): {s.rejects}")
    if s.dominant_category:
        lines.append(f"- Dominant category: {s.dominant_category}")
    if s.avg_confidence is not None:
        lines.append(f"- Average confidence: {s.avg_confidence}/10")
    lines.append(
        f"- Web search: {s.web_search_calls_total} calls "
        f"over {s.web_search_segments} segments"
    )
    lines.append(
        f"- Tokens: {s.tokens.total} total "
        f"(in {s.tokens.input}, out {s.tokens.output}, "
        f"cache_read {s.tokens.cache_read}, cache_write {s.tokens.cache_write})"
    )
    if s.estimated_cost_usd is not None:
        lines.append(f"- Estimated cost: ${s.estimated_cost_usd} ({s.pricing_model})")
    lines.append(f"- API calls: {s.api_calls_total} (fallbacks: {s.fallback_count})")
    if s.avg_transcribe_ms is not None:
        lines.append(f"- Avg transcription latency: {s.avg_transcribe_ms} ms")
    if s.avg_verify_ms is not None:
        lines.append(f"- Avg verification latency: {s.avg_verify_ms} ms")
    lines.append("")

    lines.append("## Claims")
    lines.append("")
    if not detail.claims:
        lines.append("_No claims._")
    for claim in detail.claims:
        lines.append(f"### [{claim.status}] {claim.text}")
        if claim.explanation:
            lines.append(f"- {claim.explanation}")
        if claim.counter_claim:
            lines.append(f"- **Correction**: {claim.counter_claim}")
        meta = f"confidence {claim.confidence}/10"
        if claim.category:
            meta += f" · {claim.category}"
        lines.append(f"- _{meta}_")
        for source in claim.sources:
            lines.append(f"- Source: {source}")
        lines.append("")

    lines.append("## Transcript")
    lines.append("")
    for segment in detail.segments:
        lines.append(f"{segment.seq + 1}. ({segment.detected_language}) {segment.text}")
    lines.append("")

    return "\n".join(lines)
