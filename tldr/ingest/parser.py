"""TLDR newsletter HTML → list of articles.

TLDR newsletters share a layout:
- Section headers (e.g. "BIG TECH & STARTUPS") are in <td>/<h2> blocks in all caps.
- Each article is an <a> with the title text, often suffixed "(N minute read)".
  The blurb text follows the link in document order — usually in the next <p>
  or <span> sibling under the same parent cell.
- The href routes through links.tldrnewsletter.com (which preserves the source).

Parser strategy: BeautifulSoup gives us .find_all_next() / .next_element walks
in document order, which is exactly what TLDR's layout needs. We collect external
anchors, pull title + read-time off the link text, and collect blurb text from
following DOM elements until the next external anchor.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from tldr.db.models import SourceName

log = logging.getLogger(__name__)

READ_TIME_RE = re.compile(r"\(\s*\d+\s+minute\s+read\s*\)|\(\s*GitHub\s+Repo\s*\)", re.I)
EXTRACT_READ_RE = re.compile(r"\(([^)]+)\)\s*$")

SKIP_FRAGMENTS = (
    "tldrnewsletter.com/subscribe",
    "tldrnewsletter.com/unsubscribe",
    "tldrnewsletter.com/manage",
    "tldr.tech/jobs",
    "tldr.tech/advertise",
    "twitter.com/tldrnewsletter",
    "linkedin.com/company/tldr",
)

SECTION_HEADER_RE = re.compile(r"^[\s\W]*([A-Z][A-Z0-9 &/\-]+?)[\s\W]*$")

BADGE_CLASS = {
    SourceName.tldr_tech: "b-general",
    SourceName.tldr_ai: "b-ai",
    SourceName.tldr_devops: "b-devops",
    SourceName.tldr_dev: "b-dev",
}


@dataclass(slots=True)
class ParsedArticle:
    title: str
    url: str
    raw_snippet: str
    read_time: str | None
    suggested_section: str | None
    position: int


def _is_external_link(href: str) -> bool:
    if not href or href.startswith(("mailto:", "#")):
        return False
    if any(skip in href for skip in SKIP_FRAGMENTS):
        return False
    return href.startswith(("http://", "https://"))


def _collect_snippet(anchor: Tag) -> str:
    """Walk forward via .next_element (document order, includes text nodes)
    until the next external anchor; collect text in between.
    """
    parts: list[str] = []
    char_budget = 1200
    # Skip the anchor's own descendants by jumping past them.
    cursor = anchor
    while cursor is not None:
        cursor = cursor.next_element
        if cursor is None:
            break
        # Stop at the next external <a>
        if isinstance(cursor, Tag) and cursor.name == "a":
            href = cursor.get("href") or ""
            if _is_external_link(href):
                break
            continue
        if isinstance(cursor, NavigableString):
            # Don't double-count the anchor's own text — skip strings that are
            # descendants of the source anchor.
            parent = cursor.parent
            while parent is not None and parent is not anchor:
                parent = parent.parent
            if parent is anchor:
                continue
            txt = str(cursor).strip()
            if txt:
                parts.append(txt)
                if sum(len(p) for p in parts) > char_budget:
                    break
    snippet = " ".join(parts).strip()
    snippet = re.sub(r"\s+", " ", snippet)
    return snippet[:2000]


def _detect_section(anchor: Tag) -> str | None:
    # Walk backward in document order, looking for an ALL-CAPS short text node.
    for node in anchor.find_all_previous(limit=200):
        if isinstance(node, Tag):
            text = node.get_text(" ", strip=True)
        elif isinstance(node, NavigableString):
            text = str(node).strip()
        else:
            continue
        if not text or len(text) > 80:
            continue
        # heuristic: header-like all-caps text
        letters = [c for c in text if c.isalpha()]
        if not letters:
            continue
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio < 0.9:
            continue
        m = SECTION_HEADER_RE.match(text)
        if m:
            return m.group(1).title()
    return None


def parse_tldr_html(html: str, source: SourceName) -> list[ParsedArticle]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    articles: list[ParsedArticle] = []
    pos = 0

    for a in soup.find_all("a"):
        href = a.get("href") or ""
        raw_text = a.get_text(" ", strip=True)
        if not raw_text or not _is_external_link(href):
            continue
        url_key = href.split("?")[0]
        if url_key in seen:
            continue
        seen.add(url_key)

        # Extract "(N minute read)" tail.
        read_time = None
        title = raw_text
        m = READ_TIME_RE.search(title)
        if m:
            inner = EXTRACT_READ_RE.search(title.strip())
            if inner:
                read_time = inner.group(1).strip()
            title = READ_TIME_RE.sub("", title).strip(" -—:|")
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 4:
            continue
        if title.lower() in {"read more", "read", "here", "view", "click here", "subscribe", "unsubscribe"}:
            continue

        snippet = _collect_snippet(a)
        section = _detect_section(a)

        articles.append(
            ParsedArticle(
                title=title[:480],
                url=href,
                raw_snippet=snippet,
                read_time=read_time,
                suggested_section=section,
                position=pos,
            )
        )
        pos += 1

    log.info("parser: %s -> %d articles", source.value, len(articles))
    return articles
