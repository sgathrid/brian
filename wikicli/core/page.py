"""WikiPage model and WikiDatabase parser."""

from __future__ import annotations

import re
from pathlib import Path


class WikiPage:
    """Represents a single markdown page with frontmatter and wikilinks."""

    def __init__(self, filepath: Path):
        self.filepath = filepath.resolve()
        self.stem = self.filepath.stem
        self.frontmatter: dict[str, str | list[str]] = {}
        self.title: str = self.stem
        self.tags: list[str] = []
        self.context_keys: list[str] = []
        self.aliases: list[str] = []
        self.repo: str = ""
        self.summary: str = ""

        self._body: str | None = None
        self._wikilinks: list[str] | None = None

        self._parse_frontmatter_only()

    @property
    def scope(self) -> str:
        s = self.frontmatter.get("scope", "")
        return s if isinstance(s, str) else ""

    @property
    def body(self) -> str:
        """Page prose, read on FIRST ACCESS rather than at load.

        `wiki context` runs on every session start in every repo and never looks at prose — it scores
        `context_keys`, `aliases`, `repo`, `title` and frontmatter `tags`. Reading every body eagerly
        made the hot path 3.7x slower (0.106s vs 0.028s at 1,000 pages) and held every page's text in
        memory (2.5 MB at 1,000 pages) for no benefit. `find`, `audit` and `gen` do need prose, and
        they pay for it here, once, on demand.
        """
        if self._body is None:
            try:
                content = self.filepath.read_text(encoding="utf-8")
            except OSError:
                self._body = ""
                return self._body
            if content.startswith("---"):
                parts = content.split("---", 2)
                self._body = parts[2].strip() if len(parts) >= 3 else content
            else:
                self._body = content
        return self._body

    @property
    def wikilinks(self) -> list[str]:
        """Outbound `[[links]]`, parsed from the body on first access."""
        if self._wikilinks is None:
            seen: list[str] = []
            for raw in re.findall(r"\[\[(.*?)\]\]", self.body):
                link = raw.strip().strip("\"'")
                if link and link not in seen:
                    seen.append(link)
            self._wikilinks = seen
        return self._wikilinks

    @property
    def links(self) -> list[str]:
        return self.wikilinks

    def _parse_frontmatter_only(self) -> None:
        """Streams just the frontmatter block, stopping at its closing delimiter."""
        try:
            with open(self.filepath, encoding="utf-8") as handle:
                first = handle.readline()
                if first.strip() != "---":
                    return
                lines: list[str] = []
                for line in handle:
                    if line.strip() == "---":
                        break
                    lines.append(line)
        except OSError:
            return
        self._parse_frontmatter("".join(lines))

    def _parse_frontmatter(self, fm_text: str) -> None:
        for line in fm_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue

            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip().strip("\"'")

            if val.startswith("[") and val.endswith("]"):
                items = [item.strip().strip("\"'") for item in val[1:-1].split(",") if item.strip()]
                self.frontmatter[key] = items
            else:
                self.frontmatter[key] = val

        if "title" in self.frontmatter and isinstance(self.frontmatter["title"], str):
            self.title = self.frontmatter["title"]

        if "summary" in self.frontmatter and isinstance(self.frontmatter["summary"], str):
            self.summary = self.frontmatter["summary"]

        if "repo" in self.frontmatter and isinstance(self.frontmatter["repo"], str):
            self.repo = self.frontmatter["repo"]

        # Parse context_keys, aliases, and tags from frontmatter
        for k in ("context_keys", "aliases", "tags"):
            if k in self.frontmatter:
                v = self.frontmatter[k]
                val_list = v if isinstance(v, list) else [v]
                if k == "context_keys":
                    self.context_keys = val_list
                elif k == "aliases":
                    self.aliases = val_list
                elif k == "tags":
                    for t in val_list:
                        if t not in self.tags:
                            self.tags.append(t)


NAV_PAGES = {"index.md", "log.md", "tags.md", "backlinks.md", "conventions.md", "scaling.md"}


def is_nav(filepath: Path) -> bool:
    """Returns True if the file is a navigation or meta page rather than content."""
    return filepath.name.lower() in NAV_PAGES


class WikiDatabase:
    """In-memory database indexing all markdown pages under a wiki directory."""

    def __init__(self, wiki_dir: Path):
        self.wiki_dir = wiki_dir.resolve()
        self.pages: dict[Path, WikiPage] = {}
        self.by_title: dict[str, WikiPage] = {}
        self.by_stem: dict[str, WikiPage] = {}
        self.collisions: list[str] = []

        self._load()

    def _load(self) -> None:
        if not self.wiki_dir.is_dir():
            return

        # P0.1: Recursive globbing for all markdown pages
        for page_file in sorted(self.wiki_dir.rglob("*.md")):
            if is_nav(page_file):
                continue

            page = WikiPage(page_file)
            self.pages[page_file] = page

            # Title indexing with collision detection
            norm_title = page.title.lower()
            if norm_title in self.by_title:
                self.collisions.append(
                    f"Title collision for '{page.title}': {page_file.name} vs {self.by_title[norm_title].filepath.name}"
                )
            else:
                self.by_title[norm_title] = page

            # Stem indexing
            norm_stem = page.stem.lower()
            if norm_stem not in self.by_stem:
                self.by_stem[norm_stem] = page

    def resolve_link(self, link_text: str) -> WikiPage | None:
        """Resolves a wikilink string to a WikiPage object."""
        clean = link_text.strip().lower().strip("\"'")
        if clean in self.by_title:
            return self.by_title[clean]
        if clean in self.by_stem:
            return self.by_stem[clean]
        return None
