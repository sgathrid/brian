"""Context resolution — the highest-risk logic in the project.

This has regressed three separate times:

1. bash `grep -qw`: POSIX treats `-` as a non-word character, so the fragment `ui` matched
   `compass-ui` and `ai` matched `clinical-ai`. Unrelated pages filled the session brief.
2. The Python rewrite dropped `context_keys`/`aliases`/`repo` entirely and used naked substring
   matching, reintroducing the same false positives plus body-match noise.
3. `_norm` collapsed only `_`, space and `/`, so `Repos/Front Ends/example.com` kept its dot and the key
   `brian` no longer appeared as `-brian-`; and `repo:` was compared as a whole git remote, which can
   never occur in a local path, so the strongest signal never fired at all.

The invariant is DIRECTIONAL: whole declared values are searched for inside the normalized path,
never the reverse. `compass-ui` matches `/Repos/compass-UI` but not `/Repos/erdos-web-chat-ui`.
(Note `_norm` treats `-` and `/` as the same delimiter, so a one-word key like `ui` does match a
directory called `compass-UI`. That is accepted — see
`test_hyphen_and_path_separator_are_deliberately_equivalent`.)

Assert real page names. Never soften a case to `isinstance(result, list)` — an empty list satisfies
that, which is exactly how a fully broken resolver once passed its tests.
"""

from __future__ import annotations

import pytest
from conftest import write_page

from wikicli.core.page import WikiDatabase
from wikicli.core.resolve import ContextResolver, _norm, _padded, _repo_basename


def stems(pages) -> list[str]:
    return [p.stem for p in pages]


class TestNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Compass UI", "compass-ui"),
            ("compass_ui", "compass-ui"),
            ("/Repos/Front Ends/example.com", "repos-front-ends-example-com"),
            ("brian-overview.github.io", "brian-overview-github-io"),
            ("git@github.com:Org/repo.git", "git-github-com-org-repo-git"),
            ("A  (weird)  name!", "a-weird-name"),
            ("---leading-and-trailing---", "leading-and-trailing"),
            ("", ""),
        ],
    )
    def test_every_non_alphanumeric_run_becomes_one_dash(self, raw: str, expected: str):
        assert _norm(raw) == expected

    def test_padding_wraps_values_for_whole_unit_matching(self):
        assert _padded("compass-ui") == "-compass-ui-"
        assert _padded("") == ""

    def test_fragment_does_not_match_padded_value(self):
        """The core invariant: padded matching prevents substring matches inside words."""
        haystack = _padded("/Users/me/Repos/compass-UI")
        assert _padded("compass-ui") in haystack
        assert _padded("compass") in haystack, "a genuine component still matches"

        unrelated_haystack = _padded("/Users/me/Repos/quip")
        assert _padded("ui") not in unrelated_haystack, (
            "bare fragment must not match inside unhyphenated words like quip"
        )

    def test_declared_key_must_not_match_a_merely_similar_directory(self):
        """The directional invariant — this is the exact bug that shipped twice.

        Whole declared values are searched for inside the normalized path, NEVER the reverse. The
        original implementation tokenized the *path* and looked for those tokens inside the *keys*,
        so the path token `ui` matched the key `compass-ui` and dragged Compass UI into every
        session held in an unrelated `*-ui` directory.
        """
        assert _padded("compass-ui") in _padded("/Users/me/Repos/compass-UI")
        assert _padded("compass-ui") not in _padded("/Users/me/Repos/erdos-web-chat-ui")
        assert _padded("clinical-ai") not in _padded("/Users/me/Repos/Front Ends/clinical-sentinel")

    def test_hyphen_and_path_separator_are_deliberately_equivalent(self):
        """Known, accepted ambiguity — pinned so nobody "fixes" it and breaks real matching.

        `_norm` collapses `/` and `-` to the same delimiter, so `compass-UI` is indistinguishable
        from `compass/UI`. A one-word key like `ui` therefore matches a directory named
        `compass-UI`. Harmless in practice — nobody declares `ui` as a context key — and treating
        hyphens as significant instead would stop `compass-ui` matching the real directory
        `compass-UI`, which is the case that actually matters.
        """
        assert _padded("ui") in _padded("/Users/me/Repos/compass-UI")


class TestRepoBasename:
    @pytest.mark.parametrize(
        "remote,expected",
        [
            ("git@github.com:Brian-Org/pulsar.git", "pulsar"),
            ("https://github.com/Brian-Org/pulsar.git", "pulsar"),
            ("git@github.com:Org/compass-platform.git", "compass-platform"),
            ("pulsar", "pulsar"),
        ],
    )
    def test_basename_extracted_from_remote(self, remote: str, expected: str):
        assert _repo_basename(remote) == expected

    def test_repo_signal_actually_fires(self, db: WikiDatabase):
        """`repo:` is weighted highest (+6) and is the portable signal.

        `sentinel.md` declares ONLY `repo: …/watchtower.git` — no context_keys, and a title that
        appears in no path. So this can only pass if the remote's basename is what gets matched.
        Asserting against a page that also has context_keys hides the bug entirely: mutation testing
        showed the earlier version of this test passing with repo matching completely broken.
        """
        assert stems(ContextResolver(db).resolve_context("/Users/me/Repos/watchtower", limit=1)) == ["monitoring"]


