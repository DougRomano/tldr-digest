"""Prompt templates for summarization, clustering, and tagging.

The "so what for .NET" voice is the most important constraint — see the
examples for the tone Doug expects.
"""
from __future__ import annotations

SUMMARIZE_SYSTEM = """\
You write punchy weekly-digest summaries of tech news for a senior .NET / Azure
architect (Doug Romano). For each article, produce:
- summary (2-4 sentences, concrete, with numbers when the source has them)
- so_what (1-2 sentences explicitly framed for a .NET / Azure enterprise practitioner;
  reference Microsoft-stack analogs like Entra ID, Defender, EF Core, ASP.NET, YARP,
  Hangfire, Dapper, Sentinel, Azure DevOps, M365 audit logs when relevant)
- suggested_section (a short title-cased thematic header, e.g. "Agent Sprawl & Governance",
  "MCP Tooling", "Security & Risk", "Distribution & Pricing")
- suggested_tags (3-5 short technical/domain tags — lowercase, hyphenated; NEVER
  generic words like "AI", "tech", "article")

Reply ONLY with a JSON object: {"summary": str, "so_what": str, "suggested_section": str, "suggested_tags": [str]}.
No prose. No markdown fence.

Example output for an article about ServiceNow AI Control Tower:
{"summary": "ServiceNow expanded AI Control Tower to discover, govern, secure, and monitor AI agents across its own platform and third-party environments. New integrations span AWS, Google Cloud, Azure, SAP, Oracle, and Workday, plus a kill switch that can shut down compromised agents during attacks. Pulls in Veza's access graph and Traceloop's monitoring.", "so_what": "If your ITSM is already ServiceNow, this is the lowest-friction path to multi-cloud agent governance. Treat the kill switch as a real DR primitive — runbook it, drill it.", "suggested_section": "Agent Sprawl & Enterprise Control Towers", "suggested_tags": ["servicenow", "kill-switch", "governance", "veza"]}
"""

SUMMARIZE_USER = """\
Source newsletter: {source}
Title: {title}

Snippet:
{snippet}
"""

THEME_SYSTEM = """\
You group a week of TLDR newsletter articles into 3 to 6 thematic sections for a
.NET / Azure architect's weekly digest. You also pick:
- A punchy newsroom-style HEADLINE (8-12 words, no clickbait, no emojis).
- An eyebrow line ("Weekly TLDR Digest — Topic: <newsletter>").
- 4 metric cards: a big number/value (e.g. "71%", "$1.5B", "700+", "15,000+") with a 4-8 word LABEL and a 5-9 word SUB caption explaining the significance. Pull metrics directly from the article snippets — invent NOTHING.
- A list of sections, each with an emoji (🚦🧠🔐💰🛠️📦🚀🧪🛰️🪪⚖️📈), a short title-cased title, and the article ids that belong in it. Every supplied article id must appear in exactly one section.

Reply ONLY with JSON of this shape:
{
  "headline": str,
  "eyebrow": str,
  "metrics": [{"value": str, "label": str, "sub": str}, ...4 items],
  "sections": [{"emoji": str, "title": str, "article_ids": [int]}, ...]
}
"""

THEME_USER = """\
Newsletter: {source_display}
Week: {week_display}
Articles (id | title | one-line):
{article_list}
"""

TAG_SYSTEM = """\
Suggest 3-5 tags (short, lowercase, hyphenated, domain-specific) for the article. Prefer reusing existing tags when they fit; otherwise propose new ones.
Reply ONLY with a JSON array of strings. Example: ["mcp", "azure", "openid"]
"""

TAG_USER = """\
Existing tags: {existing}
Title: {title}
Snippet: {snippet}
"""
