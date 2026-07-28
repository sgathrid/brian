"""Shared fixtures.

Tests build a SYNTHETIC wiki rather than reading the real `wiki/` tree. Two reasons:

1. Assertions stay meaningful. A test that says "resolving `core/pulsar` returns `pulsar`" against
   live content breaks whenever someone renames a page — so it gets weakened to
   `assertIsInstance(result, list)`, which is how a completely broken resolver shipped once already.
2. Edge cases can be represented. The live wiki has no title/filename collision, no page with a
   dotted repo name, no malformed frontmatter — and those are exactly the cases that broke.

`tests/test_live_wiki.py` covers the real tree separately, with assertions that survive edits.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikicli.core.page import WikiDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_page(directory: Path, name: str, frontmatter: str, body: str = "") -> Path:
    """Writes a markdown page with frontmatter. `frontmatter` is the inner YAML, without `---`."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\n{frontmatter.strip()}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return path


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    """A synthetic wiki exercising every resolution and relationship case that has broken before.

    Layout deliberately uses SUBDIRECTORIES — the real content lives in `wiki/entities/` and
    `wiki/concepts/`, and a non-recursive glob once loaded zero content pages while every test
    still passed.
    """
    root = tmp_path / "wiki"
    entities = root / "entities"
    concepts = root / "concepts"

    # Plain project page: resolves by context_keys and by repo basename.
    write_page(
        entities,
        "pulsar.md",
        """
        title: "Pulsar"
        type: entity
        scope: project
        summary: "Topological data analysis pipeline."
        repo: git@github.com:Brian-Org/pulsar.git
        context_keys: [pulsar, thema, themars]
        tags: [python, rust, topology]
        updated: 2026-01-01
        """,
        "Pulsar depends on [[ThemaRS Pipeline]] for orchestration.",
    )

    # The hyphen trap: `compass-ui` must NOT be matched by the bare fragment `ui`.
    write_page(
        entities,
        "compass-ui.md",
        """
        title: "Compass UI"
        type: entity
        scope: project
        summary: "Next.js healthcare app."
        context_keys: [compass, compass-ui, compass-platform]
        tags: [nextjs, healthcare-ai]
        updated: 2026-01-01
        """,
        "Compass UI is configured through [[Pulsar]].",
    )

    # Dotted repo directory (`example.com`) plus a misspelling alias. Incomplete normalization broke
    # the first; the second guards the `pastuer-ui` typo case.
    write_page(
        entities,
        "brian-overview.md",
        """
        title: "Brian Labs"
        type: entity
        scope: company
        summary: "Clinical AI safety company."
        context_keys: [brian, brian-org, brianai]
        aliases: [brian-ai]
        tags: [clinical-ai, safety]
        updated: 2026-01-01
        """,
        "Brian Labs builds [[Pulsar]].",
    )

    # Link target referenced by title, whose FILENAME differs from its title. Resolving links by
    # filename instead of title once reported this page as both a dead link and an orphan.
    write_page(
        concepts,
        "themars.md",
        """
        title: "ThemaRS Pipeline"
        type: concept
        scope: project
        summary: "End-to-end Pulsar pipeline stages."
        tags: [pipeline]
        updated: 2026-01-01
        """,
        "Part of [[Pulsar]].",
    )

    # Orphan: nothing links to it.
    write_page(
        concepts,
        "lonely.md",
        """
        title: "Lonely Concept"
        type: concept
        scope: research
        summary: "Nothing points here."
        tags: [orphaned]
        updated: 2026-01-01
        """,
        "This page has no incoming links and links to [[Pulsar]].",
    )

    # Dead link + missing required frontmatter (`scope`), for the auditor.
    write_page(
        concepts,
        "broken.md",
        """
        title: "Broken Page"
        type: concept
        summary: "Intentionally invalid."
        tags: [broken]
        updated: 2026-01-01
        """,
        "Points at [[No Such Page]] which does not exist.",
    )

    # Resolves ONLY via `repo:`. Deliberately has no context_keys and a title that does not appear
    # in any path, so it isolates the +6 repo signal. Without this page, a broken repo matcher still
    # passes every test because context_keys quietly covers for it.
    # Filename is deliberately unrelated to the remote basename, so neither the stem nor the title
    # can accidentally satisfy the test.
    write_page(
        entities,
        "monitoring.md",
        """
        title: "Monitoring Service"
        type: entity
        scope: project
        summary: "Resolves by git remote alone."
        repo: git@github.com:Brian-Org/watchtower.git
        tags: [monitoring]
        updated: 2026-01-01
        """,
        "Linked from [[Pulsar]] conceptually.",
    )

    # Its only key is a strict PREFIX of a longer path component. Padded matching must reject it;
    # unpadded substring matching would wrongly fire. This isolates the hyphen/substring invariant
    # at the resolver level rather than only in the `_padded` unit tests.
    write_page(
        concepts,
        "prefix-trap.md",
        """
        title: "Prefix Trap"
        type: concept
        scope: engineering
        summary: "Guards against substring matching."
        context_keys: [thema]
        updated: 2026-01-01
        """,
        "Reached from [[Pulsar]].",
    )

    # Navigation files: must be EXCLUDED from the page set, and must not count as link sources.
    (root / "index.md").write_text("# Index\n\n- [[Pulsar]]\n- [[Lonely Concept]]\n", encoding="utf-8")
    (root / "log.md").write_text("# Log\n\n## [2026-01-01] ingest | thing\n", encoding="utf-8")
    (root / "tags.md").write_text("# Tags Index\n\n- python: [[Pulsar]]\n", encoding="utf-8")
    (root / "backlinks.md").write_text("# Backlinks Index\n\n## [[Pulsar]]\n- [[Compass UI]]\n", encoding="utf-8")

    return root


@pytest.fixture
def db(wiki_dir: Path) -> WikiDatabase:
    return WikiDatabase(wiki_dir)


@pytest.fixture
def live_db() -> WikiDatabase:
    """The real wiki tree, for content-health contract tests."""
    return WikiDatabase(REPO_ROOT / "wiki")
