"""Unit tests for TTY menu renderer."""

import unittest

from wikicli.ui.menu import run_menu


class TestMenu(unittest.TestCase):
    def test_run_menu_non_interactive_tuple_options(self):
        options = [
            ("claude", "Claude Code", "~/.claude"),
            ("codex", "Codex CLI", "~/.codex"),
        ]
        result = run_menu(
            "Which agent integrations do you want to configure?",
            options=options,
            non_interactive=True,
        )
        self.assertEqual(result, "claude codex")

    def test_run_menu_single_select_non_interactive(self):
        options = [
            ("full", "Full Reset"),
            ("scope", "Scope Reset"),
            ("orphans", "Orphan Sweep"),
        ]
        result = run_menu(
            "Select reset type:",
            options=options,
            non_interactive=True,
            single_select=True,
        )
        self.assertEqual(result, "full")

    def test_run_confirm_non_interactive(self):
        from wikicli.ui.menu import run_confirm

        res_false = run_confirm("Confirm reset?", default=False, non_interactive=True)
        self.assertFalse(res_false)

    def test_run_scroll_viewer_non_interactive(self):
        import io
        import sys

        from wikicli.ui.menu import run_scroll_viewer

        items = [f"file_{i}.md" for i in range(50)]
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            run_scroll_viewer("Files targeted (50 files):", items, max_visible=20, non_interactive=True)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("Files targeted (50 files):", output)
        self.assertIn("file_0.md", output)
        self.assertIn("file_19.md", output)
        self.assertIn("... and 30 more files", output)


if __name__ == "__main__":
    unittest.main()
