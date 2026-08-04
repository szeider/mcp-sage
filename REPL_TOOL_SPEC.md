# REPL Tool Specification for Claude Code

## Motivation

Mathematical exploration, debugging, and data analysis often require **iterative, stateful interaction** with an interpreter. Current tools require reloading state in each Bash call, adding friction and context waste.

**Example pain point** (from this session):
```python
# Every Sage call must reload:
graphs_list = [Graph(line.strip()) for line in open('file.g6')]
# Then do one analysis step
# Repeat for next insight...
```

A stateful REPL would allow building up context incrementally.

---

## Core API

### `ReplStart`

Start a new REPL session.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `interpreter` | string | yes | Interpreter to launch: `python`, `sage`, `node`, `psql`, `sqlite3`, `julia`, `R`, etc. |
| `working_dir` | string | no | Working directory (default: current) |
| `env` | object | no | Additional environment variables |
| `timeout_idle` | number | no | Kill session after N seconds of inactivity (default: 600) |
| `name` | string | no | Human-readable session name for tracking |

**Returns:**
```json
{
  "session_id": "repl_a1b2c3",
  "interpreter": "sage",
  "status": "ready",
  "banner": "SageMath version 10.6..."
}
```

---

### `ReplSend`

Send a command to an active REPL session and receive output.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session ID from ReplStart |
| `command` | string | yes | Command/code to execute (can be multi-line) |
| `timeout` | number | no | Max seconds to wait for output (default: 30) |
| `wait_for_prompt` | boolean | no | Wait until prompt returns (default: true) |

**Returns:**
```json
{
  "session_id": "repl_a1b2c3",
  "output": "True\n[1, 2, 3, 4, 5]",
  "error": null,
  "execution_time_ms": 142,
  "status": "ready"
}
```

**Multi-line input:**
```
ReplSend(session_id, """
def analyze(G):
    aut = G.automorphism_group()
    return aut.order(), aut.orbits()
""")
```

---

### `ReplRead`

Read any new output without sending a command. Useful for long-running computations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `timeout` | number | no | Max seconds to wait (default: 5) |

**Returns:**
```json
{
  "session_id": "repl_a1b2c3",
  "output": "Iteration 50/100...\n",
  "status": "busy"
}
```

---

### `ReplClose`

Terminate a REPL session.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `save_history` | boolean | no | Save command history to file (default: false) |

**Returns:**
```json
{
  "session_id": "repl_a1b2c3",
  "status": "closed",
  "total_commands": 47,
  "session_duration_s": 1823
}
```

---

### `ReplList`

List active REPL sessions.

**Returns:**
```json
{
  "sessions": [
    {
      "session_id": "repl_a1b2c3",
      "interpreter": "sage",
      "name": "graph-analysis",
      "status": "ready",
      "idle_seconds": 45,
      "command_count": 23
    }
  ]
}
```

---

## Session Status Values

| Status | Meaning |
|--------|---------|
| `starting` | Interpreter launching |
| `ready` | Awaiting input |
| `busy` | Executing command |
| `error` | Interpreter crashed (can attempt restart) |
| `closed` | Session terminated |

---

## Behavior Requirements

### 1. Prompt Detection
The tool must detect when the interpreter is ready for input. Strategies:
- Regex matching known prompts (`>>> `, `sage: `, `> `, `# `, etc.)
- Configurable prompt pattern per interpreter
- Timeout fallback

### 2. Output Cleaning
Strip interpreter noise from output:
- **Remove prompt prefixes** (no more `sage: sage: sage:` clutter)
- Separate stdout/stderr if possible
- Preserve ANSI colors optionally

### 3. Error Handling
```json
{
  "output": "",
  "error": "NameError: name 'foo' is not defined",
  "traceback": "File \"<stdin>\", line 1...",
  "status": "ready"
}
```
Errors should not kill the session unless the interpreter crashes.

### 4. Multi-line Input Handling
Detect incomplete input (e.g., open parenthesis, `def` without body) and:
- Wait for continuation, OR
- Send appropriate continuation to interpreter

### 5. Interrupt Support
```
ReplSend(session_id, command="", interrupt=true)  // Send Ctrl+C
```

### 6. Session Persistence
Sessions survive across Claude Code tool calls within a conversation. Optional: serialize session state for handoff.

---

## Example Workflow

```python
# Start session
s = ReplStart(interpreter="sage", name="analysis")

# Load data once
ReplSend(s.session_id, """
graphs_list = [Graph(line.strip()) for line in open('connected_not_in_hog.g6')]
print(f"Loaded {len(graphs_list)} graphs")
""")
# Output: "Loaded 181 graphs"

# Iterative exploration
ReplSend(s.session_id, "G = graphs_list[147]; G.order(), G.size()")
# Output: "(9, 24)"

ReplSend(s.session_id, "G.automorphism_group().order()")
# Output: "1152"

ReplSend(s.session_id, "G.automorphism_group().orbits()")
# Output: "[[0,1,2,3,4,5,6,7], [8]]"

# Aha! Try construction
ReplSend(s.session_id, """
test = graphs.CompleteBipartiteGraph(4,4).join(graphs.CompleteGraph(1))
test.is_isomorphic(G)
""")
# Output: "True"

# Done
ReplClose(s.session_id)
```

---

## Implementation Notes

### PTY Requirement
Must use pseudo-terminal (PTY) to properly handle:
- Line buffering
- Prompt detection
- Ctrl+C interrupts
- Password prompts (if needed)

### Concurrency
Support multiple simultaneous sessions (e.g., Sage + SQLite + Node).

### Resource Limits
- Max concurrent sessions per conversation (e.g., 5)
- Auto-close after idle timeout
- Memory limits per session

---

## Interpreter-Specific Configurations

| Interpreter | Prompt Pattern | Notes |
|-------------|----------------|-------|
| `python` | `>>> ` / `... ` | Handle multiline with `... ` |
| `sage` | `sage: ` | Long startup time (~3s) |
| `node` | `> ` | `.editor` mode for multiline |
| `psql` | `=> ` / `-> ` | Transaction state in prompt |
| `sqlite3` | `sqlite> ` | |
| `julia` | `julia> ` | |
| `R` | `> ` / `+ ` | |
| `gdb` | `(gdb) ` | Debugging workflows |

---

## Priority: HIGH

For mathematical research, data exploration, and debugging workflows, this would be the single most impactful tool addition. The current heredoc workaround is functional but:
- Wastes tokens reloading state
- Breaks flow of exploration
- Makes iterative refinement tedious

A stateful REPL transforms Claude Code from "batch executor" to "pair programming partner."
