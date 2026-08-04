# Sage REPL MCP Server

## Overview

The Sage REPL MCP Server provides persistent SageMath sessions for Claude Code through the Model Context Protocol (MCP). It solves a fundamental friction in mathematical exploration: the need to reload state on every command execution.

Without this server, each SageMath computation runs in isolation. Loading a list of graphs, analyzing one, then querying its automorphism group would require reloading the graph file three times. The Sage REPL server maintains state across calls, enabling true iterative exploration.

## Architecture

The server uses the Jupyter kernel protocol rather than raw subprocess management. This design choice provides several advantages:

- **Reliable prompt detection** without regex matching interpreter prompts
- **Clean separation** of stdout, stderr, and return values
- **Native interrupt support** via kernel messaging
- **Robust multi-line input handling**

The implementation injects a `KernelSpec` directly into the `KernelManager` rather than requiring system-wide kernelspec installation. This allows the server to launch SageMath's bundled Python with ipykernel without modifying the user's Jupyter configuration.

On session start, the server automatically imports `sage.all`, making all Sage functions immediately available without explicit imports.

## Tools

The server exposes five MCP tools:

| Tool | Purpose |
|------|---------|
| `sage_start` | Create a new named session (auto-created on first `sage_exec` if omitted) |
| `sage_exec` | Execute Sage/Python code and return results |
| `sage_interrupt` | Send Ctrl+C to stop long-running computations |
| `sage_stop` | Terminate a session and release resources |
| `sage_list` | Show all active sessions |

The `sage_exec` tool returns structured output with separate fields for the expression result, stdout, stderr, and any errors. A configurable timeout (default 60 seconds) prevents hanging on infinite loops.

## Implementation

The entire server is a single Python file (~300 lines) using UV's inline dependency syntax (PEP 723). Dependencies include `mcp`, `jupyter_client`, and `ipykernel`. Running the server requires only:

```bash
uv run sage_repl_server.py
```

Key technical details:

- **Async execution**: Code execution runs in a thread via `asyncio.to_thread()`, keeping the MCP server responsive and allowing interrupts to work
- **Automatic cleanup**: An `atexit` handler shuts down all kernels when the server terminates
- **Multiple sessions**: The server supports named sessions for different workstreams

## Configuration

Add to Claude Code's MCP config (`.mcp.json` or `~/.claude.json`):

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

## Requirements

- SageMath 10.6+ in PATH
- Python 3.11+
- UV package manager

## Example Workflow

```python
# Load graphs once
sage_exec("graphs = [Graph(l) for l in open('data.g6')]")

# Explore interactively
sage_exec("G = graphs[42]; G.order(), G.size()")
sage_exec("G.automorphism_group().order()")
sage_exec("G.is_planar()")

# State persists across all calls
```

This transforms Claude Code from a batch executor into a genuine pair programming partner for mathematical research.
