"""Pure formatters for the session-start brief. No I/O."""

from __future__ import annotations

PROACTIVITY_LABELS = {
    "selective": "selective — offer updates for durable, high-signal changes",
    "active": "active — offer updates often; still ask first",
    "capture": "capture — prefer logging; treat most durable context as worth saving",
    "silent": "silent — only update the wiki when the user asks",
}


def format_upkeep_block(
    triggers: list[str] | None,
    instructions: str | None,
    proactivity: str = "",
) -> str:
    """Return markdown block including ## Keeping it current, or "" if empty.

    Includes both bullet triggers and instructions when present. Known proactivity
    keys add a Proactivity line.
    """
    parts: list[str] = []

    key = (proactivity or "").strip().lower()
    if key in PROACTIVITY_LABELS:
        parts.append(f"Proactivity: {PROACTIVITY_LABELS[key]}")

    if triggers:
        for raw in triggers:
            trigger = str(raw).strip()
            if trigger:
                parts.append(f"- {trigger}")

    instr = (instructions or "").strip()
    if instr:
        parts.append(instr)

    if not parts:
        return ""

    return "## Keeping it current\n" + "\n".join(parts) + "\n\n"


def format_rules_block(rule_ids: list[str] | None, catalog: dict) -> str:
    """## Active agent rules with prompt_rule lines.

    If metadata has page_guidance (str), append it indented under that rule.
    Skip unknown ids. Return "" if nothing.
    """
    if not rule_ids or not catalog:
        return ""

    lines: list[str] = []
    for rid in rule_ids:
        meta = catalog.get(rid)
        if not isinstance(meta, dict):
            continue
        prompt = meta.get("prompt_rule")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        lines.append(prompt.strip())
        guidance = meta.get("page_guidance")
        if isinstance(guidance, str) and guidance.strip():
            for gl in guidance.strip().splitlines():
                lines.append(f"  {gl}" if gl.strip() else "")

    if not lines:
        return ""

    return "## Active agent rules\n" + "\n".join(lines) + "\n\n"
