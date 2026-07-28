"""Keyword search and tag queries.

`find` is the agent's on-demand path: unlike `context`, it deliberately DOES search body prose. The
two must not be conflated — body matching in `context` floods the session brief, while its absence in
`find` makes search useless.
"""

from __future__ import annotations

from conftest import write_page

from wikicli.core.page import WikiDatabase
from wikicli.core.resolve import ContextResolver, find_literal


def stems(pages) -> list[str]:
    return [p.stem for p in pages]


class TestFindKeywords:
    def test_matches_title(self, db: WikiDatabase):
        assert "pulsar" in stems(ContextResolver(db).find_keywords("Pulsar"))

    def test_matches_exact_multiword_title(self, db: WikiDatabase):
        assert stems(ContextResolver(db).find_keywords("Brian Labs"))[0] == "brian-org"

    def test_matches_tag(self, db: WikiDatabase):
        assert "compass-ui" in stems(ContextResolver(db).find_keywords("nextjs"))

    def test_matches_body_prose(self, db: WikiDatabase):
        """This is the difference from `context`: `find` reads the body."""
        assert "brian-org" in stems(ContextResolver(db).find_keywords("builds"))

    def test_title_outranks_body(self, wiki_dir):
        """A page named for the term beats one that merely mentions it."""
        write_page(
            wiki_dir / "concepts",
            "mentions-topology.md",
            'title: "Unrelated Page"\ntype: concept\nscope: research\nupdated: 2026-01-01',
            "A passing mention of topology in prose.",
        )
        write_page(
            wiki_dir / "concepts",
            "topology.md",
            'title: "Topology"\ntype: concept\nscope: research\nupdated: 2026-01-01',
            "The subject itself.",
        )
        db = WikiDatabase(wiki_dir)
        ranked = stems(ContextResolver(db).find_keywords("topology"))
        assert ranked[0] == "topology"
        assert ranked.index("topology") < ranked.index("mentions-topology")

    def test_case_insensitive(self, db: WikiDatabase):
        assert stems(ContextResolver(db).find_keywords("PULSAR")) == stems(ContextResolver(db).find_keywords("pulsar"))

    def test_multi_token_query_scores_cumulatively(self, db: WikiDatabase):
        """Both terms hitting the same page should rank it above a single-term match."""
        ranked = stems(ContextResolver(db).find_keywords("compass healthcare-ai"))
        assert ranked[0] == "compass-ui"

    def test_ignores_knowledge_base_routing_words(self, db: WikiDatabase):
        assert stems(ContextResolver(db).find_keywords("wiki company info"))[0] == "brian-org"

    def test_ignores_conversational_scaffolding_around_a_named_page(self, db: WikiDatabase):
        ranked = stems(ContextResolver(db).find_keywords("Tell me about Pulsar in plain English"))
        assert ranked[0] == "pulsar"

    def test_named_page_survives_unseen_explanatory_language(self, db: WikiDatabase):
        ranked = stems(ContextResolver(db).find_keywords("Explain Pulsar simply to a new colleague"))
        assert ranked[0] == "pulsar"

    def test_conversational_scaffolding_does_not_change_named_page_ranking(self, db: WikiDatabase):
        resolver = ContextResolver(db)
        assert (
            stems(resolver.find_keywords("Pulsar"))[:3]
            == stems(resolver.find_keywords("Tell me about Pulsar in plain English"))[:3]
        )

    def test_comparison_prefers_a_synthesis_without_known_company_names(self, wiki_dir):
        write_page(
            wiki_dir / "concepts",
            "alpha.md",
            'title: "Alpha"\ntype: project\nscope: project\nsummary: "Alpha analyzes inputs."\nupdated: 2026-01-01',
            "Alpha works alongside [[Beta]].",
        )
        write_page(
            wiki_dir / "concepts",
            "beta.md",
            'title: "Beta"\ntype: project\nscope: project\nsummary: "Beta checks outputs."\nupdated: 2026-01-01',
            "Beta works alongside [[Alpha]].",
        )
        write_page(
            wiki_dir / "concepts",
            "suite.md",
            'title: "Product Suite"\ntype: synthesis\nscope: company\nsummary: "Alpha and Beta cover inputs and outputs."\ncontext_keys: [compare Alpha and Beta, how Alpha and Beta fit together]\nupdated: 2026-01-01',
            "The synthesis connects [[Alpha]] and [[Beta]].",
        )

        ranked = stems(ContextResolver(WikiDatabase(wiki_dir)).find_keywords("Compare Alpha and Beta"))

        assert ranked[0] == "suite"

    def test_rejects_body_coincidences_without_specific_discovery_metadata(self, wiki_dir):
        write_page(
            wiki_dir / "concepts",
            "incidental.md",
            'title: "Incidental Notes"\ntype: concept\nscope: company\nupdated: 2026-01-01',
            "Brian current count policy employee insurance.",
        )
        resolver = ContextResolver(WikiDatabase(wiki_dir))
        assert resolver.find_keywords("Brian employee count policy") == []

    def test_no_match_returns_empty(self, db: WikiDatabase):
        assert ContextResolver(db).find_keywords("zzzznotpresent") == []

    def test_empty_query_returns_empty(self, db: WikiDatabase):
        assert ContextResolver(db).find_keywords("") == []
        assert ContextResolver(db).find_keywords("   ") == []

    def test_limit_is_honoured(self, db: WikiDatabase):
        assert len(ContextResolver(db).find_keywords("a", limit=2)) <= 2

    def test_exact_title_beats_repeated_body_mentions(self, wiki_dir):
        write_page(
            wiki_dir / "concepts",
            "pulsar-notes.md",
            'title: "Notes"\ntype: concept\nscope: project\nupdated: 2026-01-01',
            "Pulsar " * 50,
        )
        ranked = stems(ContextResolver(WikiDatabase(wiki_dir)).find_keywords("Pulsar"))
        assert ranked[0] == "pulsar"

    def test_word_tokens_do_not_match_inside_unrelated_words(self, wiki_dir):
        write_page(
            wiki_dir / "concepts",
            "chair.md",
            'title: "Chair Notes"\ntype: concept\nscope: project\nupdated: 2026-01-01',
            "Chair stair affair.",
        )
        ranked = stems(ContextResolver(WikiDatabase(wiki_dir)).find_keywords("AI"))
        assert "chair" not in ranked

    def test_query_coverage_beats_single_common_term(self, wiki_dir):
        write_page(
            wiki_dir / "concepts",
            "orchestration.md",
            'title: "Orchestration Notes"\ntype: concept\nscope: project\nupdated: 2026-01-01',
            "Orchestration is discussed at length. " * 20,
        )
        ranked = stems(ContextResolver(WikiDatabase(wiki_dir)).find_keywords("Pulsar orchestration stages"))
        assert "themars" in ranked
        assert "orchestration" not in ranked

    def test_explain_reports_score_contributions(self, db: WikiDatabase):
        hit = ContextResolver(db).search_keywords("Pulsar", limit=1)[0]
        assert hit.page.stem == "pulsar"
        assert hit.score > 0
        assert any("title" in reason for reason in hit.reasons)

    def test_rebuilding_search_index_is_idempotent(self, db: WikiDatabase):
        resolver = ContextResolver(db)
        initial = resolver.search_keywords("Pulsar")

        resolver._build_search_index()

        assert resolver.search_keywords("Pulsar") == initial


