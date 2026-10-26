import re
from typing import Any, Dict, List, Optional, Tuple
from .models import SpecDoc, TypeDef, ServiceDef, MethodDef, InvariantDef, TaskDef, TaskStatus

class ParseError(Exception):
    def __init__(self, message: str, line_num: int, line: str):
        super().__init__(f"Line {line_num}: {message} -> '{line}'")
        self.line_num = line_num
        self.line = line

TAG_PATTERN = r"\[(after|ref|touch|test|by):\s*([^\]]+)\]"

def parse_task_tags(rest: str) -> Tuple[str, Dict[str, Any]]:
    """Split a task line remainder into its title and TaskDef keyword fields."""
    tags: Dict[str, Any] = {}
    for tag_match in re.finditer(TAG_PATTERN, rest):
        tag_type, tag_val = tag_match.group(1), tag_match.group(2).strip()
        if tag_type == "after":
            tags["dependencies"] = [d.strip() for d in tag_val.split(",") if d.strip()]
        elif tag_type == "ref":
            tags["refs"] = [r.strip() for r in tag_val.split(",") if r.strip()]
        elif tag_type == "touch":
            tags["touches"] = [t.strip() for t in tag_val.split(",") if t.strip()]
        elif tag_type == "test":
            tags["test_cmd"] = tag_val
        elif tag_type == "by":
            tags["owner"] = tag_val

    title = re.sub(TAG_PATTERN, "", rest).strip()
    return title, tags

class Parser:
    def __init__(self, content: str):
        self.raw_content = content
        self.lines = content.splitlines()

    def parse(self) -> SpecDoc:
        doc = SpecDoc()
        current_service: Optional[ServiceDef] = None

        for idx, raw_line in enumerate(self.lines, start=1):
            line = raw_line.strip()

            # Ignore empty lines and full-line comments
            if not line or line.startswith("#"):
                continue

            # Check if this is an indented method inside current_service
            if raw_line.startswith("  ") or raw_line.startswith("\t"):
                if current_service is not None:
                    method_match = re.match(r"^(\w+)\s*\((.*?)\)\s*(?:->\s*(.+))?$", line)
                    if method_match:
                        name, args, ret = method_match.groups()
                        sig = f"({args.strip()}) -> {ret.strip() if ret else 'void'}"
                        current_service.methods.append(MethodDef(name=name.strip(), signature=sig))
                        continue
                    else:
                        raise ParseError("Invalid service method declaration", idx, raw_line)
                else:
                    raise ParseError("Indented line without parent service declaration", idx, raw_line)

            # Not an indented line, so reset current_service
            current_service = None

            # 1. Spec version
            if line.startswith("@spec"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    doc.version = parts[1].strip()
                continue

            # 2. Metadata: @meta k1: v1 | k2: v2
            if line.startswith("@meta"):
                content_part = line[len("@meta"):].strip()
                pairs = [p.strip() for p in content_part.split("|")]
                for pair in pairs:
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        doc.meta[k.strip()] = self._strip_quotes(v.strip())
                continue

            # 3. Type definition: !type Name = definition
            if line.startswith("!type"):
                match = re.match(r"^!type\s+(\w+)\s*=\s*(.+)$", line)
                if match:
                    t_name, t_def = match.groups()
                    doc.types.append(TypeDef(name=t_name.strip(), definition=t_def.strip()))
                    continue
                else:
                    raise ParseError("Invalid !type syntax. Expected: !type Name = ...", idx, raw_line)

            # 4. Service declaration: !svc Name:
            if line.startswith("!svc"):
                match = re.match(r"^!svc\s+(\w+)\s*:$", line)
                if match:
                    s_name = match.group(1).strip()
                    current_service = ServiceDef(name=s_name)
                    doc.services.append(current_service)
                    continue
                else:
                    raise ParseError("Invalid !svc syntax. Expected: !svc Name:", idx, raw_line)

            # 5. Invariants: !why, !rule, !invariant
            if line.startswith(("!why", "!rule", "!invariant")):
                match = re.match(r"^!(why|rule|invariant)\s+([\w\.\-]+)\s*:\s*(.+)$", line)
                if match:
                    kind, key, val = match.groups()
                    doc.invariants.append(InvariantDef(
                        kind=kind,
                        key=key.strip(),
                        content=self._strip_quotes(val.strip())
                    ))
                    continue
                else:
                    raise ParseError(f"Invalid {line.split()[0]} syntax. Expected: !kind key: \"value\"", idx, raw_line)

            # 6. Tasks: [x], [>], [ ]
            task_match = re.match(r"^\[([ xX>])\]\s*([\w\.\-]+)\s*:\s*(.+)$", line)
            if task_match:
                status_char, task_id, rest = task_match.groups()
                status = TaskStatus.TODO
                if status_char in ("x", "X"):
                    status = TaskStatus.DONE
                elif status_char == ">":
                    status = TaskStatus.IN_PROGRESS

                title, tags = parse_task_tags(rest)

                doc.tasks.append(TaskDef(id=task_id.strip(), status=status, title=title, **tags))
                continue

            raise ParseError("Unrecognized syntax or command", idx, raw_line)

        return doc

    def _strip_quotes(self, s: str) -> str:
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

def parse_spec(content: str) -> SpecDoc:
    parser = Parser(content)
    return parser.parse()
