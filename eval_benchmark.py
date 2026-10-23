import sys
from pathlib import Path
from agentspec.models import SpecDoc, TaskStatus
from agentspec.parser import parse_spec
from agentspec.transpiler import to_markdown
from agentspec.packer import pack_for_task
from agentspec.benchmark import count_tokens

# 3 Diverse Real-World Project Specs
SPECS = {
    "Auth Gateway": """@spec 0.1
@meta app: "auth-gateway" | stack: "fastapi+redis" | owner: "security-infra"

# CONTRACTS
!type Token = { id: str, perms: str[], exp: int }
!type LoginReq = { email: str, password_hash: str }
!type User = { id: str, email: str, role: "admin" | "member" }

!svc AuthService:
  login(req: LoginReq) -> Token | Err(401)
  verify(token_str: str) -> bool
  revoke(token_id: str) -> bool

!svc UserService:
  getProfile(uid: str) -> User | Err(404)
  updateRole(uid: str, role: str) -> bool

# RATIONALES & INVARIANTS
!why auth: "stateless JWT to allow horizontal scaling behind Traefik"
!rule sec: "never persist plaintext passwords; bcrypt work factor >= 12"
!invariant rate_limit: "5 failed attempts per IP per 10min window"

# TASK DAG
[x] T1: initialize fastapi skeleton & docker-compose
[x] T2: setup postgres migration for user entities [after: T1]
[>] T3: implement AuthService token generation [after: T2]
[ ] T4: add redis blacklist for revoked tokens [after: T3]
[ ] T5: setup rate limiting middleware [after: T3]
[ ] T6: end-to-end integration tests [after: T4, T5]
""",

    "Commerce Engine": """@spec 0.1
@meta app: "commerce-engine" | arch: "event-driven" | runtime: "py311"

# CONTRACTS
!type Money = { cents: int, curr: "USD" | "EUR" | "GBP" }
!type CartItem = { sku: str, qty: int, price: Money }
!type Order = { id: str, user_id: str, items: CartItem[], total: Money, status: str }

!svc CartService:
  addItem(cart_id: str, item: CartItem) -> bool
  checkout(cart_id: str, idempotency_key: str) -> Order | Err(409)

!svc PaymentGateway:
  charge(order_id: str, amount: Money, token: str) -> bool | Err(402)
  refund(order_id: str) -> bool

# RATIONALES & INVARIANTS
!why store: "PostgreSQL chosen for ACID compliance on order ledger"
!why cache: "Redis key-expiration handles cart session eviction automatically"
!rule payment: "Idempotency-Key header mandatory on all transaction mutations"
!rule security: "PCI compliance: raw card data never touches internal microservices"
!invariant currency: "Monetary values strictly stored as integer cents"

# TASK DAG
[x] T1: initialize postgres schema and migrations
[x] T2: implement CartItem and Money domain primitives [after: T1]
[x] T3: develop CartService with Redis session persistence [after: T2]
[>] T4: build mock PaymentGateway adapter with Stripe SDK [after: T2]
[ ] T5: integrate checkout orchestration saga [after: T3, T4]
[ ] T6: load testing and concurrency race condition suite [after: T5]
""",

    "Data Pipeline ETL": """@spec 0.1
@meta app: "event-etl" | queue: "kafka" | sink: "clickhouse"

# CONTRACTS
!type RawEvent = { topic: str, payload_bytes: bytes, ts: int }
!type CleanRecord = { event_id: str, user_id: str, event_type: str, timestamp_utc: str }
!type IngestBatch = { batch_id: str, records: CleanRecord[], count: int }

!svc IngestionWorker:
  consumeBatch(max_records: int) -> RawEvent[]
  commitOffset(topic: str, partition: int, offset: int) -> bool

!svc Transformer:
  validateAndTransform(raw: RawEvent) -> CleanRecord | Err(ValidationError)

!svc ClickHouseSink:
  flushBatch(batch: IngestBatch) -> int | Err(500)

# RATIONALES & INVARIANTS
!why sink: "ClickHouse chosen for high-throughput columnar analytics"
!why queue: "Kafka partition keys ensure strict per-user event ordering"
!rule retry: "exponential backoff with jitter on sink flushes up to 5 attempts"
!invariant dedupe: "event_id is deterministic SHA256(user_id + ts + event_type)"

# TASK DAG
[x] T1: setup local Kafka and ClickHouse cluster in docker
[x] T2: define schema schemas and validation schemas [after: T1]
[x] T3: implement consumer worker loop with manual commit [after: T2]
[>] T4: implement Transformer with schema validation [after: T3]
[ ] T5: build ClickHouse batch buffer flush worker [after: T4]
[ ] T6: dead-letter queue (DLQ) fallback for malformed events [after: T4]
[ ] T7: end-to-end load test under 10k events/sec [after: T5, T6]
"""
}

