"""Run only the guarded, standard-library offline suite."""

import sys
from pathlib import Path


def main():
    # Enforce isolation before importing test support or collecting any tests.
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        print("Use: python -I -S -B tests/run_offline.py", file=sys.stderr)
        return 2

    tests_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests_dir))
    import unittest
    from offline.support import Sandbox

    with Sandbox(tests_dir.parent) as sandbox:
        suite = unittest.defaultTestLoader.discover(
            str(tests_dir / "offline"), pattern="test_*.py", top_level_dir=str(tests_dir)
        )
        count = suite.countTestCases()
        result = unittest.TextTestRunner(verbosity=2, buffer=True).run(suite)
        unexpected = len(sandbox.violations)
    cleaned = not sandbox.root.exists()
    print(f"Offline checks: {count} tests; unexpected blocked operations: {unexpected}")
    print(f"Temporary workspace removed: {cleaned}")
    return 0 if count and result.wasSuccessful() and not unexpected and cleaned else 1


if __name__ == "__main__":
    sys.exit(main())
