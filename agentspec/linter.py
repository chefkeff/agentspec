import re
from dataclasses import dataclass
from typing import List, Set
from .models import SpecDoc, TaskStatus

@dataclass
class LintIssue:
    severity: str  # 'ERROR', 'WARNING', 'INFO'
    code: str
    message: str

class Linter:
    def __init__(self, doc: SpecDoc):
        self.doc = doc

    def lint(self) -> List[LintIssue]:
        issues: List[LintIssue] = []
        issues.extend(self._check_prerequisite_states())
        issues.extend(self._check_orphan_tasks())
        issues.extend(self._check_unused_types())
        issues.extend(self._check_empty_services())
        return issues

    def _check_prerequisite_states(self) -> List[LintIssue]:
        """Verify that started/done tasks don't have uncompleted prerequisites."""
        issues = []
        task_map = {t.id: t for t in self.doc.tasks}

        for t in self.doc.tasks:
            if t.status in (TaskStatus.IN_PROGRESS, TaskStatus.DONE):
                for dep_id in t.dependencies:
                    dep_task = task_map.get(dep_id)
                    if dep_task:
                        if t.status == TaskStatus.DONE and dep_task.status != TaskStatus.DONE:
                            issues.append(LintIssue(
                                severity="ERROR",
                                code="E001_PRE_NOT_DONE",
                                message=f"Task '{t.id}' is marked DONE, but prerequisite '{dep_id}' is {dep_task.status.value.upper()}."
                            ))
                        elif t.status == TaskStatus.IN_PROGRESS and dep_task.status == TaskStatus.TODO:
                            issues.append(LintIssue(
                                severity="WARNING",
                                code="W001_PRE_NOT_STARTED",
                                message=f"Task '{t.id}' is IN_PROGRESS, but prerequisite '{dep_id}' has not even started (TODO)."
                            ))
        return issues

    def _check_orphan_tasks(self) -> List[LintIssue]:
        """Detect tasks that have no dependencies and are not depended on by any other task."""
        if len(self.doc.tasks) <= 1:
            return []

        depended_on: Set[str] = set()
        for t in self.doc.tasks:
            depended_on.update(t.dependencies)

        issues = []
        for t in self.doc.tasks:
            if not t.dependencies and t.id not in depended_on:
                issues.append(LintIssue(
                    severity="INFO",
                    code="I001_ORPHAN_TASK",
                    message=f"Task '{t.id}' ('{t.title}') is disconnected from the main DAG (no prerequisites and no dependents)."
                ))
        return issues

    def _check_unused_types(self) -> List[LintIssue]:
        """Detect types declared with !type that are never referenced anywhere else in the spec."""
        if not self.doc.types:
            return []

        # Aggregate all text where types could be referenced
        corpus = []
        for s in self.doc.services:
            for m in s.methods:
                corpus.append(m.signature)
        for t in self.doc.types:
            corpus.append(t.definition)

        full_text = " ".join(corpus)
        issues = []
        for t in self.doc.types:
            # Check if type name appears as a distinct word anywhere else
            # (excluding its own definition in full_text by regex counting)
            pattern = rf"\b{re.escape(t.name)}\b"
            matches = list(re.finditer(pattern, full_text))
            if not matches:
                issues.append(LintIssue(
                    severity="WARNING",
                    code="W002_UNUSED_TYPE",
                    message=f"Type '{t.name}' is defined but never referenced in any service interface or composite type."
                ))
        return issues

    def _check_empty_services(self) -> List[LintIssue]:
        issues = []
        for s in self.doc.services:
            if not s.methods:
                issues.append(LintIssue(
                    severity="WARNING",
                    code="W003_EMPTY_SERVICE",
                    message=f"Service '{s.name}' has no methods declared."
                ))
        return issues

def lint_spec(doc: SpecDoc) -> List[LintIssue]:
    return Linter(doc).lint()
