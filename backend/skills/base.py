"""Base class for all Skills."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """A Skill is a specialized system prompt template + output parser."""

    name: str = ""
    description: str = ""

    @staticmethod
    def extract_json(text: str) -> dict | list | None:
        """Extract JSON from model output, trying multiple strategies.

        1. Direct json.loads on the full text
        2. Extract from markdown code blocks (```json ... ```)
        3. Regex extract outermost {...} or [...]
        Returns None if all strategies fail.
        """
        text = text.strip()

        # Strategy 1: direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: markdown code block
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # Strategy 3: outermost braces / brackets
        for open_ch, close_ch in [('{', '}'), ('[', ']')]:
            start = text.find(open_ch)
            if start == -1:
                continue
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except (json.JSONDecodeError, ValueError):
                            break
            # If depth never reached 0, skip

        return None

    @abstractmethod
    def build_system_prompt(self, context: dict[str, Any]) -> str:
        """Return the system prompt fragment for this skill."""
        ...

    @abstractmethod
    def parse_output(self, raw: str) -> dict[str, Any]:
        """Parse the model's raw text output into structured data."""
        ...
