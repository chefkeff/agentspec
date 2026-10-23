import pytest
from agentspec.parser import parse_spec, ParseError
from agentspec.models import TaskStatus
from agentspec.transpiler import to_markdown
from agentspec.benchmark import benchmark_spec

SAMPLE_SPEC = """@spec 0.1
@meta app: "test-app" | env: "prod"

!type User = { id: str, active: bool }

!svc UserService:
  getUser(id: str) -> User
  deleteUser(id: str) -> bool

!why db: "NoSQL chosen for dynamic user attribute schema"
!rule sec: "mTLS required between internal services"

[x] T1: create database connection
[>] T2: implement user service [after: T1]
[ ] T3: add caching layer [after: T2]
"""

def test_parse_valid_spec():
    doc = parse_spec(SAMPLE_SPEC)
    assert doc.version == "0.1"
    assert doc.meta["app"] == "test-app"
    assert doc.meta["env"] == "prod"
    
    assert len(doc.types) == 1
    assert doc.types[0].name == "User"
    
    assert len(doc.services) == 1
    assert doc.services[0].name == "UserService"
    assert len(doc.services[0].methods) == 2
    assert doc.services[0].methods[0].name == "getUser"
    
    assert len(doc.invariants) == 2
    assert doc.invariants[0].kind == "why"
    assert doc.invariants[0].key == "db"
    
    assert len(doc.tasks) == 3
    assert doc.tasks[0].status == TaskStatus.DONE
    assert doc.tasks[1].status == TaskStatus.IN_PROGRESS
    assert doc.tasks[2].status == TaskStatus.TODO
    assert doc.tasks[2].dependencies == ["T2"]
    
    errors = doc.validate_dag()
    assert errors == []

def test_dag_cycle_detection():
    cycle_spec = """@spec 0.1
[ ] T1: task 1 [after: T2]
[ ] T2: task 2 [after: T1]
"""
    doc = parse_spec(cycle_spec)
    errors = doc.validate_dag()
    assert any("cycle" in err.lower() for err in errors)

def test_dag_missing_dependency():
    missing_spec = """@spec 0.1
[ ] T1: task 1 [after: NON_EXISTENT]
"""
    doc = parse_spec(missing_spec)
    errors = doc.validate_dag()
    assert any("non-existent" in err.lower() for err in errors)

def test_transpile_markdown():
    doc = parse_spec(SAMPLE_SPEC)
    md = to_markdown(doc)
    assert "# test-app" in md
    assert "```mermaid" in md
    assert "T1 --> T2" in md
    assert "T2 --> T3" in md
    assert "type User = { id: str, active: bool };" in md

def test_benchmark():
    results = benchmark_spec(SAMPLE_SPEC)
    assert "cl100k_base" in results
    res = results["cl100k_base"]
    assert res.aspec_tokens > 0
    assert res.markdown_tokens > res.aspec_tokens
    assert res.reduction_percent > 0
