import re
from typing import List, Tuple
from .benchmark import count_tokens

# Common filler phrases in LLM-generated specs and prompt markdown
FILLER_PATTERNS = [
    (r"\b(it is important that|it is essential to|make sure that|please ensure that|we need to ensure that)\b", ""),
    (r"\b(in order to|for the purpose of|so as to)\b", "to"),
    (r"\b(the system should provide the ability to|the application allows users to)\b", ""),
    (r"\b(as described previously|as mentioned above|as noted earlier)\b", ""),
    (r"\b(it should be noted that|note that)\b", ""),
    (r"\b(is responsible for handling|is responsible for)\b", "handles"),
    (r"\b(in the event that|in case of)\b", "if"),
    (r"\b(utilize|utilizes|utilizing)\b", "use"),
]

def compress_prose(text: str) -> str:
    """
    Strips redundant natural language fluff, converting verbose sentences
    into concise telegraphic notation.
    """
    lines = text.splitlines()
    compressed_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            compressed_lines.append("")
            continue

        c_line = stripped
        for pattern, repl in FILLER_PATTERNS:
            c_line = re.sub(pattern, repl, c_line, flags=re.IGNORECASE)

        # Normalize multiple spaces
        c_line = re.sub(r"\s+", " ", c_line).strip()
        
        # Capitalize first letter if it was a sentence
        if c_line and c_line[0].islower():
            c_line = c_line[0].upper() + c_line[1:]

        compressed_lines.append(c_line)

    return "\n".join(compressed_lines)

def summarize_markdown_to_aspec(markdown_text: str, app_name: str = "compressed-spec") -> str:
    """
    Converts unstructured Markdown notes into a concise .aspec draft.
    """
    aspec_lines = [
        "@spec 0.1",
        f'@meta app: "{app_name}" | source: "compressed-from-md"',
        "",
        "# RATIONALES & INVARIANTS"
    ]

    tasks = []
    task_idx = 1

    for line in markdown_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Look for constraints / requirements
        if any(w in line.lower() for w in ("must", "cannot", "security", "never", "always", "strictly")):
            clean_rule = compress_prose(line.lstrip("-*#0123456789. "))
            aspec_lines.append(f'!rule req_{task_idx}: "{clean_rule}"')
            task_idx += 1

        # Look for list items or checkboxes that look like tasks
        elif re.match(r"^(\-|\*|\d+\.)\s*(\[([ xX])\])?\s*(.+)$", line):
            m = re.match(r"^(\-|\*|\d+\.)\s*(\[([ xX])\])?\s*(.+)$", line)
            box = m.group(3)
            title = compress_prose(m.group(4))
            status_mark = "x" if box in ("x", "X") else " "
            dep_str = f" [after: T{len(tasks)}]" if tasks else ""
            tid = f"T{len(tasks) + 1}"
            tasks.append(f"[{status_mark}] {tid}: {title}{dep_str}")

    aspec_lines.append("")
    aspec_lines.append("# TASK EXECUTION DAG")
    if tasks:
        aspec_lines.extend(tasks)
    else:
        aspec_lines.append("[ ] T1: implement requirements from compressed specification")

    return "\n".join(aspec_lines)
