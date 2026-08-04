#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mcp>=1.0.0,<2",
#     "jupyter_client>=8.0.0",
#     "ipykernel>=6.0.0",
# ]
# ///
"""
Sage REPL MCP Server

A minimal MCP server providing persistent Sage sessions via Jupyter kernel.

Usage:
    uv run sage_repl_server.py
    uv run sage_repl_server.py --directory /path/to/experiment

Claude Code config (~/.claude.json or project .mcp.json):
    {
      "mcpServers": {
        "sage-repl": {
          "command": "uv",
          "args": ["run", "/path/to/sage_repl_server.py"]
        }
      }
    }

With working directory:
    {
      "mcpServers": {
        "sage-repl": {
          "command": "uv",
          "args": ["run", "/path/to/sage_repl_server.py", "--directory", "/path/to/experiment"]
        }
      }
    }
"""

import argparse
import asyncio
import atexit
import os
import re
import shutil
from queue import Empty
from typing import Any

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# --- Kernel Management ---


# GAP crash detection - interrupt after repeated crashes to prevent fork bomb
GAP_CRASH_PATTERN = re.compile(r"Gap crashed|Restarting Gap", re.IGNORECASE)
GAP_CRASH_LIMIT = 3


class SageKernel:
    """Manages a Sage IPython kernel for persistent code execution."""

    def __init__(self):
        if not shutil.which("sage"):
            raise FileNotFoundError("'sage' not found in PATH")

        # Use sage's Python - inject KernelSpec directly to bypass lookup
        sage_cmd = [
            "sage",
            "-python",
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ]
        self.km = KernelManager()
        self.km._kernel_spec = KernelSpec(
            resource_dir="",
            argv=sage_cmd,
            display_name="Sage",
            language="python",
        )
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=30)

        # Import sage.all at startup
        self._execute_silent("from sage.all import *")

    def _execute_silent(self, code: str) -> None:
        """Execute code without returning output."""
        msg_id = self.kc.execute(code, silent=True)
        # Wait for completion
        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=30)
                if (
                    msg["msg_type"] == "status"
                    and msg["content"]["execution_state"] == "idle"
                    and msg["parent_header"].get("msg_id") == msg_id
                ):
                    break
            except Empty:
                break

    def execute(self, code: str, timeout: int = 60) -> dict[str, Any]:
        """Execute code and return structured output."""
        msg_id = self.kc.execute(code, silent=False, store_history=True)

        output = {"stdout": "", "stderr": "", "result": None, "error": None}
        gap_crash_count = 0

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=timeout)

                # Only process our messages
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue

                msg_type = msg["msg_type"]
                content = msg["content"]

                if msg_type == "stream":
                    if content["name"] == "stdout":
                        output["stdout"] += content["text"]
                    elif content["name"] == "stderr":
                        output["stderr"] += content["text"]
                        # Detect GAP crash loop to prevent fork bomb
                        if GAP_CRASH_PATTERN.search(content["text"]):
                            gap_crash_count += 1
                            if gap_crash_count >= GAP_CRASH_LIMIT:
                                self.interrupt()
                                output["error"] = (
                                    f"GAP crash loop detected ({gap_crash_count} crashes). "
                                    "Execution interrupted to prevent runaway processes. "
                                    "Avoid structure_description() on this input."
                                )
                                break
                elif msg_type == "execute_result":
                    output["result"] = content["data"].get("text/plain", "")
                elif msg_type == "error":
                    output["error"] = f"{content['ename']}: {content['evalue']}"
                elif msg_type == "status" and content["execution_state"] == "idle":
                    break
            except Empty:
                output["error"] = "Timeout: kernel may still be busy"
                break

        return output

    def interrupt(self) -> None:
        """Interrupt the current execution."""
        self.km.interrupt_kernel()

    def shutdown(self) -> None:
        """Shutdown the kernel."""
        try:
            self.kc.stop_channels()
            if self.km.is_alive():
                self.km.shutdown_kernel(now=True)
        except Exception:
            pass


# --- Global State ---

sessions: dict[str, SageKernel] = {}


def cleanup():
    """Cleanup all sessions on exit."""
    for kernel in sessions.values():
        kernel.shutdown()


atexit.register(cleanup)


# --- MCP Server ---

server = Server("sage-repl")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sage_start",
            description="Start a new Sage session. Returns session ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Optional session ID (default: 'default')",
                        "default": "default",
                    }
                },
            },
        ),
        Tool(
            name="sage_exec",
            description="Execute Sage/Python code in a session. Returns result, stdout, stderr.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Sage/Python code to execute",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (default: 'default')",
                        "default": "default",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default: 60)",
                        "default": 60,
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="sage_interrupt",
            description="Interrupt a running computation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (default: 'default')",
                        "default": "default",
                    }
                },
            },
        ),
        Tool(
            name="sage_stop",
            description="Stop a Sage session and free resources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (default: 'default')",
                        "default": "default",
                    }
                },
            },
        ),
        Tool(
            name="sage_list",
            description="List all active Sage sessions.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "sage_start":
        session_id = arguments.get("session_id", "default")

        if session_id in sessions:
            return [
                TextContent(type="text", text=f"Session '{session_id}' already exists")
            ]

        try:
            sessions[session_id] = SageKernel()
            return [
                TextContent(
                    type="text", text=f"Session '{session_id}' started. Sage is ready."
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to start session: {e}")]

    elif name == "sage_exec":
        session_id = arguments.get("session_id", "default")
        code = arguments.get("code", "")
        timeout = arguments.get("timeout", 60)

        if session_id not in sessions:
            # Auto-start session
            try:
                sessions[session_id] = SageKernel()
            except Exception as e:
                return [TextContent(type="text", text=f"Failed to start session: {e}")]

        kernel = sessions[session_id]
        output = await asyncio.to_thread(kernel.execute, code, timeout)

        # Format output
        parts = []
        if output["result"]:
            parts.append(output["result"])
        if output["stdout"]:
            parts.append(f"[stdout]\n{output['stdout']}")
        if output["stderr"]:
            parts.append(f"[stderr]\n{output['stderr']}")
        if output["error"]:
            parts.append(f"[error]\n{output['error']}")

        result = "\n".join(parts) if parts else "(no output)"
        return [TextContent(type="text", text=result)]

    elif name == "sage_interrupt":
        session_id = arguments.get("session_id", "default")

        if session_id not in sessions:
            return [TextContent(type="text", text=f"No session '{session_id}'")]

        sessions[session_id].interrupt()
        return [TextContent(type="text", text=f"Interrupted session '{session_id}'")]

    elif name == "sage_stop":
        session_id = arguments.get("session_id", "default")

        if session_id not in sessions:
            return [TextContent(type="text", text=f"No session '{session_id}'")]

        sessions[session_id].shutdown()
        del sessions[session_id]
        return [TextContent(type="text", text=f"Session '{session_id}' stopped")]

    elif name == "sage_list":
        if not sessions:
            return [TextContent(type="text", text="No active sessions")]

        lines = [f"Active sessions: {len(sessions)}"]
        for sid in sessions:
            lines.append(f"  - {sid}")
        return [TextContent(type="text", text="\n".join(lines))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sage REPL MCP Server")
    parser.add_argument(
        "--directory",
        type=str,
        default=None,
        help="Change to this directory before starting the server",
    )
    args = parser.parse_args()

    if args.directory:
        os.chdir(args.directory)

    asyncio.run(main())
