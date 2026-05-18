from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _badge_label(source_value: str) -> str:
    return {
        "tldr_tech": "TLDR",
        "tldr_ai": "TLDR AI",
        "tldr_devops": "TLDR DevOps",
        "tldr_dev": "TLDR Dev",
    }.get(source_value, source_value)


def _badge_class(source_value: str) -> str:
    return {
        "tldr_tech": "b-general",
        "tldr_ai": "b-ai",
        "tldr_devops": "b-devops",
        "tldr_dev": "b-dev",
    }.get(source_value, "b-general")


def _short_date(d) -> str:
    return d.strftime("%b %d") if d else ""


templates.env.filters["badge_label"] = _badge_label
templates.env.filters["badge_class"] = _badge_class
templates.env.filters["short_date"] = _short_date
