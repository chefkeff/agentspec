from typing import Dict, Any
from .parser import parse_spec
from .transpiler import to_markdown

class BenchmarkResult:
    def __init__(self, aspec_tokens: int, markdown_tokens: int, encoding_name: str):
        self.aspec_tokens = aspec_tokens
        self.markdown_tokens = markdown_tokens
        self.encoding_name = encoding_name
        self.saved_tokens = max(0, markdown_tokens - aspec_tokens)
        self.reduction_percent = ((markdown_tokens - aspec_tokens) / markdown_tokens * 100) if markdown_tokens > 0 else 0.0

def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except Exception:
        # Fallback approximation (1 token ~ 4 chars) if tiktoken encoding fails
        return len(text) // 4

def benchmark_spec(aspec_text: str) -> Dict[str, BenchmarkResult]:
    doc = parse_spec(aspec_text)
    md_text = to_markdown(doc)

    results = {}
    for enc_name in ["cl100k_base", "o200k_base"]:
        try:
            aspec_tok = count_tokens(aspec_text, enc_name)
            md_tok = count_tokens(md_text, enc_name)
            results[enc_name] = BenchmarkResult(aspec_tok, md_tok, enc_name)
        except Exception:
            pass

    return results
