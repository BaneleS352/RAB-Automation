"""Shared Jira ADF helpers — single source for description parsing (was duplicated in 3 files)."""

import json


def adf_to_text(adf: object) -> str:
    """Flatten Atlassian Document Format (description) to plain text. Robust to missing 'text' keys."""
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf
    if isinstance(adf, dict):
        parts: list[str] = []
        for block in adf.get("content") or []:
            if isinstance(block, dict):
                for inline in block.get("content") or []:
                    if isinstance(inline, dict):
                        if inline.get("type") == "text":
                            parts.append(inline.get("text") or "")
                        elif "text" in inline:
                            parts.append(str(inline["text"]))
                parts.append("\n")
        text = "".join(parts).strip()
        return text if text else json.dumps(adf)[:500] if adf else ""
    return str(adf)[:1000]
