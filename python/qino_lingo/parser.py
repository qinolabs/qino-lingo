"""
Conversation parser — transforms markdown logs into structured Turn objects.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from datetime import datetime


@dataclass
class Turn:
    """A single turn in a conversation."""
    role: str  # 'user' or 'assistant'
    content: str
    index: int

    # Derived properties
    word_count: int = 0
    is_command: bool = False
    is_command_expansion: bool = False
    has_substantive_content: bool = False

    def __post_init__(self):
        self.word_count = len(self.content.split())
        self.is_command = bool(re.search(r'<command-name>', self.content))
        self.is_command_expansion = len(self.content) > 2000 and ('## Task:' in self.content or '## Process' in self.content)

        # Check for substantive content (not just commands/system messages)
        clean = re.sub(r'<[^>]+>[^<]*</[^>]+>', '', self.content)  # Remove XML tags
        clean = re.sub(r'Caveat:.*', '', clean)
        clean = clean.strip()
        self.has_substantive_content = len(clean) > 20 and not self.is_command


@dataclass
class TurnPair:
    """A user-assistant turn pair."""
    user_turn: Turn
    assistant_turn: Optional[Turn]

    @property
    def is_complete(self) -> bool:
        return self.assistant_turn is not None

    @property
    def combined_content(self) -> str:
        parts = [f"USER: {self.user_turn.content}"]
        if self.assistant_turn:
            parts.append(f"ASSISTANT: {self.assistant_turn.content}")
        return "\n\n".join(parts)


@dataclass
class Conversation:
    """A parsed conversation with metadata."""
    filename: str
    session_id: str
    date: Optional[str]
    turns: List[Turn] = field(default_factory=list)

    @property
    def user_turns(self) -> List[Turn]:
        return [t for t in self.turns if t.role == 'user']

    @property
    def assistant_turns(self) -> List[Turn]:
        return [t for t in self.turns if t.role == 'assistant']

    @property
    def substantive_user_turns(self) -> List[Turn]:
        return [t for t in self.user_turns if t.has_substantive_content]

    @property
    def turn_pairs(self) -> List[TurnPair]:
        """Extract user-assistant turn pairs."""
        pairs = []
        i = 0
        while i < len(self.turns):
            if self.turns[i].role == 'user':
                user_turn = self.turns[i]
                assistant_turn = None
                if i + 1 < len(self.turns) and self.turns[i + 1].role == 'assistant':
                    assistant_turn = self.turns[i + 1]
                    i += 1
                pairs.append(TurnPair(user_turn, assistant_turn))
            i += 1
        return pairs

    @property
    def total_user_words(self) -> int:
        return sum(t.word_count for t in self.user_turns)

    @property
    def total_assistant_words(self) -> int:
        return sum(t.word_count for t in self.assistant_turns)


def parse_conversation(filepath: Path) -> Conversation:
    """Parse a markdown conversation file into a Conversation object."""
    text = filepath.read_text()

    # Extract session ID
    session_match = re.search(r'Session ID: (.+)', text)
    session_id = session_match.group(1).strip() if session_match else filepath.stem

    # Extract date from filename
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath.name)
    date = date_match.group(1) if date_match else None

    # Split into turns
    turn_pattern = r'^## (👤 User|🤖 Claude)$'
    parts = re.split(turn_pattern, text, flags=re.MULTILINE)

    turns = []
    i = 1  # Skip header
    turn_index = 0

    while i < len(parts) - 1:
        role_marker = parts[i].strip()
        content = parts[i + 1].strip()

        # Clean content: remove trailing ---
        content = re.sub(r'\n---\s*$', '', content).strip()

        if role_marker == '👤 User':
            role = 'user'
        elif role_marker == '🤖 Claude':
            role = 'assistant'
        else:
            i += 2
            continue

        if content:  # Skip empty turns
            turns.append(Turn(role=role, content=content, index=turn_index))
            turn_index += 1

        i += 2

    return Conversation(
        filename=filepath.name,
        session_id=session_id,
        date=date,
        turns=turns
    )


def parse_all_conversations(directory: Path) -> List[Conversation]:
    """Parse all conversation files in a directory."""
    conversations = []
    for filepath in sorted(directory.glob("claude-conversation-*.md")):
        try:
            conv = parse_conversation(filepath)
            conversations.append(conv)
        except Exception as e:
            print(f"Error parsing {filepath.name}: {e}")
    return conversations
