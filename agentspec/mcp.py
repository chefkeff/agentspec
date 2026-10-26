import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any

from .parser import parse_spec
from .transpiler import to_markdown
from .packer import format_subagent_prompt
from .patcher import patch_file, PatchError
from .linter import lint_spec
from .scheduler import get_task_schedule

TOOLS = [
    {
        "name": "aspec_pack",
        "description": "Generate minimal token-efficient subagent context slice for a specific task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"},
                "task_id": {"type": "string", "description": "Target task ID (e.g. T2)"}
            },
            "required": ["file_path", "task_id"]
        }
    },
    {
        "name": "aspec_patch",
        "description": "Mutate task status or add new tasks in-place without rewriting the spec file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"},
                "mutations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of mutations, e.g. ['T2=in_progress@agent-a', 'T2=done', '+task T5: title [after: T4]']. Claims are rejected if the task is not ready, already claimed, or its [touch: ...] files are held by another in-progress task"
                },
                "verify": {"type": "boolean", "description": "Run [test: ...] verification gate before marking task done"}
            },
            "required": ["file_path", "mutations"]
        }
    },
    {
        "name": "aspec_ready",
        "description": "List unblocked tasks and conflict-free parallel swarm execution batches",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "aspec_verify",
        "description": "Run automated [test: ...] verification gate for a specific task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"},
                "task_id": {"type": "string", "description": "Target task ID to verify"}
            },
            "required": ["file_path", "task_id"]
        }
    },
    {
        "name": "aspec_lint",
        "description": "Lint an .aspec file for prerequisite order violations, orphan tasks, and dead types",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "aspec_render",
        "description": "Render .aspec into human-readable Markdown with Mermaid DAG",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .aspec file"}
            },
            "required": ["file_path"]
        }
    }
]

def handle_tool_call(name: str, args: Dict[str, Any]) -> str:
    fpath = Path(args.get("file_path", ""))
    if not fpath.exists():
        return f"Error: File '{fpath}' not found."

    content = fpath.read_text(encoding="utf-8")
    doc = parse_spec(content)

    if name == "aspec_pack":
        return format_subagent_prompt(doc, args["task_id"])
    elif name == "aspec_patch":
        muts = args.get("mutations", [])
        verify = args.get("verify", False)
        try:
            updated = patch_file(fpath, muts, verify=verify)
        except PatchError as pe:
            return f"Patch rejected: {pe}"
        return f"Successfully applied {len(muts)} mutations. Active tasks: {len(updated.tasks)}"
    elif name == "aspec_ready":
        schedule = get_task_schedule(doc)
        data = {
            "ready_tasks": [{"id": t.id, "title": t.title, "touches": t.touches, "test": t.test_cmd} for t in schedule.ready_tasks],
            "in_progress": [{"id": t.id, "title": t.title, "owner": t.owner} for t in schedule.in_progress_tasks],
            "waiting_on_locks": [{"id": t.id, "held_by": schedule.lock_holders[t.id]} for t in schedule.lock_waiting_tasks],
            "blocked": [{"id": t.id, "title": t.title} for t in schedule.blocked_tasks],
            "parallel_batches": [
                {
                    "batch": b.batch_index,
                    "task_ids": [t.id for t in b.tasks],
                    "touches": list(b.touched_files)
                }
                for b in schedule.parallel_batches
            ],
            "file_conflicts": schedule.file_conflicts
        }
        return json.dumps(data, indent=2)
    elif name == "aspec_verify":
        task_id = args.get("task_id")
        target_task = next((t for t in doc.tasks if t.id == task_id), None)
        if not target_task:
            return f"Error: Task '{task_id}' not found."
        if not target_task.test_cmd:
            return f"Task '{task_id}' has no [test: ...] verification command."
        res = subprocess.run(target_task.test_cmd, shell=True, capture_output=True, text=True)
        status = "PASSED" if res.returncode == 0 else f"FAILED (exit code {res.returncode})"
        return f"Test {status}:\n{res.stdout}\n{res.stderr}".strip()
    elif name == "aspec_lint":
        issues = lint_spec(doc)
        if not issues:
            return "No issues found. Spec and DAG are completely clean."
        return "\n".join(f"[{i.severity}] {i.code}: {i.message}" for i in issues)
    elif name == "aspec_render":
        return to_markdown(doc)
    else:
        return f"Unknown tool: {name}"

def run_mcp_server():
    """Runs a Model Context Protocol stdio JSON-RPC server."""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
            method = req.get("method")
            msg_id = req.get("id")

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "agentspec-mcp", "version": "0.2.0"},
                        "capabilities": {"tools": {}}
                    }
                }
            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": TOOLS}
                }
            elif method == "tools/call":
                params = req.get("params", {})
                t_name = params.get("name")
                t_args = params.get("arguments", {})
                output = handle_tool_call(t_name, t_args)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": output}]
                    }
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method {method} not found"}
                }

            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err_res = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)}
            }
            sys.stdout.write(json.dumps(err_res) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    run_mcp_server()
