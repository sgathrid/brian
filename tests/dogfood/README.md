# Dogfood verification

These tests exercise the real process boundaries, not mocked tool functions.

```bash
uv run pytest tests/dogfood -v
uv run python benchmarks/evaluate_search.py --repeat 100 --cold-repeat 10
wiki gen && wiki ingest check && wiki audit
```

The dogfood suite launches the MCP server over stdio, exercises the real structured CLI through stdin/stdout,
compares transport results, rejects changed approvals, and mutates only disposable wiki copies. The top-level
`benchmarks/` directory remains separate because it is a versioned retrieval dataset and evaluator, not test-only data.
