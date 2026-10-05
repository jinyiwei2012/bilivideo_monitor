"""Import-purity guard for ``core`` (B2 composition-root prerequisite).

``import core`` must not open databases, spawn threads, or expose module-level
instance aliases. These guards freeze the current purity so future refactors
cannot silently re-introduce import-time side effects.

The checks run in a subprocess so that already-imported modules in the test
process cannot mask a regression.
"""

import subprocess
import sys
import textwrap

_PURE_IMPORT_PROBE = textwrap.dedent("""
    import os
    import threading

    def _snapshot_data_dir():
        files = set()
        for root, _dirs, names in os.walk("data"):
            for name in names:
                files.add(os.path.join(root, name))
        return files

    before_threads = threading.active_count()
    before_files = _snapshot_data_dir()

    import core  # noqa: F401  (import purity is exactly what is under test)

    after_threads = threading.active_count()
    after_files = _snapshot_data_dir()

    new_files = sorted(after_files - before_files)
    assert after_threads == before_threads, (
        "import core spawned threads: %d -> %d" % (before_threads, after_threads)
    )
    assert new_files == [], "import core created files: %s" % (new_files,)

    # No module-level instance aliases: only factories/types/submodules allowed.
    assert not hasattr(core, "db"), "core exposes a module-level db alias"
    assert not hasattr(core, "bilibili_api_instance"), (
        "core exposes a module-level api instance alias"
    )
    for name in ("get_db", "get_bilibili_api"):
        assert name in getattr(core, "__all__", []), "core.__all__ missing %r" % (name,)
    """)


def test_import_core_has_no_import_time_side_effects():
    result = subprocess.run(
        [sys.executable, "-c", _PURE_IMPORT_PROBE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"import purity probe failed:\n{result.stdout}\n{result.stderr}"


def test_core_get_db_is_lazy_and_injectable():
    """``get_db`` must be a lazy factory, not an import-time instance."""
    from core.database import central_db

    assert callable(central_db.get_db)
    assert hasattr(central_db, "_db")
