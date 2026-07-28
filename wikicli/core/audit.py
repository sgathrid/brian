"""Wiki consistency, link validation, and schema auditor."""

from pathlib import Path

from .page import WikiDatabase, is_nav


def audit_wiki(db: WikiDatabase) -> tuple[bool, list[str]]:
    """Validates schema, detects dead links, and identifies orphan pages."""
    report_lines: list[str] = []
    has_errors = False

    required_fm = ["title", "type", "scope"]

    # Filter to content pages only (excluding navigation/meta pages)
    content_pages = [p for p in db.pages.values() if not is_nav(p.filepath)]
    incoming_links: dict[Path, set[Path]] = {p.filepath: set() for p in content_pages}

    for page in content_pages:
        rel_path = page.filepath.name

        # 1. Frontmatter Validation
        missing_keys = [k for k in required_fm if k not in page.frontmatter or not page.frontmatter[k]]
        if missing_keys:
            has_errors = True
            report_lines.append(f"✕ {rel_path}: Missing frontmatter field(s): {', '.join(missing_keys)}")

        # 2. Link Resolution & Dead Link Detection
        for link in page.wikilinks:
            resolved = db.resolve_link(link)
            if resolved:
                if resolved.filepath in incoming_links and resolved.filepath != page.filepath:
                    incoming_links[resolved.filepath].add(page.filepath)
            else:
                has_errors = True
                report_lines.append(f"✕ {rel_path}: Dead wikilink [[{link}]]")

    # 3. Orphan Page Detection (content pages with 0 incoming links from other content pages)
    orphans = [p.name for p, links in incoming_links.items() if len(links) == 0]
    if orphans:
        report_lines.append("")
        report_lines.append(f"▲ Orphan pages ({len(orphans)}):")
        for orphan in sorted(orphans):
            report_lines.append(f"   - {orphan}")

    return not has_errors, report_lines
