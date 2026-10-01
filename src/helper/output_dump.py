"""Output dump helper for pandera validation decorator."""

from __future__ import annotations

from pathlib import Path

from ..pandera.dump_folder import get_dump_folder


def dump_function_output(func_obj, result) -> None:
    """Dump function output to the configured dump folder.

    Args:
        func_obj: The function object that was called
        result: The result returned by the function
    """
    import inspect

    try:
        source_file = Path(inspect.getsourcefile(func_obj) or "")
        dump_dir = get_dump_folder(source_file)
        dump_dir.mkdir(parents=True, exist_ok=True)

        import json
        import pickle

        func_name = func_obj.__qualname__
        timestamp = __import__("datetime").datetime.now().strftime("%Y%m%dT%H%M%S")
        dump_file = dump_dir / f"{func_name}.{timestamp}.pkl"

        with open(dump_file, "wb") as f:
            pickle.dump(result, f)

        # Also write a JSON summary if possible
        json_file = dump_dir / f"{func_name}.{timestamp}.json"
        try:
            if hasattr(result, "to_dict"):
                payload = result.to_dict()
            elif hasattr(result, "__dict__"):
                payload = result.__dict__
            else:
                payload = {"type": type(result).__name__, "repr": repr(result)}
            with open(json_file, "w") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception:
            pass  # JSON dump is best-effort
    except Exception:
        pass  # Best-effort dump, never fail the decorated function
