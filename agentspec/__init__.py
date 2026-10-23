"""
agentspec (`aspec`): A token-efficient project specification, task graph,
and state serialization framework for AI agents.
"""

from .models import SpecDoc, TypeDef, ServiceDef, MethodDef, InvariantDef, TaskDef, TaskStatus
from .parser import parse_spec, ParseError
from .transpiler import to_markdown
from .benchmark import benchmark_spec, count_tokens
from .packer import pack_for_task, format_subagent_prompt
from .patcher import apply_mutations, patch_file, PatchError
from .linter import lint_spec, LintIssue
from .ingester import ingest_codebase
from .dashboard import generate_html_dashboard
from .scheduler import get_task_schedule, TaskSchedule, ParallelBatch

__version__ = "0.3.0"

__all__ = [
    "SpecDoc",
    "TypeDef",
    "ServiceDef",
    "MethodDef",
    "InvariantDef",
    "TaskDef",
    "TaskStatus",
    "parse_spec",
    "ParseError",
    "to_markdown",
    "benchmark_spec",
    "count_tokens",
    "pack_for_task",
    "format_subagent_prompt",
    "apply_mutations",
    "patch_file",
    "PatchError",
    "lint_spec",
    "LintIssue",
    "ingest_codebase",
    "generate_html_dashboard",
    "get_task_schedule",
    "TaskSchedule",
    "ParallelBatch",
]
