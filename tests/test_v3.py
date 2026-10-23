import pytest
from agentspec.parser import parse_spec
from agentspec.models import TaskStatus
from agentspec.packer import pack_for_task
from agentspec.scheduler import get_task_schedule
from agentspec.patcher import apply_mutations, PatchError

RICH_SPEC = """@spec 0.1
@meta app: "ecommerce"

!type Token = { id: str, exp: int }
!type Order = { order_id: str, token: Token }
!type Unrelated = { flag: bool }

!svc AuthService:
  login(u: str) -> Token

!svc UnrelatedService:
  noop() -> bool

[x] T1: initialize schema [touch: src/schema.sql]
[ ] T2: implement auth [after: T1] [ref: AuthService] [touch: src/auth.py] [test: echo auth_ok]
[ ] T3: implement order [after: T1] [ref: Order] [touch: src/order.py] [test: echo order_ok]
[ ] T4: audit auth logs [after: T1] [touch: src/auth.py]
"""

def test_parse_and_serialize_rich_tags():
    doc = parse_spec(RICH_SPEC)
    t2 = next(t for t in doc.tasks if t.id == "T2")
    assert t2.dependencies == ["T1"]
    assert t2.refs == ["AuthService"]
    assert t2.touches == ["src/auth.py"]
    assert t2.test_cmd == "echo auth_ok"
    assert t2.title == "implement auth"

    aspec_out = doc.to_aspec()
    assert "[after: T1]" in aspec_out
    assert "[ref: AuthService]" in aspec_out
    assert "[touch: src/auth.py]" in aspec_out
    assert "[test: echo auth_ok]" in aspec_out

def test_deep_contract_pruning():
    doc = parse_spec(RICH_SPEC)
    sliced = pack_for_task(doc, "T2", prune_contracts=True)

    # Should retain AuthService and transitive Token type
    svc_names = [s.name for s in sliced.services]
    type_names = [t.name for t in sliced.types]

    assert "AuthService" in svc_names
    assert "UnrelatedService" not in svc_names

    assert "Token" in type_names
    assert "Unrelated" not in type_names

def test_parallel_scheduling_and_file_conflicts():
    doc = parse_spec(RICH_SPEC)
    schedule = get_task_schedule(doc)

    # Ready tasks: T2, T3, T4 (all depend on completed T1)
    ready_ids = [t.id for t in schedule.ready_tasks]
    assert set(ready_ids) == {"T2", "T3", "T4"}

    # File conflict on src/auth.py between T2 and T4
    assert "src/auth.py" in schedule.file_conflicts
    assert set(schedule.file_conflicts["src/auth.py"]) == {"T2", "T4"}

    # Batch 1 should execute T2 and T3 in parallel (disjoint files)
    # Batch 2 should execute T4 (since src/auth.py was locked in Batch 1)
    assert len(schedule.parallel_batches) == 2
    batch1_ids = {t.id for t in schedule.parallel_batches[0].tasks}
    batch2_ids = {t.id for t in schedule.parallel_batches[1].tasks}

    assert batch1_ids == {"T2", "T3"}
    assert batch2_ids == {"T4"}

def test_verification_gate_success():
    doc = parse_spec(RICH_SPEC)
    # T2 has test: echo auth_ok (exit code 0)
    apply_mutations(doc, ["T2=done"], verify=True)
    t2 = next(t for t in doc.tasks if t.id == "T2")
    assert t2.status == TaskStatus.DONE

def test_verification_gate_failure():
    spec = """@spec 0.1
[ ] T1: flaky task [test: exit 1]
"""
    doc = parse_spec(spec)
    with pytest.raises(PatchError) as exc_info:
        apply_mutations(doc, ["T1=done"], verify=True)
    assert "Verification test failed for task 'T1'" in str(exc_info.value)

def test_patch_add_task_with_rich_tags():
    doc = parse_spec(RICH_SPEC)
    apply_mutations(doc, [
        "+task T5: process payments [after: T2, T3] [ref: Order] [touch: src/pay.py] [test: echo pay_ok]"
    ])
    t5 = next(t for t in doc.tasks if t.id == "T5")
    assert t5.id == "T5"
    assert t5.title == "process payments"
    assert t5.dependencies == ["T2", "T3"]
    assert t5.refs == ["Order"]
    assert t5.touches == ["src/pay.py"]
    assert t5.test_cmd == "echo pay_ok"
