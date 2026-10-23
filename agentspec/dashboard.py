import json
from .models import SpecDoc, TaskStatus
from .benchmark import count_tokens
from .transpiler import to_markdown
from .packer import pack_for_task

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>agentspec Dashboard: {app_name}</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});</script>
  <style>
    :root {{
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-dim: #8b949e;
      --accent: #58a6ff;
      --green: #3fb950;
      --yellow: #d29922;
      --blue: #1f6feb;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }}
    h1 {{ font-size: 24px; font-weight: 600; color: #fff; }}
    .badge {{ background: var(--blue); color: #fff; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 12px; }}
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .metric-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
    .metric-title {{ font-size: 12px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 6px; letter-spacing: 0.5px; }}
    .metric-value {{ font-size: 28px; font-weight: 700; color: #fff; }}
    .metric-sub {{ font-size: 13px; color: var(--green); margin-top: 4px; }}
    .grid-2 {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; margin-bottom: 24px; }}
    @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px; }}
    h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #fff; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
    .mermaid-box {{ background: #0b0e14; border-radius: 6px; padding: 16px; overflow-x: auto; text-align: center; }}
    .task-list {{ list-style: none; }}
    .task-item {{ display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 6px; margin-bottom: 8px; background: #0d1117; border: 1px solid var(--border); }}
    .task-title {{ font-size: 14px; font-weight: 500; }}
    .task-status {{ font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }}
    .status-done {{ background: rgba(63, 185, 80, 0.2); color: var(--green); border: 1px solid var(--green); }}
    .status-prog {{ background: rgba(88, 166, 255, 0.2); color: var(--accent); border: 1px solid var(--accent); }}
    .status-todo {{ background: rgba(139, 148, 158, 0.2); color: var(--text-dim); border: 1px solid var(--text-dim); }}
    .tag-why {{ color: var(--accent); font-weight: 600; }}
    .tag-rule {{ color: #f85149; font-weight: 600; }}
    pre {{ background: #090d13; padding: 12px; border-radius: 6px; overflow-x: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; color: #79c0ff; border: 1px solid var(--border); }}
    select, button {{ background: #21262d; color: #fff; border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; font-size: 14px; cursor: pointer; }}
    button:hover {{ background: #30363d; }}
    .interactive-row {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>agentspec: {app_name}</h1>
        <div style="font-size: 13px; color: var(--text-dim); margin-top: 4px;">Spec v{version} &bull; Generated deterministically for human review</div>
      </div>
      <span class="badge">Active Project</span>
    </header>

    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-title">Token Footprint</div>
        <div class="metric-value">{aspec_tokens} <span style="font-size: 14px; color: var(--text-dim); font-weight: normal;">tokens</span></div>
        <div class="metric-sub">↓ {savings_pct}% vs raw Markdown ({md_tokens} tok)</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Task Completion</div>
        <div class="metric-value">{done_tasks} / {total_tasks}</div>
        <div class="metric-sub" style="color: var(--accent);">{prog_tasks} in progress, {todo_tasks} pending</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Architectural Invariants</div>
        <div class="metric-value">{invariants_count}</div>
        <div class="metric-sub" style="color: var(--text-dim);">Strict state constraints</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Service Contracts</div>
        <div class="metric-value">{services_count}</div>
        <div class="metric-sub" style="color: var(--text-dim);">{types_count} registered types</div>
      </div>
    </div>

    <div class="grid-2">
      <div>
        <div class="card">
          <h2>Task Execution DAG</h2>
          <div class="mermaid-box">
            <div class="mermaid">
{mermaid_graph}
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Subagent Context Packer (Live Slice)</h2>
          <div class="interactive-row">
            <select id="taskSelect" onchange="updatePrompt()">
              {task_options}
            </select>
            <button onclick="copyPrompt()">Copy Subagent Prompt</button>
            <span id="copyMsg" style="font-size: 12px; color: var(--green); display: none;">Copied!</span>
          </div>
          <pre id="promptDisplay">{initial_packed_prompt}</pre>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Task Status List</h2>
          <ul class="task-list">
            {task_items_html}
          </ul>
        </div>

        <div class="card">
          <h2>Invariants & Principles</h2>
          <div style="font-size: 13px;">
            {invariants_html}
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Contracts & Type Definitions</h2>
      <pre>{contracts_text}</pre>
    </div>
  </div>

  <script>
    const prompts = {prompts_json};
    function updatePrompt() {{
      const sel = document.getElementById("taskSelect").value;
      document.getElementById("promptDisplay").innerText = prompts[sel] || "No task selected";
    }}
    function copyPrompt() {{
      const txt = document.getElementById("promptDisplay").innerText;
      navigator.clipboard.writeText(txt).then(() => {{
        const msg = document.getElementById("copyMsg");
        msg.style.display = "inline";
        setTimeout(() => {{ msg.style.display = "none"; }}, 2000);
      }});
    }}
  </script>
</body>
</html>
"""

def generate_html_dashboard(doc: SpecDoc, aspec_text: str) -> str:
    app_name = doc.meta.get("app", "Project Spec")
    aspec_tokens = count_tokens(aspec_text, "cl100k_base")
    md_text = to_markdown(doc)
    md_tokens = count_tokens(md_text, "cl100k_base")
    savings_pct = f"{((md_tokens - aspec_tokens) / md_tokens * 100):.1f}" if md_tokens else "0"

    total_tasks = len(doc.tasks)
    done_tasks = sum(1 for t in doc.tasks if t.status == TaskStatus.DONE)
    prog_tasks = sum(1 for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS)
    todo_tasks = sum(1 for t in doc.tasks if t.status == TaskStatus.TODO)

    # Mermaid
    mermaid_lines = ["graph TD"]
    for t in doc.tasks:
        safe_title = t.title.replace('"', "'")
        mermaid_lines.append(f'    {t.id}["{t.id}: {safe_title}"]')
    for t in doc.tasks:
        for dep in t.dependencies:
            mermaid_lines.append(f"    {dep} --> {t.id}")
    done_ids = [t.id for t in doc.tasks if t.status == TaskStatus.DONE]
    prog_ids = [t.id for t in doc.tasks if t.status == TaskStatus.IN_PROGRESS]
    todo_ids = [t.id for t in doc.tasks if t.status == TaskStatus.TODO]
    if done_ids:
        mermaid_lines.append(f"    style {','.join(done_ids)} fill:#1b4728,stroke:#3fb950,stroke-width:2px,color:#fff")
    if prog_ids:
        mermaid_lines.append(f"    style {','.join(prog_ids)} fill:#0c2d6b,stroke:#58a6ff,stroke-width:2px,color:#fff")
    if todo_ids:
        mermaid_lines.append(f"    style {','.join(todo_ids)} fill:#21262d,stroke:#8b949e,stroke-width:1px,color:#8b949e")

    # Tasks HTML
    task_html_parts = []
    for t in doc.tasks:
        badge_cls = "status-done" if t.status == TaskStatus.DONE else ("status-prog" if t.status == TaskStatus.IN_PROGRESS else "status-todo")
        status_label = t.status.value.upper()
        task_html_parts.append(f'''
          <li class="task-item">
            <div>
              <strong style="color: #fff;">{t.id}</strong>: <span class="task-title">{t.title}</span>
            </div>
            <span class="task-status {badge_cls}">{status_label}</span>
          </li>
        ''')

    # Invariants HTML
    inv_html_parts = []
    for inv in doc.invariants:
        cls = "tag-rule" if inv.kind == "rule" else "tag-why"
        inv_html_parts.append(f'<div style="margin-bottom: 8px;"><span class="{cls}">[{inv.kind.upper()}: {inv.key}]</span> {inv.content}</div>')

    # Packed prompts for each task
    prompts_map = {}
    task_option_parts = []
    for t in doc.tasks:
        try:
            packed_doc = pack_for_task(doc, t.id)
            prompts_map[t.id] = packed_doc.to_aspec()
        except Exception:
            prompts_map[t.id] = doc.to_aspec()
        task_option_parts.append(f'<option value="{t.id}">Task {t.id} ({t.title[:30]}...)</option>')

    first_task_id = doc.tasks[0].id if doc.tasks else ""
    initial_prompt = prompts_map.get(first_task_id, "")

    # Contracts text
    contracts_lines = []
    for t in doc.types:
        contracts_lines.append(f"!type {t.name} = {t.definition}")
    for s in doc.services:
        contracts_lines.append(f"\n!svc {s.name}:")
        for m in s.methods:
            contracts_lines.append(f"  {m.name}{m.signature}")

    return DASHBOARD_TEMPLATE.format(
        app_name=app_name,
        version=doc.version,
        aspec_tokens=aspec_tokens,
        md_tokens=md_tokens,
        savings_pct=savings_pct,
        done_tasks=done_tasks,
        total_tasks=total_tasks,
        prog_tasks=prog_tasks,
        todo_tasks=todo_tasks,
        invariants_count=len(doc.invariants),
        services_count=len(doc.services),
        types_count=len(doc.types),
        mermaid_graph="\n".join(mermaid_lines),
        task_options="\n".join(task_option_parts),
        initial_packed_prompt=initial_prompt,
        task_items_html="\n".join(task_html_parts),
        invariants_html="\n".join(inv_html_parts),
        contracts_text="\n".join(contracts_lines),
        prompts_json=json.dumps(prompts_map)
    )
