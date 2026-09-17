from __future__ import annotations

import ast
import sys
from pathlib import Path

IGNORE_TAG = "no-object-annotations"


def is_object_annotation(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "object"


def collect_annotations(node: ast.AST) -> list[ast.expr]:
    annotations: list[ast.expr] = []

    if isinstance(node, (ast.arg, ast.AnnAssign)) and node.annotation is not None:
        annotations.append(node.annotation)

    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
        annotations.append(node.returns)

    return annotations


def is_ignored(annotation: ast.expr, source_lines: list[str]) -> bool:
    """Return True if any source line inside the annotation carries the ignore tag."""
    start = getattr(annotation, "lineno", None)
    end = getattr(annotation, "end_lineno", start)

    if start is None or end is None:
        return False

    return any(f"# ignore: {IGNORE_TAG}" in line for line in source_lines[start - 1 : end])


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    errors: list[str] = []

    for node in ast.walk(tree):
        for annotation in collect_annotations(node):
            if is_ignored(annotation, source_lines):
                continue

            for child in ast.walk(annotation):
                if is_object_annotation(child):
                    errors.append(
                        f"{path}:{child.lineno}:{child.col_offset + 1}: explicit 'object' type annotation is forbidden"
                    )

    return errors


def main() -> int:
    errors: list[str] = []

    for filename in sys.argv[1:]:
        path = Path(filename)

        if path.suffix == ".py":
            errors.extend(check_file(path))

    if errors:
        print("\n".join(errors))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
