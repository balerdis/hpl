"""The earlier products' names live in a few places and nowhere else.

Walks the tracked tree and fails when a file outside the allowlist contains
either name, case-insensitively. The allowlist is the detection module (found
by its import, not retyped), the two places that show its message, the
documentation section about it, and the tests of all that.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from hpl import predecessors

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(predecessors.__file__).resolve().relative_to(ROOT).as_posix()
SOURCE = Path(MODULE).parent
ALLOWED = frozenset(
    {
        MODULE,
        (SOURCE / "cli.py").as_posix(),
        (SOURCE / "tui" / "session.py").as_posix(),
        "MANUAL.md",
        Path(__file__).resolve().relative_to(ROOT).as_posix(),
        (Path(__file__).resolve().parent / "test_predecessors.py").relative_to(ROOT).as_posix(),
    }
)
WORDS = tuple(sorted({"pegasus", "darq"}))


def tracked_files() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [name for name in listing.split("\0") if name and (ROOT / name).is_file()]


def containing(word: str) -> set[str]:
    found = set()
    for name in tracked_files():
        try:
            text = (ROOT / name).read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            continue
        if word in text.lower():
            found.add(name)
    return found


class PredecessorWordGuardTest(unittest.TestCase):
    def test_the_module_is_where_the_allowlist_says(self):
        self.assertTrue((ROOT / MODULE).is_file())
        self.assertIn(MODULE, tracked_files() + [MODULE])

    def test_the_words_are_the_products_in_the_module(self):
        names = {p.display_name.lower() for p in predecessors.PRODUCTS}
        self.assertEqual(names, set(WORDS))

    def test_each_word_appears_only_in_allowed_files(self):
        for word in WORDS:
            with self.subTest(word=word):
                self.assertEqual(sorted(containing(word) - ALLOWED), [])


if __name__ == "__main__":
    unittest.main()
