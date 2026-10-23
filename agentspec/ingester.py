import ast
from pathlib import Path
from typing import List, Optional
from .models import SpecDoc, TypeDef, ServiceDef, MethodDef, TaskDef, TaskStatus

class CodebaseIngester:
    def __init__(self, target_path: Path):
        self.target_path = Path(target_path)

    def ingest(self) -> SpecDoc:
        doc = SpecDoc()
        app_name = self.target_path.name or "ingested-app"
        doc.meta = {"app": app_name, "origin": "auto-ingest"}

        py_files = []
        if self.target_path.is_file() and self.target_path.suffix == ".py":
            py_files = [self.target_path]
        elif self.target_path.is_dir():
            py_files = list(self.target_path.rglob("*.py"))

        for f in py_files:
            # Skip virtualenvs or tests
            if any(part in f.parts for part in (".venv", "venv", "__pycache__", "site-packages")):
                continue
            self._ingest_py_file(f, doc)

        # Add initial starter tasks based on discovered services
        if doc.services:
            for idx, svc in enumerate(doc.services, start=1):
                dep = [f"T{idx-1}"] if idx > 1 else []
                doc.tasks.append(TaskDef(
                    id=f"T{idx}",
                    status=TaskStatus.TODO,
                    title=f"test and harden {svc.name} implementation",
                    dependencies=dep
                ))
        else:
            doc.tasks.append(TaskDef(id="T1", status=TaskStatus.TODO, title="initial project architecture review", dependencies=[]))

        return doc

    def _ingest_py_file(self, filepath: Path, doc: SpecDoc):
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except Exception:
            return

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._process_class(node, doc)

    def _process_class(self, node: ast.ClassDef, doc: SpecDoc):
        class_name = node.name

        # Check if it looks like a Service, Controller, Client, or Manager
        is_svc = any(keyword in class_name for keyword in ("Service", "Controller", "Client", "Gateway", "Manager", "API"))

        methods: List[MethodDef] = []
        fields: List[str] = []

        for item in node.body:
            # Type fields: x: int
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                field_type = ast.unparse(item.annotation) if hasattr(ast, "unparse") else "any"
                fields.append(f"{field_name}: {field_type}")

            # Methods
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name.startswith("_") and item.name != "__init__":
                    continue

                args_list = []
                for a in item.args.args:
                    if a.arg in ("self", "cls"):
                        continue
                    a_type = ast.unparse(a.annotation) if (a.annotation and hasattr(ast, "unparse")) else "any"
                    args_list.append(f"{a.arg}: {a_type}")

                ret_type = ast.unparse(item.returns) if (item.returns and hasattr(ast, "unparse")) else "any"
                sig = f"({', '.join(args_list)}) -> {ret_type}"
                methods.append(MethodDef(name=item.name, signature=sig))

        if is_svc and methods:
            doc.services.append(ServiceDef(name=class_name, methods=methods))
        elif fields:
            def_str = "{" + ", ".join(fields) + "}"
            doc.types.append(TypeDef(name=class_name, definition=def_str))
        elif methods and not is_svc:
            # If it has public methods, treat as a service
            doc.services.append(ServiceDef(name=class_name, methods=methods))

def ingest_codebase(path: Path) -> SpecDoc:
    return CodebaseIngester(path).ingest()
