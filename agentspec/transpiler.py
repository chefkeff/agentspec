from .models import SpecDoc, TaskStatus

class Transpiler:
    def __init__(self, doc: SpecDoc):
        self.doc = doc

    def to_markdown(self) -> str:
        lines = []

        # Title & Meta
        app_name = self.doc.meta.get("app", "Project Specification")
        lines.append(f"# {app_name}")
        lines.append("")

        if self.doc.meta:
            lines.append("### Project Metadata")
            lines.append("| Key | Value |")
            lines.append("| :--- | :--- |")
            for k, v in self.doc.meta.items():
                lines.append(f"| **{k}** | `{v}` |")
            lines.append("")

        # Invariants & Rules
        if self.doc.invariants:
            lines.append("## Architectural Principles & Constraints")
            lines.append("")
            for inv in self.doc.invariants:
                kind_badge = inv.kind.upper()
                if inv.kind == "why":
                    badge_style = "Rationale"
                elif inv.kind == "rule":
                    badge_style = "Constraint"
                else:
                    badge_style = "Invariant"
                lines.append(f"- **[{badge_style}: `{inv.key}`]**: {inv.content}")
            lines.append("")

        # Contracts / Types
        if self.doc.types:
            lines.append("## Type Contracts")
            lines.append("")
            lines.append("```typescript")
            for t in self.doc.types:
                lines.append(f"type {t.name} = {t.definition};")
            lines.append("```")
            lines.append("")

        # Services
        if self.doc.services:
            lines.append("## Service Interfaces")
            lines.append("")
            for svc in self.doc.services:
                lines.append(f"### `interface {svc.name}`")
                lines.append("```typescript")
                for m in svc.methods:
                    lines.append(f"  {m.name}{m.signature};")
                lines.append("```")
                lines.append("")

        # Tasks & DAG
        if self.doc.tasks:
            lines.append("## Execution Plan & Task DAG")
            lines.append("")

            # Checklist
            for t in self.doc.tasks:
                if t.status == TaskStatus.DONE:
                    mark = "[x]"
                    status_text = "*(Done)*"
                elif t.status == TaskStatus.IN_PROGRESS:
                    mark = "[ ]"
                    status_text = "*(In Progress)*"
                else:
                    mark = "[ ]"
                    status_text = "*(Pending)*"

                dep_str = f" `after: {', '.join(t.dependencies)}`" if t.dependencies else ""
                lines.append(f"- {mark} **{t.id}**: {t.title} {status_text}{dep_str}")

            lines.append("")

            # Mermaid DAG
            lines.append("### Dependency Graph")
            lines.append("")
            lines.append("```mermaid")
            lines.append("graph TD")
            
            # Nodes
            for t in self.doc.tasks:
                safe_title = t.title.replace('"', "'")
                lines.append(f'    {t.id}["{t.id}: {safe_title}"]')

            # Edges
            for t in self.doc.tasks:
                for dep in t.dependencies:
                    lines.append(f"    {dep} --> {t.id}")

            # Styling
            done_ids = [t.id for t in self.doc.tasks if t.status == TaskStatus.DONE]
            prog_ids = [t.id for t in self.doc.tasks if t.status == TaskStatus.IN_PROGRESS]
            todo_ids = [t.id for t in self.doc.tasks if t.status == TaskStatus.TODO]

            if done_ids:
                lines.append(f"    style {','.join(done_ids)} fill:#d4edda,stroke:#28a745,stroke-width:2px")
            if prog_ids:
                lines.append(f"    style {','.join(prog_ids)} fill:#cce5ff,stroke:#007bff,stroke-width:2px")
            if todo_ids:
                lines.append(f"    style {','.join(todo_ids)} fill:#f8f9fa,stroke:#6c757d,stroke-width:1px")

            lines.append("```")
            lines.append("")

        return "\n".join(lines)

def to_markdown(doc: SpecDoc) -> str:
    return Transpiler(doc).to_markdown()