# Extraction Probes to test reader agent comprehension
EXTRACTION_PROBES = [
    {
        "id": "PROBE_1_SIGNATURE",
        "question": "What is the return type of CartService.checkout and what error code is returned on conflicts?",
        "expected": "Returns 'Order' or error 'Err(409)'.",
        "aspec_source": "checkout(cart_id: str, idempotency_key: str) -> Order | Err(409)"
    },
    {
        "id": "PROBE_2_INVARIANTS",
        "question": "Why was PostgreSQL chosen, and what is the strict rule regarding currency representation?",
        "expected": "PostgreSQL was chosen for ACID compliance on order ledger. Currency must strictly be stored as integer cents.",
        "aspec_source": "!why store: 'PostgreSQL chosen for ACID compliance on order ledger' | !invariant currency: 'Monetary values strictly stored as integer cents'"
    },
    {
        "id": "PROBE_3_DAG_PREREQS",
        "question": "What tasks must be completed before Task T5 (checkout orchestration saga) can begin?",
        "expected": "Tasks T3 (CartService) and T4 (PaymentGateway).",
        "aspec_source": "[ ] T5: integrate checkout orchestration saga [after: T3, T4]"
    },
    {
        "id": "PROBE_4_TASK_STATE",
        "question": "In the Commerce Engine, what is the exact status of T1, T2, T3, T4, and T5?",
        "expected": "T1=Done, T2=Done, T3=Done, T4=In Progress, T5=Pending/Todo.",
        "aspec_source": "[x] T1, [x] T2, [x] T3, [>] T4, [ ] T5"
    }
]

def run_benchmarks():
    from rich.console import Console
    from rich.table import Table
    console = Console()

    table = Table(title="agentspec Token Reduction & Subagent Slicing Benchmark", header_style="bold magenta")
    table.add_column("Project Spec", style="cyan")
    table.add_column("Markdown (Full)", justify="right", style="yellow")
    table.add_column(".aspec (Full)", justify="right", style="green")
    table.add_column("Full Savings", justify="right", style="bold green")
    table.add_column(".aspec Slice (Subagent)", justify="right", style="blue")
    table.add_column("Subagent Savings", justify="right", style="bold blue")

    for name, aspec_raw in SPECS.items():
        doc = parse_spec(aspec_raw)
        md_full = to_markdown(doc)

        tok_md = count_tokens(md_full, "cl100k_base")
        tok_aspec = count_tokens(aspec_raw, "cl100k_base")
        full_savings = ((tok_md - tok_aspec) / tok_md * 100)

        # Pick active task (in progress) for subagent slice
        active_task = next((t for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS), doc.tasks[0])
        sliced_doc = pack_for_task(doc, active_task.id)
        tok_slice = count_tokens(sliced_doc.to_aspec(), "cl100k_base")
        slice_savings = ((tok_md - tok_slice) / tok_md * 100)

        table.add_row(
            name,
            f"{tok_md} tok",
            f"{tok_aspec} tok",
            f"{full_savings:.1f}%",
            f"{tok_slice} tok ({active_task.id})",
            f"{slice_savings:.1f}%"
        )

    console.print(table)

if __name__ == "__main__":
    run_benchmarks()
