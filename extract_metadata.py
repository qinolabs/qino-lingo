#!/usr/bin/env python3
"""Extract metadata from conversation files for analysis."""

import os
import re
import json
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path("/Users/picard/Code/qinolabs/qino-lingo")
CONV_DIR = PROJECT_DIR / "corpus"
OUTPUT_FILE = PROJECT_DIR / "metadata.json"

def extract_metadata(filepath):
    """Extract metadata from a single conversation file."""
    text = filepath.read_text()
    size = filepath.stat().st_size

    # Extract date from filename: claude-conversation-YYYY-MM-DD-*.md
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath.name)
    date = date_match.group(1) if date_match else None

    # Check if it's an agent conversation
    is_agent = 'agent-' in filepath.name

    # Count turns
    user_turns = len(re.findall(r'^## 👤 User$', text, re.MULTILINE))
    claude_turns = len(re.findall(r'^## 🤖 Claude$', text, re.MULTILINE))

    # Extract user content (not command expansions)
    user_sections = re.split(r'^## 👤 User$', text, flags=re.MULTILINE)[1:]

    user_word_count = 0
    substantive_user_turns = 0
    has_command_expansion = False
    has_reflective_language = False

    # Patterns that suggest reflective/conceptual content
    reflective_patterns = [
        r"i've been thinking",
        r"what (makes|does|is|should|would|could)",
        r"how (can|do|should|would|could)",
        r"why (does|is|should|would)",
        r"the essence of",
        r"something about",
        r"let's (explore|think|consider)",
        r"my sense is",
        r"i wonder",
        r"what if",
        r"this feels like",
        r"there's something",
    ]

    for section in user_sections:
        # Check for command expansion (long system prompts)
        if len(section) > 2000 and ('## Task:' in section or '## Process' in section):
            has_command_expansion = True

        # Get content up to next section
        content = section.split('---')[0] if '---' in section else section

        # Skip command tags and system messages
        lines = content.strip().split('\n')
        substantive_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('<') and not line.startswith('Caveat:'):
                substantive_lines.append(line)

        user_text = ' '.join(substantive_lines)
        words = len(user_text.split())
        user_word_count += words

        if words > 10:
            substantive_user_turns += 1

        # Check for reflective language
        for pattern in reflective_patterns:
            if re.search(pattern, user_text, re.IGNORECASE):
                has_reflective_language = True
                break

    # Extract Claude content word count (rough)
    claude_sections = re.split(r'^## 🤖 Claude$', text, flags=re.MULTILINE)[1:]
    claude_word_count = 0
    for section in claude_sections:
        content = section.split('---')[0] if '---' in section else section
        claude_word_count += len(content.split())

    # Calculate dialogue density (user words per turn)
    dialogue_density = user_word_count / max(user_turns, 1)

    # Calculate exchange ratio
    exchange_ratio = user_turns / max(claude_turns, 1)

    return {
        "filename": filepath.name,
        "date": date,
        "is_agent": is_agent,
        "file_size": size,
        "user_turns": user_turns,
        "claude_turns": claude_turns,
        "substantive_user_turns": substantive_user_turns,
        "user_word_count": user_word_count,
        "claude_word_count": claude_word_count,
        "dialogue_density": round(dialogue_density, 1),
        "exchange_ratio": round(exchange_ratio, 2),
        "has_command_expansion": has_command_expansion,
        "has_reflective_language": has_reflective_language,
    }

def main():
    metadata = []

    for filepath in sorted(CONV_DIR.glob("claude-conversation-*.md")):
        try:
            meta = extract_metadata(filepath)
            metadata.append(meta)
        except Exception as e:
            print(f"Error processing {filepath.name}: {e}")

    # Write metadata
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Print summary statistics
    print(f"Extracted metadata for {len(metadata)} files")
    print(f"\nSaved to: {OUTPUT_FILE}")

    # Summary stats
    total_user_words = sum(m['user_word_count'] for m in metadata)
    total_claude_words = sum(m['claude_word_count'] for m in metadata)
    with_reflective = sum(1 for m in metadata if m['has_reflective_language'])
    with_command_exp = sum(1 for m in metadata if m['has_command_expansion'])
    agents = sum(1 for m in metadata if m['is_agent'])

    print(f"\n=== Summary ===")
    print(f"Total files: {len(metadata)}")
    print(f"Agent conversations: {agents}")
    print(f"With command expansions: {with_command_exp}")
    print(f"With reflective language: {with_reflective}")
    print(f"Total user words: {total_user_words:,}")
    print(f"Total Claude words: {total_claude_words:,}")

    # Distribution of substantive user turns
    substantive_dist = {}
    for m in metadata:
        bucket = m['substantive_user_turns']
        if bucket > 10:
            bucket = "10+"
        substantive_dist[bucket] = substantive_dist.get(bucket, 0) + 1

    print(f"\n=== Substantive User Turns Distribution ===")
    for k in sorted(substantive_dist.keys(), key=lambda x: int(x.replace('+', '')) if isinstance(x, str) else x):
        print(f"  {k}: {substantive_dist[k]}")

if __name__ == "__main__":
    main()
