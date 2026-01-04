#!/usr/bin/env python3
"""Filter obvious noise from conversation files."""

import os
import re
import shutil
from pathlib import Path

CONV_DIR = Path("/Users/picard/Code/qinolabs/qino-conversations")
NOISE_DIR = CONV_DIR / "_noise"

# Ensure noise directory exists
NOISE_DIR.mkdir(exist_ok=True)

def count_pattern(text, pattern):
    return len(re.findall(pattern, text, re.MULTILINE))

def is_noise(filepath):
    """Determine if a file is clearly noise."""
    text = filepath.read_text()
    size = filepath.stat().st_size

    user_turns = count_pattern(text, r'^## 👤 User$', )
    claude_turns = count_pattern(text, r'^## 🤖 Claude$')

    # Count substantive user content (not just command tags)
    # Look for user sections followed by actual text (not command-message tags)
    user_sections = re.split(r'^## 👤 User$', text, flags=re.MULTILINE)[1:]  # Skip header
    substantive_user = 0
    for section in user_sections:
        # Check if section has real content (not just command tags or empty)
        lines = section.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('<') and not line.startswith('---') and line != 'Caveat:':
                # Has substantive content
                if len(line) > 20 and not line.startswith('Caveat:'):
                    substantive_user += 1
                    break

    # Filter criteria:

    # 1. Very small files with no Claude response
    if size < 1000 and claude_turns == 0:
        return True, "under 1KB, no Claude response"

    # 2. Files with only /clear or /exit commands
    if '<command-name>/clear</command-name>' in text or '<command-name>/exit</command-name>' in text:
        if substantive_user == 0 and claude_turns <= 1:
            return True, "only clear/exit commands"

    # 3. Agent warmup files with minimal exchange
    if 'agent-' in filepath.name and size < 1500:
        if user_turns <= 2 and claude_turns <= 1:
            # Check if it's just warmup
            if 'Warmup' in text or "I'm ready to help" in text:
                if substantive_user == 0:
                    return True, "agent warmup only"

    # 4. No substantive user input (only commands, no real dialogue)
    if substantive_user == 0 and claude_turns > 0:
        return True, "no substantive user input"

    # 5. Pure transactional: only "commit" commands with no conceptual exchange
    # Check if file is small and only contains commit/update operations
    if size < 3000:
        transactional_patterns = [
            r'commit (all|the|these|changes)',
            r'^commit\s*$',
            r'/update-qino-tools',
            r'git (add|commit|push|status)',
        ]
        is_transactional = any(re.search(p, text, re.IGNORECASE | re.MULTILINE) for p in transactional_patterns)

        # But check if there's any conceptual exchange (questions, explanations beyond the transaction)
        conceptual_markers = [
            r'what (makes|does|is|should|would|could)',
            r'how (can|do|should|would|could)',
            r'why (does|is|should|would)',
            r'the essence of',
            r'something about',
            r'i\'ve been thinking',
            r'let\'s (explore|think|consider)',
        ]
        has_conceptual = any(re.search(p, text, re.IGNORECASE) for p in conceptual_markers)

        if is_transactional and not has_conceptual and claude_turns <= 3:
            return True, "pure transactional"

    return False, None

def main():
    moved = 0
    reasons = {}

    for filepath in CONV_DIR.glob("claude-conversation-*.md"):
        is_noise_file, reason = is_noise(filepath)
        if is_noise_file:
            shutil.move(str(filepath), str(NOISE_DIR / filepath.name))
            moved += 1
            reasons[reason] = reasons.get(reason, 0) + 1

    print(f"Moved {moved} files to _noise/")
    print("\nBreakdown:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    remaining = len(list(CONV_DIR.glob("claude-conversation-*.md")))
    print(f"\nRemaining: {remaining} files")

if __name__ == "__main__":
    main()
