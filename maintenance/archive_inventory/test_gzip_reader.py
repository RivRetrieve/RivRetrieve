"""Synthetic regression checks for the private local archive inventory reader.

Load only reviewed imports and function definitions. Never import the script:
its module startup truncates output and reads the genuine source specification.
Paths arrive through environment variables; no source material is a test input.
"""

import ast
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import types
import unittest
import warnings
import zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

PAYLOAD = b"synthetic river gauge payload\n" * 31
COMPRESSED = gzip.compress(PAYLOAD, mtime=0)


def load_reader(path, scratch, rolled=False):
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "inventory_definitions", "exec"), namespace)
    namespace.update(ROOT=scratch, out=io.StringIO(), summary=Counter(), warnings=[])
    observed = {}
    original_emit = namespace["emit"]

    def emit(locator, providers, stream, outer=None):
        observed[locator] = stream.read()
        stream.seek(0)
        return original_emit(locator, providers, stream, outer)

    namespace["emit"] = emit
    if rolled:

        @contextmanager
        def disk_spool(*args, **kwargs):
            with tempfile.SpooledTemporaryFile(*args, **kwargs) as stream:
                stream.rollover()
                yield stream

        namespace["tempfile"] = types.SimpleNamespace(SpooledTemporaryFile=disk_spool)
    return namespace, observed


def archive_bytes(kind, member, content):
    buffer = io.BytesIO()
    if kind == "tar":
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo(member)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    else:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr(member, content)
    return buffer.getvalue()


class InventoryGzipTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ["INVENTORY_SYNTHETIC_ROOT"])
        self.addCleanup(self.directory.cleanup)
        self.scratch = Path(self.directory.name)
        self.original = Path(os.environ["INVENTORY_ORIGINAL_SCRIPT"])
        self.candidate = Path(os.environ["INVENTORY_CANDIDATE_SCRIPT"])

    def inspect_bytes(self, script, content, locator, rolled=False):
        namespace, observed = load_reader(script, self.scratch, rolled)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, dir=self.scratch) as stream:
            stream.write(content)
            if rolled:
                stream.rollover()
            self.assertEqual(stream._rolled, rolled)
            stream.seek(0)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                namespace["inspect"](stream, locator, ["synthetic"])
            stream.seek(0)
            after = stream.read()
        records = [json.loads(line) for line in namespace["out"].getvalue().splitlines()]
        return namespace, observed, records, caught, after

    def assert_records(self, records, observed, expected):
        self.assertEqual(len(records), len(expected))
        self.assertEqual(set(observed), set(expected))
        for record, (locator, (content, parent)) in zip(records, expected.items(), strict=True):
            self.assertEqual(record["locator"], locator)
            self.assertEqual(record["container"], parent)
            self.assertEqual(record["providers"], ["synthetic"])
            self.assertEqual(record["byte_size"], len(content))
            self.assertEqual(record["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(observed[locator], content)

    def test_original_in_memory_reproduces_failure_warning_and_mutation(self):
        namespace, observed, records, caught, after = self.inspect_bytes(self.original, COMPRESSED, "payload.gz")
        self.assertEqual(len(records), 1)
        self.assertEqual(set(observed), {"payload.gz"})
        self.assertEqual(
            namespace["warnings"],
            [{"locator": "payload.gz", "reason": "container_inspection_failed", "exception_type": "OSError"}],
        )
        self.assertTrue(any(issubclass(item.category, FutureWarning) for item in caught))
        self.assertNotEqual(after, COMPRESSED)

    def test_repaired_direct_gzip_both_spool_states(self):
        for rolled in (False, True):
            with self.subTest(rolled=rolled):
                namespace, observed, records, caught, after = self.inspect_bytes(
                    self.candidate, COMPRESSED, "payload.gz", rolled
                )
                self.assert_records(
                    records,
                    observed,
                    {
                        "payload.gz": (COMPRESSED, None),
                        "payload.gz!payload": (PAYLOAD, "payload.gz"),
                    },
                )
                self.assertEqual(namespace["warnings"], [])
                self.assertEqual(caught, [])
                self.assertEqual(after, COMPRESSED)

    def test_recursive_tar_and_zip_both_spool_states(self):
        # Force every temporary nested copy to disk in the rolled cases.
        # The TAR/ZIP traversal and decoder are the preserved script's functions.
        for kind in ("tar", "zip"):
            content = archive_bytes(kind, "payload.gz", COMPRESSED)
            locator = "outer." + kind
            child = locator + "!payload.gz"
            for rolled in (False, True):
                with self.subTest(kind=kind, rolled=rolled):
                    namespace, observed, records, caught, after = self.inspect_bytes(
                        self.candidate, content, locator, rolled
                    )
                    self.assert_records(
                        records,
                        observed,
                        {
                            locator: (content, None),
                            child: (COMPRESSED, locator),
                            child + "!" + locator + "!payload": (PAYLOAD, child),
                        },
                    )
                    self.assertEqual(namespace["warnings"], [])
                    self.assertEqual(caught, [])
                    self.assertEqual(after, content)

    def test_recursive_zip_tar_gzip_parent_chain(self):
        tar = archive_bytes("tar", "payload.gz", COMPRESSED)
        content = archive_bytes("zip", "inner.tar", tar)
        namespace, observed, records, caught, after = self.inspect_bytes(self.candidate, content, "outer.zip")
        self.assert_records(
            records,
            observed,
            {
                "outer.zip": (content, None),
                "outer.zip!inner.tar": (tar, "outer.zip"),
                "outer.zip!inner.tar!payload.gz": (COMPRESSED, "outer.zip!inner.tar"),
                "outer.zip!inner.tar!payload.gz!outer.zip!inner.tar!payload": (
                    PAYLOAD,
                    "outer.zip!inner.tar!payload.gz",
                ),
            },
        )
        self.assertEqual(namespace["warnings"], [])
        self.assertEqual(caught, [])
        self.assertEqual(after, content)

    def test_malformed_gzip_is_visible_failure_without_mutation(self):
        for malformed in (b"not gzip", COMPRESSED[:-5]):
            for rolled in (False, True):
                with self.subTest(truncated=malformed != b"not gzip", rolled=rolled):
                    namespace, observed, records, caught, after = self.inspect_bytes(
                        self.candidate, malformed, "broken.gz", rolled
                    )
                    self.assert_records(records, observed, {"broken.gz": (malformed, None)})
                    self.assertEqual(len(namespace["warnings"]), 1)
                    failure = namespace["warnings"][0]
                    self.assertEqual(failure["locator"], "broken.gz")
                    self.assertEqual(failure["reason"], "container_inspection_failed")
                    self.assertIn(failure["exception_type"], ("BadGzipFile", "EOFError"))
                    self.assertEqual(caught, [])
                    self.assertEqual(after, malformed)

    def test_malformed_nested_gzip_retains_parent_and_failure(self):
        for kind in ("tar", "zip"):
            with self.subTest(kind=kind):
                content = archive_bytes(kind, "broken.gz", b"not gzip")
                locator = "outer." + kind
                child = locator + "!broken.gz"
                namespace, observed, records, caught, after = self.inspect_bytes(self.candidate, content, locator)
                self.assert_records(records, observed, {locator: (content, None), child: (b"not gzip", locator)})
                self.assertEqual(
                    namespace["warnings"],
                    [{"locator": child, "reason": "container_inspection_failed", "exception_type": "BadGzipFile"}],
                )
                self.assertEqual(caught, [])
                self.assertEqual(after, content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
