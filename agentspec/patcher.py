import re
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from .models import SpecDoc, TaskDef, TaskStatus, InvariantDef
from .parser import parse_spec

class PatchError(Exception):
    pass

def apply_mutations(doc: SpecDoc, mutations: List[str], verify: bool = False) -> SpecDoc:
    """
    Apply a series of micro-mutations to an in-memory SpecDoc.
    Supported mutations:
      - <task_id>=done | in_progress | todo
      - +task <id>: <title> [after: <deps>] [ref: ...] [touch: ...] [test: ...]
      - +why <key>: "<content>"
      - +rule <key>: "<content>"
    """
    task_map: Dict[str, TaskDef] = {t.id: t for t in doc.tasks}

    for mut in mutations:
        mut = mut.strip()
        if not mut:
            continue

        # Status update: T2=done or T2=in_progress
        if "=" in mut and not mut.startswith("+"):
            task_id, new_status_str = [x.strip() for x in mut.split("=", 1)]
            if task_id not in task_map:
                raise PatchError(f"Cannot update status: task '{task_id}' not found.")

            status_str_clean = new_status_str.lower().replace("-", "_")
            if status_str_clean in ("done", "x"):
                target_task = task_map[task_id]
                if verify and target_task.test_cmd:
                    res = subprocess.run(target_task.test_cmd, shell=True, capture_output=True, text=True)
                    if res.returncode != 0:
                        err_msg = res.stderr.strip() or res.stdout.strip()
                        raise PatchError(f"Verification test failed for task '{task_id}': {err_msg}")
                target_task.status = TaskStatus.DONE
            elif status_str_clean in ("in_progress", "progress", ">"):
                task_map[task_id].status = TaskStatus.IN_PROGRESS
            elif status_str_clean in ("todo", "pending", " "):
                task_map[task_id].status = TaskStatus.TODO
            else:
                raise PatchError(f"Invalid status '{new_status_str}' for task '{task_id}'")
            continue

        # Add task: +task T7: title [after: T5, T6] [ref: ...] [touch: ...] [test: ...]
        if mut.startswith("+task"):
            content = mut[len("+task"):].strip()
            task_match = re.match(r"^([\w\.\-]+)\s*:\s*(.+)$", content)
            if not task_match:
                raise PatchError(f"Invalid task syntax: '{mut}'. Expected: +task ID: Title [after: deps]")
            tid, rest = task_match.groups()
            if tid in task_map:
                raise PatchError(f"Task '{tid}' already exists in spec.")

            deps: List[str] = []
            refs: List[str] = []
            touches: List[str] = []
            test_cmd: Optional[str] = None

            for tag_match in re.finditer(r"\[(after|ref|touch|test):\s*([^\]]+)\]", rest):
                tag_type, tag_val = tag_match.group(1), tag_match.group(2).strip()
                if tag_type == "after":
                    deps = [d.strip() for d in tag_val.split(",") if d.strip()]
                elif tag_type == "ref":
                    refs = [r.strip() for r in tag_val.split(",") if r.strip()]
                elif tag_type == "touch":
                    touches = [t.strip() for t in tag_val.split(",") if t.strip()]
                elif tag_type == "test":
                    test_cmd = tag_val

            title = re.sub(r"\[(after|ref|touch|test):\s*[^\]]+\]", "", rest).strip()

            new_task = TaskDef(
                id=tid.strip(),
                status=TaskStatus.TODO,
                title=title,
                dependencies=deps,
                refs=refs,
                touches=touches,
                test_cmd=test_cmd
            )
            doc.tasks.append(new_task)
            task_map[tid] = new_task
            continue

        # Add invariant: +why key: "content" or +rule key: "content"
        inv_match = re.match(r"^\+(why|rule|invariant)\s+([\w\.\-]+)\s*:\s*(.+)$", mut)
        if inv_match:
            kind, key, content = inv_match.groups()
            clean_content = content.strip().strip('"').strip("'")
            doc.invariants.append(InvariantDef(kind=kind, key=key.strip(), content=clean_content))
            continue

        raise PatchError(f"Unrecognized mutation: '{mut}'")

    # Validate DAG after patching
    dag_errors = doc.validate_dag()
    if dag_errors:
        raise PatchError(f"Patch created DAG errors: {'; '.join(dag_errors)}")

    return doc

def patch_file(filepath: Path, mutations: List[str], verify: bool = False) -> SpecDoc:
    content = filepath.read_text(encoding="utf-8")
    doc = parse_spec(content)
    updated_doc = apply_mutations(doc, mutations, verify=verify)
    filepath.write_text(updated_doc.to_aspec(), encoding="utf-8")
    return updated_doc