class TestContextResolution:
    """The regression table. Every row previously produced a wrong answer."""

    @pytest.mark.parametrize(
        "cwd,expected_first",
        [
            ("/Users/me/Repos/core/pulsar", "pulsar"),
            ("/Users/me/Repos/compass-UI", "compass-ui"),
            ("/Users/me/Repos/compass-platform", "compass-ui"),
            # Company keys are brian/brian-overview — not derived from example.com domain.
            ("/Users/me/Repos/brian-overview", "brian-overview"),
            ("/Users/me/Repos/brian", "brian-overview"),
        ],
    )
    def test_known_directories_resolve_to_their_page(self, db: WikiDatabase, cwd: str, expected_first: str):
        assert stems(ContextResolver(db).resolve_context(cwd, limit=3))[:1] == [expected_first]

    @pytest.mark.parametrize(
        "cwd",
        [
            "/Users/me/Repos/erdos-web-chat-ui",  # `ui` must not match `compass-ui`
            "/Users/me/Repos/Orchestrator-UI",  # same, different casing
            "/Users/me/Repos/Front Ends/clinical-sentinel",  # `clinical` must not match `clinical-ai`
            "/Users/me/Repos/totally-unrelated",
        ],
    )
    def test_unrelated_directories_resolve_to_nothing(self, db: WikiDatabase, cwd: str):
        """A false positive is worse than no result: it displaces a real page from the top-3 brief."""
        assert ContextResolver(db).resolve_context(cwd, limit=3) == []

    def test_key_that_is_a_prefix_of_a_path_component_does_not_match(self, db: WikiDatabase):
        """`prefix-trap.md` declares only `context_keys: [thema]`.

        `thema` is a strict prefix of the directory `themars-web`. Padded whole-unit matching must
        reject it; naive substring matching accepts it. This is the resolver-level guard for the
        hyphen bug — the `_padded` unit tests alone did not catch a mutation that dropped the padding
        inside the scoring loop.
        """
        resolved = stems(ContextResolver(db).resolve_context("/Users/me/Repos/themars-web", limit=5))
        assert "prefix-trap" not in resolved

    def test_that_same_key_matches_its_own_exact_component(self, db: WikiDatabase):
        """The other half: padding must not make legitimate whole-value matches fail."""
        assert "prefix-trap" in stems(ContextResolver(db).resolve_context("/Users/me/Repos/thema", limit=5))

    def test_alias_resolves(self, db: WikiDatabase):
        """`aliases:` exists so a renamed or misspelled directory still finds its page."""
        assert stems(ContextResolver(db).resolve_context("/Users/me/Repos/brian-ai", limit=1)) == ["brian-overview"]

    def test_empty_and_root_input_are_safe(self, db: WikiDatabase):
        assert ContextResolver(db).resolve_context("", limit=3) == []
        assert ContextResolver(db).resolve_context("/", limit=3) == []

    def test_limit_is_honoured(self, db: WikiDatabase):
        assert len(ContextResolver(db).resolve_context("/Users/me/Repos/pulsar", limit=1)) <= 1

    def test_returns_existing_absolute_paths(self, db: WikiDatabase):
        for path in ContextResolver(db).resolve_context("/Users/me/Repos/pulsar", limit=3):
            assert path.is_absolute()
            assert path.is_file()


class TestRanking:
    def test_stronger_signal_outranks_weaker(self, wiki_dir):
        """A page matching by context_keys (+5) must outrank one matching only by tag (+1)."""
        write_page(
            wiki_dir / "concepts",
            "tag-only.md",
            'title: "Tag Only"\ntype: concept\nscope: research\ntags: [pulsar]\nupdated: 2026-01-01',
        )
        db = WikiDatabase(wiki_dir)
        ranked = stems(ContextResolver(db).resolve_context("/Users/me/Repos/pulsar", limit=5))
        assert ranked[0] == "pulsar"
        assert "tag-only" in ranked
        assert ranked.index("pulsar") < ranked.index("tag-only")

    def test_body_text_does_not_create_context_matches(self, wiki_dir):
        """Body prose is searched by `find`, never by `context`.

        Body matching was briefly weighted +2 and flooded the brief with pages that merely mentioned
        a word in passing.
        """
        write_page(
            wiki_dir / "concepts",
            "mentions-only.md",
            'title: "Mentions Only"\ntype: concept\nscope: research\nupdated: 2026-01-01',
            "This page discusses pulsar timing at length but declares no keys.",
        )
        db = WikiDatabase(wiki_dir)
        assert "mentions-only" not in stems(ContextResolver(db).resolve_context("/Users/me/Repos/pulsar", limit=5))
