# Dogfood tests

These tests exercise the real CLI and MCP server against a temporary copy of this checkout.

```bash
uv run pytest tests/dogfood -q
```

A private `benchmarks/` retrieval dataset is optional and not required for the open-source suite.
