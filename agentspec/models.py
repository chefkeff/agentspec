from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional

class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"

@dataclass
class MethodDef:
    name: str
    signature: str

@dataclass
class ServiceDef:
    name: str
    methods: List[MethodDef] = field(default_factory=list)

@dataclass
class TypeDef:
    name: str
    definition: str

@dataclass
class InvariantDef:
    kind: str  # 'why', 'rule', 'invariant'
    key: str
    content: str

@dataclass
class TaskDef:
    id: str
    status: TaskStatus
    title: str
    dependencies: List[str] = field(default_factory=list)
    refs: List[str] = field(default_factory=list)
    touches: List[str] = field(default_factory=list)
    test_cmd: Optional[str] = None

@dataclass
class SpecDoc:
    version: str = "0.1"
    meta: Dict[str, str] = field(default_factory=dict)
    types: List[TypeDef] = field(default_factory=list)
    services: List[ServiceDef] = field(default_factory=list)
    invariants: List[InvariantDef] = field(default_factory=list)
    tasks: List[TaskDef] = field(default_factory=list)

    def validate_dag(self) -> List[str]:
        """Validate task dependencies and detect cycles or missing tasks."""
        errors = []
        task_ids = {t.id for t in self.tasks}
        
        # Check missing dependencies
        for t in self.tasks:
            for dep in t.dependencies:
                if dep not in task_ids:
                    errors.append(f"Task '{t.id}' depends on non-existent task '{dep}'")
                    
        # Check cycles using DFS
        adj: Dict[str, List[str]] = {t.id: t.dependencies for t in self.tasks}
        visited: Dict[str, int] = {}  # 0 = unvisited, 1 = visiting, 2 = visited

        def dfs(node: str, path: List[str]):
            visited[node] = 1
            for parent in adj.get(node, []):
                state = visited.get(parent, 0)
                if state == 1:
                    cycle_str = " -> ".join(path + [parent])
                    errors.append(f"Dependency cycle detected: {cycle_str}")
                elif state == 0:
                    dfs(parent, path + [parent])
            visited[node] = 2

        for t in self.tasks:
            if visited.get(t.id, 0) == 0:
                dfs(t.id, [t.id])

        return errors

    def to_aspec(self) -> str:
        """Serialize SpecDoc back into canonical .aspec format."""
        lines = [f"@spec {self.version}"]
        if self.meta:
            meta_str = " | ".join(f'{k}: "{v}"' for k, v in self.meta.items())
            lines.append(f"@meta {meta_str}")
        lines.append("")

        if self.invariants:
            lines.append("# RATIONALES & INVARIANTS")
            for inv in self.invariants:
                lines.append(f'!{inv.kind} {inv.key}: "{inv.content}"')
            lines.append("")

        if self.types:
            lines.append("# TYPES & CONTRACTS")
            for t in self.types:
                lines.append(f"!type {t.name} = {t.definition}")
            lines.append("")

        if self.services:
            for s in self.services:
                lines.append(f"!svc {s.name}:")
                for m in s.methods:
                    lines.append(f"  {m.name}{m.signature}")
                lines.append("")

        if self.tasks:
            lines.append("# TASK EXECUTION DAG")
            for t in self.tasks:
                if t.status == TaskStatus.DONE:
                    mark = "x"
                elif t.status == TaskStatus.IN_PROGRESS:
                    mark = ">"
                else:
                    mark = " "
                tags = []
                if t.dependencies:
                    tags.append(f"[after: {', '.join(t.dependencies)}]")
                if t.refs:
                    tags.append(f"[ref: {', '.join(t.refs)}]")
                if t.touches:
                    tags.append(f"[touch: {', '.join(t.touches)}]")
                if t.test_cmd:
                    tags.append(f"[test: {t.test_cmd}]")
                tag_str = f" {' '.join(tags)}" if tags else ""
                lines.append(f"[{mark}] {t.id}: {t.title}{tag_str}")

        return "\n".join(lines).strip() + "\n"
