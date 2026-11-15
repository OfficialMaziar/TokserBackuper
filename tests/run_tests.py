"""Minimal pytest-compatible test runner.

The project's tests are written for pytest. When pytest is installed
(recommended: ``pip install pytest``), run ``pytest tests/``. This runner
exists so the suite can also execute in offline environments that cannot
install packages. It supports the subset of pytest used here:
  * ``test_*`` functions and fixtures by name (including ``scope="session"``)
  * ``@pytest.mark.parametrize``
  * ``pytest.raises`` / ``pytest.fixture`` (via the bundled ``pytest`` shim)
  * ``tmp_path`` fixtures

Usage:  python tests/run_tests.py [-k pattern] [-v]
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pytest_shim  # noqa: E402  (registers "pytest" in sys.modules)


def load_module(path: Path):
    name = f"tbm_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    pattern = None
    verbose = "-v" in argv
    if "-k" in argv:
        pattern = argv[argv.index("-k") + 1]

    conftest = load_module(ROOT / "tests" / "conftest.py")
    fixtures = {
        name: obj for name, obj in vars(conftest).items()
        if getattr(obj, "_is_tbm_fixture", False)
    }
    session_cache: dict[str, object] = {}
    gen_finalizers: list = []

    def resolve(name: str, module):
        if name == "tmp_path":
            import tempfile
            return Path(tempfile.mkdtemp(prefix="tbm_tmp_"))
        if name in session_cache:
            return session_cache[name]
        # Fixtures may live in conftest.py or in the test module itself
        # (pytest resolves module-level fixtures with higher priority).
        fx = None
        home = conftest
        if module is not None:
            candidate = getattr(module, name, None)
            if getattr(candidate, "_is_tbm_fixture", False):
                fx, home = candidate, module
        if fx is None:
            fx = fixtures.get(name)
        if fx is None:
            raise KeyError(f"Unknown fixture: {name}")
        scope = getattr(fx, "_fixture_scope", "function")
        cache_key = f"{name}::{scope}"
        if scope == "session" and cache_key in session_cache:
            return session_cache[cache_key]

        # Dependencies resolve in the fixture's own module, which is how a
        # module-level fixture reaches conftest fixtures.
        kwargs = {dep: resolve(dep, home) for dep in getattr(fx, "_fixture_deps", [])}
        result = fx(**kwargs)
        if inspect.isgenerator(result):
            gen = result
            value = next(gen)
            gen_finalizers.append(gen)
        else:
            value = result
        if scope == "session":
            session_cache[cache_key] = value
        else:
            session_cache[name] = value
        return value

    test_files = sorted((ROOT / "tests").glob("test_*.py"))
    passed = failed = skipped = 0
    failures: list[tuple[str, str]] = []

    for path in test_files:
        module = load_module(path)
        for name, fn in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(fn):
                continue
            if pattern and pattern not in name:
                continue
            marks = getattr(fn, "_tbm_parametrize", None)
            if not marks:
                cases = [({}, "")]
            else:
                names = marks["names"]
                cases = []
                for value in marks["values"]:
                    vals = value if len(names) > 1 else (value,)
                    cases.append((dict(zip(names, vals)), f"[{value!r}]"))
            for extra_kwargs, suffix in cases:
                label = f"{path.stem}::{name}{suffix}"
                # Drop per-test fixtures but keep session-scoped ones. The
                # clear() must happen on a snapshot, otherwise the session
                # entries are lost along with everything else and the session
                # fixture is rebuilt for every test.
                for key in [k for k in session_cache if "::session" not in k]:
                    del session_cache[key]
                try:
                    sig = inspect.signature(fn)
                    kwargs = {}
                    for param in sig.parameters:
                        if param in extra_kwargs:
                            kwargs[param] = extra_kwargs[param]
                        else:
                            kwargs[param] = resolve(param, module)
                    fn(**kwargs)
                    passed += 1
                    if verbose:
                        print(f"  PASS  {label}")
                except pytest_shim.Skipped as exc:
                    skipped += 1
                    if verbose:
                        print(f"  SKIP  {label}: {exc}")
                except Exception as exc:
                    failed += 1
                    tb = traceback.format_exc()
                    failures.append((label, tb))
                    print(f"  FAIL  {label}: {type(exc).__name__}: {exc}")
                finally:
                    # Finalize non-session generators created for this test.
                    for gen in list(gen_finalizers):
                        try:
                            next(gen)
                        except StopIteration:
                            gen_finalizers.remove(gen)
                        except Exception:
                            gen_finalizers.remove(gen)

    print()
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    if failures:
        print("\n" + "=" * 70)
        for label, tb in failures:
            print(f"\nFAILED {label}\n{tb}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
