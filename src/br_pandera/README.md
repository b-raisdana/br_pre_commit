# pandera

Runtime DataFrame validation decorator and its output-dump folder configuration. Full reference documentation, moved here from the module docstrings.

## Modules

| Module | Responsibility |
| ------ | -------------- |
| `__main__.py` | `pandera_validate` decorator: type checking, `n_return`/NaN enforcement, static NaN-fill detection, output dumping |
| `dump_folder.py` | Process-wide dump-folder resolution (`configure_pandera_dump_folder`, `resolve_dump_folder`, `get_dump_folder`) |

## `pandera_validate`

```python
@pandera_validate
def load(path: str) -> pt.DataFrame[MySchema]: ...
```

Accepts the function directly or with options (`@pandera_validate(dump_output=True)`).

### Decorator options

| Option | Default | Effect |
| ------ | ------- | ------ |
| `allow_pandas_dataframe` | `False` | When false, warns when an annotation uses bare `pandas.DataFrame` instead of `pandera.typing.DataFrame` |
| `trim_to_n_return` | `True` | Return only the last `n_return` rows after NaN-row drop |
| `warn_on_nan_fill` | `True` | Log a warning for statically detected NaN-fill calls |
| `forbid_nan_fill` | `False` | Raise `NanFillDetectedError` at decoration time instead of warning |
| `deep_nan_fill_scan` | `False` | Also follow same-module function calls one level deep |
| `nan_fill_scan_depth` | `2` | Depth cap for the deep scan |
| `extra_nan_fill_names` | `frozenset()` | Additional names to treat as NaN fills, unioned with `DEFAULT_NAN_FILL_NAMES` |
| `dump_output` | `False` | Write the function result via `helper.output_dump.dump_function_output` |

### Call-time keyword arguments

`n_return`, `allow_return_nan`, and `discard_n_return` are **popped before the wrapped call**, so they never reach the validated function:

- `n_return` — required when the signature declares it, unless `allow_return_nan=True`; must be an `int` (`bool` rejected) or `TypeError` is raised at call time.
- `allow_return_nan` — skip `n_return` enforcement entirely.
- `discard_n_return` — strip `n_return` from the forwarded call (it is normally forwarded so the schema can validate against it).

### n_return / NaN enforcement

`_enforce_output` walks the result with `optree.tree_map` and applies, to **every DataFrame leaf** (including frames nested in tuples, lists, and dicts):

1. `df.dropna()` — drop any row containing a NaN in any column.
2. If fewer than `n_return` valid rows remain → `InsufficientDataError` naming the required count, the valid/input counts, and the columns holding NaNs.
3. `tail(n_return)` when `trim_to_n_return`.

### Static NaN-fill detection

At decoration time the decorated function's source is parsed with `ast` and every call whose name is in `DEFAULT_NAN_FILL_NAMES` (`fillna`, `bfill`, `backfill`, `ffill`, `pad`, `interpolate`, `nan_to_num`, `SimpleImputer`, `KNNImputer`, `IterativeImputer`) plus `extra_nan_fill_names` is reported with file, line, and call chain. The policy stated in the warning is to prevent NaNs through sufficient warmup/lookback rather than filling them. Source that cannot be read (`OSError`, `TypeError`, `SyntaxError`) yields no hits — detection is best-effort, never a hard failure.

### Production bypass

When `app_config.environment == "production"` the decorator returns the undecorated function: no `pandera.check_types`, no `n_return` enforcement, no scanning. NaN-fill and legacy-DataFrame *warnings* still run, since they happen before the bypass.

### Exceptions

- `NanFillDetectedError(ValueError)` — raised at decoration time when `forbid_nan_fill=True` and a NaN fill is found.
- `InsufficientDataError(ValueError)` — raised at call time when valid rows are below `n_return`.
- `TypeError` — bad `n_return` value or missing `n_return` while enforcement is expected.

### Companion hook

`../check_pandera_decorator.py` enforces the matching static rule in pre-commit: a public function annotated with `pd.DataFrame`/`pt.DataFrame[...]`/`pandera.typing.DataFrame[...]` must carry `@pandera_validate` or `@duckdb_cache(...)`, unless the line directly above is `# pandera-validate: ignore[typevar]`. Private (leading-underscore) helpers are skipped. It parses the AST only and never imports application modules.

## Dump folder

One process-wide switch set once by the importing project, instead of a folder argument on every call:

```python
from pandera.dump_folder import configure_pandera_dump_folder

configure_pandera_dump_folder("logs/debug_frames")  # relative -> <git root>/logs/debug_frames
configure_pandera_dump_folder("/var/tmp/frames")    # absolute -> used as-is
configure_pandera_dump_folder(None)                 # restore the default
```

- Default is `logs/output_dump/`.
- A relative override resolves against the Git repository root **owning the decorated function**, not the process CWD, so the layout belongs to the importing project regardless of where the run starts.
- `configure_pandera_dump_folder` applies to every subsequent dump and must therefore be called at project start-up, before decorated functions run.
- `resolve_dump_folder(source_file)` computes the path without creating it; `get_dump_folder(source_file)` creates it on first use and logs the location.

## Import surface

This package is vendored from a larger project; its public surface is re-exported by the repository root:

- `from br_pre_commit import pandera_validate` is the supported entry point.
- The implementation lives in `br_pre_commit/src/br_pandera/`, always under a package-qualified path (`br_pre_commit.src.br_pandera` from a consuming repository, `src.br_pandera` from this repository's own root). The package is deliberately **not** named `pandera`: nothing puts `src/` itself on `sys.path`, and the distinct name keeps it from ever shadowing the third-party `pandera` distribution the decorator validates with (`import pandera.pandas`), even if some future entry point did.
- Dumping uses `src/helper/output_dump.py` (content-addressed file names) and `src/helper/repo_root.py`; configure the target folder through `configure_pandera_dump_folder` above.
- `import pandera.pandas` additionally requires a Pandera release that ships the `pandera.pandas` submodule.
