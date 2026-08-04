# sage-mcp

An MCP server providing persistent [SageMath](https://www.sagemath.org) sessions
to any MCP-compatible host: Claude Code, Claude Desktop, Cursor, or an agent
harness such as [mcp-minion](https://github.com/szeider/mcp-solver).

Without this server, each SageMath computation runs in isolation: loading a
list of graphs, analyzing one, then querying its automorphism group would
require reloading the graph file three times. The Sage REPL server maintains
state across calls, enabling iterative mathematical exploration.

## Quickstart

The server is a single file using UV's inline dependency syntax (PEP 723):

```bash
uv run sage_repl_server.py
```

Claude Code / Claude Desktop config (`.mcp.json` or `~/.claude.json`):

```json
{
  "mcpServers": {
    "sage-repl": {
      "command": "uv",
      "args": ["run", "/path/to/sage_repl_server.py"]
    }
  }
}
```

An optional `--directory /path/to/workdir` argument sets the server's working
directory, so that relative paths in Sage code (e.g. a file written by the
agent) resolve inside a chosen run folder.

## Tools

| Tool | Purpose |
|------|---------|
| `sage_start` | Create a new named session (auto-created on first `sage_exec` if omitted) |
| `sage_exec` | Execute Sage/Python code and return results |
| `sage_interrupt` | Send Ctrl+C to stop long-running computations |
| `sage_stop` | Terminate a session and release resources |
| `sage_list` | Show all active sessions |

`sage_exec` returns structured output with separate fields for the expression
result, stdout, stderr, and any errors. A configurable timeout (default 60
seconds) prevents hanging on infinite loops.

## Architecture

The server drives SageMath through the Jupyter kernel protocol rather than raw
subprocess management: reliable prompt detection, clean separation of stdout /
stderr / return values, native interrupt support, and robust multi-line input.
It injects a `KernelSpec` directly into the `KernelManager`, so SageMath's
bundled Python runs with ipykernel without touching the user's Jupyter
configuration. On session start the server imports `sage.all`, making all Sage
functions immediately available. See `REPL_TOOL_SPEC.md` for the full tool
specification.

## Requirements

- SageMath 10.6+ in `PATH` (the server launches `sage -python`)
- [uv](https://docs.astral.sh/uv/)

Dependencies (resolved automatically by `uv run`): `mcp` (1.x low-level server
API; pinned `<2`), `jupyter_client`, `ipykernel`.

## Citation

This server was built for and used in the experiments of:

> *Neurosymbolic Discovery of Algebraic Graph Constructions.*
> NeSy 2026. (Full citation and archive DOI to appear.)

## License

MIT