class TestFindLiteral:
    def test_returns_exact_matching_lines(self, wiki_dir):
        matches = find_literal(WikiDatabase(wiki_dir), "Pulsar depends")
        assert [(match.page.stem, match.line_number) for match in matches] == [("pulsar", 12)]

    def test_is_case_sensitive_by_default(self, db: WikiDatabase):
        assert find_literal(db, "PULSAR DEPENDS") == []

    def test_can_ignore_case(self, db: WikiDatabase):
        assert find_literal(db, "PULSAR DEPENDS", ignore_case=True)

    def test_does_not_rank_or_expand_the_query(self, db: WikiDatabase):
        assert find_literal(db, "Pulsr") == []


class TestFindTags:
    def test_lists_all_tags_when_no_target(self, db: WikiDatabase):
        tags = dict(ContextResolver(db).find_tags())
        for expected in ("python", "nextjs", "clinical-ai", "orphaned"):
            assert expected in tags

    def test_groups_pages_under_their_tag(self, db: WikiDatabase):
        tags = dict(ContextResolver(db).find_tags())
        assert stems(tags["python"]) == ["pulsar"]

    def test_exact_tag_filter(self, db: WikiDatabase):
        result = ContextResolver(db).find_tags("nextjs")
        assert len(result) == 1
        tag, pages = result[0]
        assert tag == "nextjs"
        assert stems(pages) == ["compass-ui"]

    def test_tag_filter_is_exact_not_substring(self, db: WikiDatabase):
        """Querying `ai` must not return `clinical-ai` or `healthcare-ai`.

        Substring tag matching is the same false-positive class as the resolver bug.
        """
        assert ContextResolver(db).find_tags("ai") == []

    def test_tag_filter_is_case_insensitive_and_strips_hash(self, db: WikiDatabase):
        assert len(ContextResolver(db).find_tags("NEXTJS")) == 1
        assert len(ContextResolver(db).find_tags("#nextjs")) == 1

    def test_unknown_tag_returns_empty(self, db: WikiDatabase):
        assert ContextResolver(db).find_tags("nosuchtag") == []
