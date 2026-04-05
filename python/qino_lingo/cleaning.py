"""
Noise filtering for conversation transcripts.

Strips system-generated content, code blocks, console output, and terse
commands to reveal the exchanges where genuine thinking is visible.

The exchange (user turn + assistant response) is the unit of meaning.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .parser import parse_conversation


@dataclass
class CleanedExchange:
    """A cleaned user-assistant exchange with signal metadata."""

    index: int
    user_text: str
    assistant_text: Optional[str]
    user_words: int
    is_system: bool = False
    is_terse: bool = False


# --- System content detection ---


_SYSTEM_PATTERNS = [
    "this session is being continued from a previous conversation",
    "the summary below covers the earlier portion",
    "the conversation is summarized below",
    "analysis: let me",
    "let me chronologically analyze",
    "let me trace through",
    "## task:",
    "## process",
    "base directory for this skill:",
    "you are the **qino-",
    "ecology for developing ideas",
]


def is_system_content(text: str) -> bool:
    """Detect context compaction summaries, skill expansions, and agent injections."""
    lower = text.lower()
    if lower.startswith("implement the following plan:"):
        return True
    return any(pattern in lower for pattern in _SYSTEM_PATTERNS)


# --- Content stripping ---


def strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks."""
    return re.sub(r"```[\s\S]*?```", "", text)


def strip_console_output(text: str) -> str:
    """Remove stack traces and console diagnostic lines."""
    lines = text.split("\n")
    return "\n".join(
        line
        for line in lines
        if not re.match(
            r"\s*(at |overrideMethod @|installHook\.js|react-dom"
            r"|\.tsx:\d|\.ts:\d|react_stack_bottom_frame)",
            line,
        )
    )


def strip_xml_tags(text: str) -> str:
    """Remove XML tag pairs and self-closing tags."""
    text = re.sub(r"<[^>]+>[^<]*</[^>]+>", "", text)
    return re.sub(r"<[^>]+/?>", "", text)


def strip_file_paths(text: str) -> str:
    """Reduce absolute file paths to just a marker."""
    return re.sub(r"/Users/\w+/Code/[^\s\)]+", "[path]", text)


# --- Terse command detection ---

_TERSE_PATTERNS = [
    r"^(yes|no|ok|okay|good|great|perfect|nice|cool|thanks|correct|exactly)\.?$",
    r"^(build it|do it|resume|continue|next|commit|push|proceed|go ahead)\.?$",
    r"^(fix (it|this|that)|try (it|this|that|again))\.?$",
    r"^[a-z]$",
    r"^\d+$",
]


def is_terse_command(text: str) -> bool:
    """Detect short operational steering commands."""
    clean = text.strip().lower()
    if len(clean.split()) > 5:
        return False
    return any(re.match(p, clean) for p in _TERSE_PATTERNS)


# --- Turn cleaning ---


def clean_user_turn(raw: str) -> str:
    """Apply all noise filters to a raw user turn. Returns cleaned text."""
    text = strip_code_blocks(raw)
    text = strip_console_output(text)
    text = strip_xml_tags(text)
    text = strip_file_paths(text)

    lines = [
        line.strip()
        for line in text.strip().split("\n")
        if line.strip()
        and not line.strip().startswith("Caveat:")
        and not line.strip().startswith("[Request interrupted")
    ]
    return " ".join(lines).strip()


# --- Exchange-level cleaning ---


def clean_conversation(filepath: Path) -> list[CleanedExchange]:
    """Parse and clean a conversation into exchange-level data.

    Returns a list of CleanedExchange objects — user-assistant pairs
    with noise filtered and metadata attached.
    """
    text = filepath.read_text()
    parts = re.split(r"^## (👤 User|🤖 Claude)$", text, flags=re.MULTILINE)

    # Collect raw turns in order
    raw_turns: list[dict] = []
    i = 1
    while i < len(parts) - 1:
        role_marker = parts[i].strip()
        content = parts[i + 1].strip()

        if role_marker == "👤 User":
            role = "user"
        elif role_marker == "🤖 Claude":
            role = "assistant"
        else:
            i += 2
            continue

        # Clean content: remove trailing separator
        content = re.sub(r"\n---\s*$", "", content).strip()
        if content:
            raw_turns.append({"role": role, "content": content})

        i += 2

    # Pair into exchanges (user + following assistant)
    exchanges: list[CleanedExchange] = []
    exchange_idx = 0
    j = 0

    while j < len(raw_turns):
        turn = raw_turns[j]

        if turn["role"] != "user":
            j += 1
            continue

        raw_user = turn["content"]

        # Find paired assistant response
        assistant_text = None
        if j + 1 < len(raw_turns) and raw_turns[j + 1]["role"] == "assistant":
            assistant_content = raw_turns[j + 1]["content"]
            # Clean assistant: strip code blocks but keep text
            assistant_text = strip_code_blocks(assistant_content).strip()
            # Truncate very long assistant responses for memory efficiency
            if len(assistant_text) > 3000:
                # Find sentence boundary near limit
                cut = assistant_text[:3000].rfind(". ")
                if cut > 2000:
                    assistant_text = assistant_text[: cut + 1] + " [...]"
                else:
                    assistant_text = assistant_text[:3000] + " [...]"
            j += 1

        # Classify the user turn
        system = is_system_content(raw_user)
        cleaned = clean_user_turn(raw_user)

        if not cleaned or len(cleaned) < 10:
            j += 1
            continue

        terse = is_terse_command(cleaned)
        word_count = len(cleaned.split())

        exchanges.append(
            CleanedExchange(
                index=exchange_idx,
                user_text=cleaned,
                assistant_text=assistant_text,
                user_words=word_count,
                is_system=system,
                is_terse=terse,
            )
        )
        exchange_idx += 1
        j += 1

    return exchanges
