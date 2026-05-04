"""
prompt_loader.py
================
Loads the LLM coding prompt from coding_prompt.md and exposes the individual
sections as strings.  All other scripts import from here instead of
hard-coding prompt text.

Sections in coding_prompt.md are delimited by lines starting with "## ".
Comments (lines starting with "#" that are NOT section markers) and the
file-level header block are ignored.

Public API
----------
    from prompt_loader import build_system_prompt, build_user_prompt, FALLBACK_CODEBOOK

    system_prompt = build_system_prompt(codebook_text)   # codebook from CSV #CONFIG, or fallback
    user_prompt   = build_user_prompt(row_dict)          # row dict from load_sample_csv
"""

from pathlib import Path

_PROMPT_FILE = Path(__file__).resolve().parent / "coding_prompt.md"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _load_sections(path: Path = _PROMPT_FILE) -> dict[str, str]:
    """
    Parse coding_prompt.md into a {section_name: text} dict.
    Lines starting with '## ' are section markers.
    Lines starting with '#' (but not '## ') before the first '## ' marker are
    treated as file-level comments and ignored.
    """
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("## "):
            # Save previous section
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = raw_line[3:].strip()
            current_lines = []
        else:
            # Skip file-level comment lines (before first section marker)
            if current_section is None and raw_line.startswith("#"):
                continue
            if current_section is not None:
                current_lines.append(raw_line)

    # Save last section
    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


# Load once at import time; re-import or call _load_sections() to refresh
_SECTIONS = _load_sections()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_section(name: str) -> str:
    """Return a named section from coding_prompt.md, or raise KeyError."""
    if name not in _SECTIONS:
        raise KeyError(
            f"Section '{name}' not found in {_PROMPT_FILE.name}. "
            f"Available: {list(_SECTIONS.keys())}"
        )
    return _SECTIONS[name]


# The full fallback codebook (used when CSV #CONFIG parsing fails)
FALLBACK_CODEBOOK: str = get_section("CODEBOOK")


def build_system_prompt(codebook: str) -> str:
    """
    Assemble the system prompt from its components.
    `codebook` is either the text from the CSV #CONFIG line or FALLBACK_CODEBOOK.
    """
    intro          = get_section("SYSTEM_INTRO")
    presence_check = get_section("PRESENCE_CHECK")  # may be empty — see coding_prompt.md
    examples       = get_section("EXAMPLES")
    json_format    = get_section("JSON_FORMAT")

    parts = [intro.strip(), codebook.strip()]
    if presence_check.strip():
        parts.append(presence_check.strip())
    if examples.strip():
        parts.append(examples.strip())
    parts.append(json_format.strip())

    return "\n\n".join(parts)


def build_user_prompt(row: dict) -> str:
    """
    Build the per-row user prompt.
    Strips the [✓/⚠ ...] intercoder header line from extracted_text before use.
    """
    excerpt     = _strip_context_header(row.get("extracted_text", "").strip())
    target_ngo  = row.get("target_ngo", "")
    user_check  = get_section("USER_CHECK").format(target_ngo=target_ngo)

    return (
        f"SOURCE NGO (publisher): {row.get('source_ngo', '')}\n"
        f"TARGET NGO (mentioned): {target_ngo}\n"
        f"Year: {row.get('year', '?')}\n"
        f"Article: {row.get('article_name', '?')}\n"
        f"Keywords: {row.get('relation_keywords', '')}\n\n"
        f"<excerpt>\n"
        f"{excerpt}\n"
        f"</excerpt>\n\n"
        + user_check.strip()
        + "\n\n"
        "Reply with ONLY the JSON object."
    )


def _strip_context_header(text: str) -> str:
    """
    Remove the leading [✓ / ⚠ / ~ ...] header line injected by the intercoder
    tool — it is a UI hint for human coders, not part of the article text.

    Also strips leading/trailing Unicode ellipsis characters (…, U+2026) that
    mark truncated windows in the excerpt.  Ollama returns empty responses when
    the prompt starts with that character.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            result = "\n".join(lines[i + 1:]).lstrip("\n")
            return result.strip("\u2026").strip()
        if s:
            break
    return text.strip("\u2026").strip()


# ---------------------------------------------------------------------------
# CLI: print assembled prompts for inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("SECTIONS LOADED:", list(_SECTIONS.keys()))
    print("=" * 60)

    print("\n--- SYSTEM PROMPT (using fallback codebook) ---\n")
    print(build_system_prompt(FALLBACK_CODEBOOK))

    print("\n--- USER PROMPT (example row) ---\n")
    example = {
        "source_ngo": "Greenpeace CR",
        "target_ngo": "Frank Bold",
        "year": "2020",
        "article_name": "Turów mine dispute",
        "relation_keywords": "projektů",
        "extracted_text": (
            '[⚠ Fallback: NGO "Frank Bold" found separately]\n\n'
            'Prosazujeme, aby spor o důl Turów mezi Českem a Polskem rozhodla EU...'
        ),
    }
    print(build_user_prompt(example))
