# agentspec Examples & Artifacts

This directory contains reference specifications, packed subagent slices, compression benchmarks, and rendered outputs demonstrating `agentspec` capabilities.

---

## Directory Layout

```
examples/
├── unpacked/                     # Full, unscoped project specifications
│   ├── commerce.aspec            # Complete e-commerce service spec & DAG
│   └── swarm.aspec               # Parallel multi-agent swarm spec with [touch:] & [test:]
│
├── packed/                       # Scoped subagent prompt slices (aspec pack)
│   ├── commerce_t3_slice.aspec   # Pruned slice for Task T3 (saves ~26% tokens)
│   └── swarm_t3_slice.aspec      # Pruned slice with deep contract pruning (saves ~50% tokens)
│
├── compression/                  # Markdown-to-agentspec compression (aspec compress)
│   ├── verbose_plan.md           # Raw, verbose 700+ char natural language markdown
│   └── compressed_plan.aspec     # Algorithmic extraction into clean, dense .aspec
│
├── output/                       # On-demand human review artifacts
│   ├── rendered.md               # Deterministically compiled Markdown + Mermaid graph
│   └── dashboard.html            # Standalone dark-mode HTML dashboard with live DAG
│
├── project.aspec                 # Default starter commerce spec
├── swarm.aspec                   # Default starter swarm spec
└── agentspec_self.aspec          # Self-ingested codebase spec of agentspec itself
```

---

## Quick Experiments

1. **Compare Unpacked vs. Packed**:
   Compare `examples/unpacked/swarm.aspec` with `examples/packed/swarm_t3_slice.aspec`. Notice how `aspec pack` stripped `CartService`, `Money`, and unrelated tasks, giving Subagent 3 only what it needs.

2. **Run Parallel Swarm Scheduler**:
   ```bash
   aspec ready examples/swarm.aspec
   ```

3. **Transpile Spec to Markdown**:
   ```bash
   aspec render examples/unpacked/commerce.aspec
   ```

4. **Launch HTML Mission Control Dashboard**:
   ```bash
   aspec view examples/swarm.aspec --out dashboard.html
   ```
