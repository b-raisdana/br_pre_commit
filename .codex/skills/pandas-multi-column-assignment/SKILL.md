---
name: pandas-multi-column-assignment
description: When assigning multiple columns from a sequence of Series in a DataFrame, use explicit 2-D construction (pd.concat[..., axis=1]) with named columns, never a plain Python list[Series]; and prefer true runtime schema validation over typing.cast() as a type-only assertion.
---

# Pandas multi-column assignment & runtime validation

Trigger: assigning multiple new columns to a DataFrame from `Series` objects, or annotating/returning a validated DataFrame.

## Multi-column assignment

Do **not** assign a plain Python `list[Series]`:

```python
df[columns] = [s1, s2, s3]            # ❌ ValueError: Columns must be same length as key
```

A list is 1-D; pandas can't map N series to N columns reliably.

**Use** explicit 2-D construction:

```python
columns = ["a", "b", "c"]
df[columns] = pd.concat([s1, s2, s3], axis=1).set_axis(columns, axis=1)
```

- `pd.concat([...], axis=1)` builds a rows × columns object.
- `set_axis(columns, axis=1)` pins the column names explicitly — never leave them positional.
- Index alignment is preserved — prefer `concat` over `np.array(series)` unless index semantics are intentionally discarded.

For repeated dynamic assignments, define the column-name list once:

```python
result_columns = [...]                # define once
df[result_columns] = pd.concat([...], axis=1).set_axis(result_columns, axis=1)
```

Drop any now-unnecessary `# type: ignore[...]` after restructuring; re-run the type checker and keep an ignore only for a genuine, unavoidable issue.

## Runtime validation over typing.cast

`cast()` is static-only — it does **not** validate, convert, or enforce at runtime:

```python
return cast(pt.DataFrame[SomeSchema], df)   # ❌ type-checker lies, runtime is unchecked
```

When a runtime schema validator exists, use it:

```python
return SomeSchema.validate(df)             # ✅ true runtime validation
```

For a function transforming schema A → schema B, return the **validated** result:

```python
return TargetSchema.validate(result)       # not cast(pt.DataFrame[TargetSchema], result)
```

Objective: make type/schema claims **true at runtime**, not merely accepted by the type checker.

Combine with [pandera-dataframe-validation](../pandera-dataframe-validation/SKILL.md) — decorated functions get this enforcement for free; the `cast` anti-pattern is for paths *without* `@pandera_validate`.
