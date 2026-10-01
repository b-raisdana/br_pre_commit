"""br_pre_commit - pre-commit hooks, helpers and the pandera_validate decorator.

Exposed so consuming repositories can write::

    from br_pre_commit import pandera_validate

instead of reaching into ``br_pre_commit.src.br_pandera.__main__``. Requires the
repository root (the directory containing this package) on ``sys.path``.

The re-export is lazy (PEP 562). Importing ``br_pre_commit`` must not pull in
pandas/pandera: the decorator is only imported when the attribute is first
accessed. Every intra-repository import is package-qualified, so nothing ever
puts ``src/`` itself on ``sys.path`` and the local ``src/br_pandera`` package can
never shadow the third-party ``pandera`` distribution that the decorator
validates with (``import pandera.pandas``).
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast, overload

if TYPE_CHECKING:
    from .src.br_pandera.__main__ import pandera_validate

__all__ = ["pandera_validate"]

_P = ParamSpec("_P")
_R = TypeVar("_R")


class PanderaValidate(Protocol):
    """The pandera_validate decorator, usable bare or called with options."""

    @overload
    def __call__(self, func: Callable[_P, _R], /) -> Callable[_P, _R]: ...
    @overload
    def __call__(self, **options: bool | int) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]: ...


def __getattr__(name: str) -> PanderaValidate:
    if name == "pandera_validate":
        from .src.br_pandera.__main__ import pandera_validate

        return cast("PanderaValidate", pandera_validate)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
