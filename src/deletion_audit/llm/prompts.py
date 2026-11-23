"""Versioned prompt loader with untrusted content delimiting and injection sanitization."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*override\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
    re.compile(r"</?untrusted_(?:evidence|request_text)>", re.IGNORECASE),
)


@dataclass(frozen=True)
class PromptTemplate:
    """Loaded versioned prompt file."""

    prompt_id: str
    version: str
    template: str
    content_hash: str

    def render(self, **kwargs: str) -> str:
        """Render template with sanitized untrusted placeholders."""
        safe_kwargs = {k: sanitize_untrusted_text(v) for k, v in kwargs.items()}
        return self.template.format(**safe_kwargs)


def sanitize_untrusted_text(text: str) -> str:
    """Neutralize boundary-escape tags and flag obvious prompt-injection directives."""
    cleaned = text.replace("<untrusted_", "<escaped_untrusted_").replace(
        "</untrusted_", "</escaped_untrusted_"
    )
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[PROMPT_INJECTION_NEUTRALIZED]", cleaned)
    return cleaned


def contains_prompt_injection(text: str) -> bool:
    """Detect whether untrusted text contains a prompt-injection attempt."""
    return any(pattern.search(text) is not None for pattern in _INJECTION_PATTERNS)


def load_prompt(prompts_dir: Path, filename: str) -> PromptTemplate:
    """Load a versioned prompt file from `prompts/`."""
    path = (prompts_dir / filename).resolve()
    raw = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    prompt_id = path.stem
    version = "v1"
    body = raw
    if raw.startswith("---\n"):
        parts = raw.split("---\n", 2)
        if len(parts) == 3:
            header, body = parts[1], parts[2]
            for line in header.splitlines():
                if line.startswith("prompt_id:"):
                    prompt_id = line.split(":", 1)[1].strip()
                elif line.startswith("version:"):
                    version = line.split(":", 1)[1].strip()
    return PromptTemplate(
        prompt_id=prompt_id,
        version=version,
        template=body.strip(),
        content_hash=digest,
    )
