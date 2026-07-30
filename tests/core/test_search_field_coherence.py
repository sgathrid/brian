"""Focused contract tests for two-term search field coherence.

Live-corpus holdouts freeze Brian seed-wiki behavior. Synthetic cases isolate the
rule: for two-term queries, coherent evidence ranks above terms assembled across
fields. Incoherent candidates remain visible with provenance and a demotion
reason. Exact body phrases and genuine title/name anchors are coherent; one- and
three-plus-term behavior is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_page

from wikicli.core.knowledge import query_knowledge
from wikicli.core.page import WikiDatabase
from wikicli.core.resolve import ContextResolver, SearchHit

ROOT = Path(__file__).resolve().parents[2]

# Brian seed wiki is intentionally tiny (one overview page). Hold out a few
# queries that must keep ranking that page first after search-scoring changes.
CURRENT_CORPUS_HOLDOUT = (
    ("What is Brian?", "brian-overview"),
    ("wiki company info", "brian-overview"),
    ("cross-LLM context engine", "brian-overview"),
    ("open-source context engine", "brian-overview"),
    ("central knowledge base", "brian-overview"),
)


def _resolver(tmp_path: Path, *, frontmatter: str, body: str = "") -> ContextResolver:
    wiki_dir = tmp_path / "wiki"
    write_page(
        wiki_dir / "concepts",
        "record.md",
        f'title: "Neutral Record"\ntype: concept\nscope: company\nupdated: 2026-07-30\n{frontmatter}',
        body,
    )
    return ContextResolver(WikiDatabase(wiki_dir))


def _stems(resolver: ContextResolver, query: str) -> list[str]:
    return [hit.page.stem for hit in resolver.search_keywords(query)]


def _hits(resolver: ContextResolver, query: str) -> list[SearchHit]:
    return resolver.search_keywords(query)


@pytest.mark.parametrize(("query", "expected"), CURRENT_CORPUS_HOLDOUT)
def test_current_corpus_holdout_preserves_top_result(query: str, expected: str) -> None:
    resolver = ContextResolver(WikiDatabase(ROOT / "wiki"))

    assert _stems(resolver, query)[0] == expected


@pytest.mark.parametrize(
    "frontmatter",
    (
        "context_keys: [orchid ledger]",
        "tags: [orchid, ledger]",
        'summary: "An orchid ledger records the evidence."',
    ),
)
def test_two_terms_in_one_discovery_field_are_supported(tmp_path: Path, frontmatter: str) -> None:
    resolver = _resolver(tmp_path, frontmatter=frontmatter)

    hits = _hits(resolver, "orchid ledger")
    assert [hit.page.stem for hit in hits] == ["record"]
    assert any(reason.startswith("field provenance:") for reason in hits[0].reasons)
    assert "incoherent evidence demoted" not in hits[0].reasons


@pytest.mark.parametrize(
    ("frontmatter", "body"),
    (
        ('context_keys: [orchid]\nsummary: "A ledger is discussed."', ""),
        ('tags: [orchid]\nsummary: "A ledger is discussed."', ""),
        ("context_keys: [orchid]\ntags: [ledger]", ""),
        ('summary: "Orchid notes."', "The ledger appears elsewhere."),
    ),
)
def test_two_generic_terms_scattered_across_fields_are_demoted(tmp_path: Path, frontmatter: str, body: str) -> None:
    wiki_dir = tmp_path / "wiki"
    write_page(
        wiki_dir / "concepts",
        "incidental.md",
        f'title: "Incidental Record"\ntype: concept\nscope: company\nupdated: 2026-07-30\n{frontmatter}',
        body,
    )
    write_page(
        wiki_dir / "concepts",
        "coherent.md",
        'title: "Coherent Record"\ntype: concept\nscope: company\nupdated: 2026-07-30',
        "A precise orchid ledger governs this workflow.",
    )
    for index in range(3):
        write_page(
            wiki_dir / "concepts",
            f"filler-{index}.md",
            f'title: "Filler {index}"\ntype: concept\nscope: company\nupdated: 2026-07-30',
            "Unrelated background material.",
        )
    hits = _hits(ContextResolver(WikiDatabase(wiki_dir)), "orchid ledger")

    assert [hit.page.stem for hit in hits] == ["coherent", "incidental"]
    incidental = hits[1]
    provenance = next(reason for reason in incidental.reasons if reason.startswith("field provenance:"))
    assert "orchid=" in provenance
    assert "ledger=" in provenance
    assert "incoherent evidence demoted" in incidental.reasons


def test_exact_body_phrase_is_supported(tmp_path: Path) -> None:
    resolver = _resolver(
        tmp_path,
        frontmatter='summary: "Unrelated notes."',
        body="A precise orchid ledger governs this workflow.",
    )

    hits = _hits(resolver, "orchid ledger")
    assert [hit.page.stem for hit in hits] == ["record"]
    assert "body phrase" in hits[0].reasons
    assert "incoherent evidence demoted" not in hits[0].reasons


def test_single_body_term_remains_supported(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path, frontmatter='summary: "Unrelated notes."', body="An orchid appears here.")

    assert _stems(resolver, "orchid") == ["record"]


def test_title_anchor_can_join_evidence_from_another_field(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    write_page(
        wiki_dir / "entities",
        "orchid.md",
        'title: "Orchid"\ntype: entity\nscope: company\nupdated: 2026-07-30',
        "The ledger records its work.",
    )
    resolver = ContextResolver(WikiDatabase(wiki_dir))

    assert _stems(resolver, "orchid ledger") == ["orchid"]


def test_detailed_query_keeps_existing_cross_field_behavior(tmp_path: Path) -> None:
    resolver = _resolver(
        tmp_path,
        frontmatter="context_keys: [orchid]",
        body="The ledger describes a tracing protocol.",
    )

    assert _stems(resolver, "orchid ledger tracing protocol") == ["record"]


def test_seed_wiki_coherent_phrase_outranks_scattered_two_term_noise(tmp_path: Path) -> None:
    """Multi-page synthetic stand-in for private-corpus sponsor/partner cases."""
    wiki_dir = tmp_path / "wiki"
    write_page(
        wiki_dir / "projects",
        "sponsor-discovery-pilot.md",
        (
            'title: "Sponsor Discovery Pilot"\ntype: project\nscope: company\n'
            "updated: 2026-07-30\ncontext_keys: [sponsor discovery]\n"
            'summary: "A sponsor discovery pilot for trial recruitment."'
        ),
        "The pilot runs sponsor discovery end to end.",
    )
    write_page(
        wiki_dir / "entities",
        "sponsor.md",
        (
            'title: "Sponsor"\ntype: entity\nscope: company\nupdated: 2026-07-30\n'
            "context_keys: [sponsor]\ntags: [partner]"
        ),
        "Sponsor relationships and trial recruitment notes.",
    )
    write_page(
        wiki_dir / "concepts",
        "noise.md",
        (
            'title: "Noise Page"\ntype: concept\nscope: company\nupdated: 2026-07-30\n'
            'context_keys: [sponsor]\nsummary: "Discovery is mentioned in passing."'
        ),
        "Unrelated background material.",
    )
    resolver = ContextResolver(WikiDatabase(wiki_dir))
    hits = _hits(resolver, "sponsor discovery")
    stems = [hit.page.stem for hit in hits]

    assert stems[0] == "sponsor-discovery-pilot"
    assert "noise" in stems
    noise = hits[stems.index("noise")]
    assert any(reason.startswith("field provenance:") for reason in noise.reasons)
    assert "incoherent evidence demoted" in noise.reasons

    same_field = _stems(resolver, "trial recruitment")
    assert "sponsor-discovery-pilot" in same_field
    assert "sponsor" in same_field
    assert _stems(resolver, "sponsor pilot")[0] in {"sponsor", "sponsor-discovery-pilot"}


def test_seed_wiki_unsupported_founding_question_abstains() -> None:
    result = query_knowledge(ROOT, "Who founded Brian and how many employees are there?")

    assert result.no_results is True
    assert result.hits == []
