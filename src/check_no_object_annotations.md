# no-object-annotations Hook

The `no-object-annotations` hook rejects an explicit `object` annotation anywhere in a type hint (parameter, return, variable) and suggests a more specific type.

## The Ignore Tag

To allow an explicit `object` type annotation, add the ignore tag as a comment inside the annotation, on the same line as the `object` occurrence:

```python
def read_section(section: str) -> dict[str, object]:  # ignore: no-object-annotations
    ...
```

### Tag Rules

| Rule | Description |
|------|-------------|
| **Exact match required** | The tag must match exactly `# ignore: no-object-annotations` |
| **Same line as `object`** | The tag must be on the line that contains the `object` token in the annotation |
| **Multi-line annotations** | If an annotation spans multiple lines, the tag must be on the specific line holding `object`; a tag on the `def` line above does not suppress anything |
| **Not for casts** | A `cast("dict[str, object]", value)` inside the function body is not an annotation, so it needs no tag |

## Examples

### ✅ Allowed (tag on same line as `object`)

```python
# Return annotation with tag on same line
def process() -> dict[str, object]:  # ignore: no-object-annotations
    return {}

# Parameter annotation with tag on same line
def handler(data: list[object]) -> None:  # ignore: no-object-annotations
    pass

# Variable annotation with tag on same line
items: list[object] = []  # ignore: no-object-annotations
```

### ✅ Allowed (multi-line annotation, tag on `object` line)

```python
def complex_func(
    data: dict[
        str,  # some comment
        object  # ignore: no-object-annotations
    ]
) -> None:
    ...
```

### ❌ Rejected (tag on wrong line)

```python
# Tag on def line - does NOT work
def bad_example() -> dict[str, object]:  # ignore: no-object-annotations
    ...
#         ^^^^^^ 'object' is on this line, but tag is on the def line above

# Tag missing entirely
def also_bad() -> dict[str, object]:
    ...
```

### ✅ Allowed (cast is not an annotation)

```python
from typing import cast

def example(value: dict) -> dict[str, str]:
    # This cast contains 'object' but is NOT an annotation
    # No ignore tag needed
    result = cast("dict[str, object]", value)
    return result
```

## How It Works

The checker (`src/check_no_object_annotations.py`) parses each Python file with `ast` and:

1. Collects all type annotations (parameters, return types, variable annotations)
2. Walks each annotation's AST nodes looking for `ast.Name(id="object")`
3. Checks if the line containing that `object` node has the ignore tag comment
4. Reports an error for each untagged `object` occurrence

The tag is detected by checking the source lines from the annotation's `lineno` to `end_lineno` for the exact string `# ignore: no-object-annotations`.

## Configuration

No configuration options. The hook is enabled/disabled via `stages` in `.pre-commit-config.yaml`:

```yaml
- id: no-object-annotations
  name: block object type annotations
  language: system
  entry: python -m src.check_no_object_annotations
  pass_filenames: true
  stages:
    - pre-commit  # or 'manual' to disable
```

## Related

- Root README: [Specialized hooks table](../README.md#specialized-hooks)
- Implementation: `src/check_no_object_annotations.py`
