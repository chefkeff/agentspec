import pytest
from pathlib import Path
from agentspec.parser import parse_spec
from agentspec.models import TaskStatus
from agentspec.packer import pack_for_task, format_subagent_prompt
from agentspec.patcher import apply_mutations
from agentspec.linter import lint_spec
from agentspec.ingester import ingest_codebase
from agentspec.dashboard import generate_html_dashboard

V2_SAMPLE = """@spec 0.1
@meta app: "v2-test"

!type Item = { id: str, price: int }
!type DeadType = { val: str }

!svc ItemService:
  getItem(id: str) -> Item

!why perf: "In-memory caching"

[x] T1: initialize db
[x] T2: create item schema [after: T1]
[>] T3: implement item service [after: T2]
[ ] T4: setup payment gateway [after: T2]
[ ] T5: checkout flow integration [after: T3, T4]
[ ] T6: isolated orphan task
"""

def test_packer_ancestor_slicing():
    doc = parse_spec(V2_SAMPLE)
    # T3 depends on T2, T2 depends on T1.
    # T4, T5, T6 are future or unrelated, should be sliced out!
    packed = pack_for_task(doc, "T3")
    task_ids = [t.id for t in packed.tasks]
    assert task_ids == ["T1", "T2", "T3"]
    assert "T4" not in task_ids
    assert "T5" not in task_ids
    assert "T6" not in task_ids

    prompt = format_subagent_prompt(doc, "T3")
    assert "Task T3" in prompt
    assert "!svc ItemService" in prompt

def test_patcher_mutations():
    doc = parse_spec(V2_SAMPLE)
    mutations = [
        "T3=done",
        "+task T7: performance benchmark [after: T5]",
        '+rule cache: "TTL strictly 3600 seconds"'
    ]
    updated = apply_mutations(doc, mutations)
    t3 = next(t for t in updated.tasks if t.id == "T3")
    assert t3.status == TaskStatus.DONE

    t7 = next(t for t in updated.tasks if t.id == "T7")
    assert t7.dependencies == ["T5"]

    rule = next(inv for inv in updated.invariants if inv.key == "cache")
    assert rule.content == "TTL strictly 3600 seconds"

def test_linter_guards():
    doc = parse_spec(V2_SAMPLE)
    issues = lint_spec(doc)

    # DeadType should be caught as unused
    unused = [i for i in issues if i.code == "W002_UNUSED_TYPE"]
    assert any("DeadType" in i.message for i in unused)

    # T6 should be flagged as orphan
    orphans = [i for i in issues if i.code == "I001_ORPHAN_TASK"]
    assert any("T6" in i.message for i in orphans)

    # Now simulate an invalid state: T5 done while T4 is pending
    invalid_spec = """@spec 0.1
[ ] T1: task 1
[x] T2: task 2 [after: T1]
"""
    bad_doc = parse_spec(invalid_spec)
    bad_issues = lint_spec(bad_doc)
    assert any(i.code == "E001_PRE_NOT_DONE" for i in bad_issues)

def test_ingester_python(tmp_path: Path):
    test_code = """
class OrderDto:
    order_id: str
    total: float

class OrderService:
    def create_order(self, customer_id: str) -> str:
        pass
    def cancel_order(self, order_id: str) -> bool:
        pass
"""
    py_file = tmp_path / "orders.py"
    py_file.write_text(test_code, encoding="utf-8")

    doc = ingest_codebase(tmp_path)
    assert any(t.name == "OrderDto" for t in doc.types)
    assert any(s.name == "OrderService" for s in doc.services)
    svc = next(s for s in doc.services if s.name == "OrderService")
    method_names = [m.name for m in svc.methods]
    assert "create_order" in method_names
    assert "cancel_order" in method_names

def test_dashboard_generator():
    doc = parse_spec(V2_SAMPLE)
    html = generate_html_dashboard(doc, V2_SAMPLE)
    assert "<!DOCTYPE html>" in html
    assert "mermaid" in html
    assert "v2-test" in html
    assert "ItemService" in html
