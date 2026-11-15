"""A tiny subset of pytest, used only when the real package is unavailable.

If pytest IS installed, this module is never imported and the real pytest is
used. It provides ``pytest.fixture``, ``pytest.raises``, ``pytest.mark`` and
``pytest.skip`` for the offline runner.
"""
from __future__ import annotations

import contextlib
import sys


class Skipped(Exception):
    pass


class Failed(AssertionError):
    pass


class _Raises:
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise Failed(f"DID NOT RAISE {self.expected}")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        if self.match is not None and self.match not in str(exc):
            raise Failed(f"Pattern {self.match!r} not found in {exc!r}")
        return True


class _Mark:
    @staticmethod
    def parametrize(argnames, values):
        def decorator(fn):
            names = ([n.strip() for n in argnames.split(",")]
                     if isinstance(argnames, str) else list(argnames))
            fn._tbm_parametrize = {"names": names, "values": list(values)}
            return fn
        return decorator

    def __getattr__(self, name):
        def decorator(fn=None, **_kwargs):
            if fn is None:
                return lambda f: f
            return fn
        return decorator


def fixture(func=None, *, scope="function", **_kwargs):
    def wrap(fn):
        fn._is_tbm_fixture = True
        fn._fixture_scope = scope
        import inspect

        fn._fixture_deps = list(inspect.signature(fn).parameters)
        return fn

    if func is not None:
        return wrap(func)
    return wrap


def raises(expected, match=None):
    return _Raises(expected, match)


def skip(reason=""):
    raise Skipped(reason)


def fail(reason=""):
    raise Failed(reason)


_module = type(sys)("pytest")
_module.fixture = fixture
_module.raises = raises
_module.mark = _Mark()
_module.skip = skip
_module.fail = fail
_module.Skipped = Skipped

if "pytest" not in sys.modules:
    sys.modules["pytest"] = _module
