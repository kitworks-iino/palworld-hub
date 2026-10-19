"""Checks for the bounded current-build adapter; never launches the game."""
from __future__ import annotations

import ctypes
import hashlib
import mmap
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_current_native_runtime as current  # noqa: E402


class CurrentNativeAdapterTests(unittest.TestCase):
    def test_relative_targets_are_signed_and_require_real_transfer_instructions(self):
        self.assertEqual(current.direct_target(0x1000, b"\xe8" + struct.pack("<i", -0x205)), 0xE00)
        self.assertEqual(current.direct_target(0x1000, b"\xe9" + struct.pack("<i", 0x2FB)), 0x1300)
        for instruction in (b"\x90" * 5, b"\xe8\0", b"\xe8" + b"\0" * 5):
            with self.assertRaisesRegex(RuntimeError, "direct rel32"):
                current.direct_target(0x1000, instruction)

    def test_unknown_manager_instruction_or_offset_is_refused(self):
        original = current.HOOK_PREFIXES["MANAGER_HELPER"]
        for index in (4, 5, 11, 12):
            altered = bytearray(original)
            altered[index] ^= 1
            with self.assertRaisesRegex(RuntimeError, "Unknown manager prologue"):
                current.manager_trampoline(0x100000, bytes(altered))

    @unittest.skipUnless(sys.platform == "linux" and os.uname().machine == "x86_64", "x86-64 relocation check")
    def test_relocated_manager_branch_preserves_null_flagged_and_normal_paths(self):
        # This tiny synthetic function is our own test fixture, not game code.
        # It uses the exact reviewed prefix, then returns null for null/flagged
        # objects and returns its argument otherwise. Test both paths after the
        # original entry has been overwritten, just as a hook would do.
        page = mmap.mmap(-1, mmap.PAGESIZE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        base = ctypes.addressof(ctypes.c_char.from_buffer(page))
        fixture = current.HOOK_PREFIXES["MANAGER_HELPER"] + \
            bytes.fromhex("74 05 31 c0 5b c3 cc 48 89 f8 5b c3")
        trampoline = current.manager_trampoline(base, current.HOOK_PREFIXES["MANAGER_HELPER"])
        page[:len(fixture)] = fixture
        page[128:128 + len(trampoline)] = trampoline
        libc = ctypes.CDLL(None)
        libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
        libc.mprotect.restype = ctypes.c_int
        self.assertEqual(libc.mprotect(base, mmap.PAGESIZE, mmap.PROT_READ | mmap.PROT_EXEC), 0)
        function_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
        original, relocated = function_type(base), function_type(base + 128)
        ordinary = (ctypes.c_ubyte * 16)()
        flagged = (ctypes.c_ubyte * 16)()
        flagged[11] = 0x20
        cases = [(None, None), (ctypes.addressof(ordinary), ctypes.addressof(ordinary)),
                 (ctypes.addressof(flagged), None)]
        try:
            for argument, expected in cases:
                self.assertEqual(original(argument), expected)
                self.assertEqual(relocated(argument), expected)
            self.assertEqual(libc.mprotect(base, mmap.PAGESIZE, mmap.PROT_READ | mmap.PROT_WRITE), 0)
            page[:13] = b"\xcc" * 13
            self.assertEqual(libc.mprotect(base, mmap.PAGESIZE, mmap.PROT_READ | mmap.PROT_EXEC), 0)
            for argument, expected in cases:
                self.assertEqual(relocated(argument), expected)
        finally:
            page.close()

    def test_accessor_collection_refuses_missing_boundary(self):
        with self.assertRaisesRegex(RuntimeError, "did not return"):
            current.routine_prefix([{"address": 1, "bytes": "90", "assembly": "nop"}])
        with self.assertRaisesRegex(RuntimeError, "padding"):
            current.routine_prefix([{"address": 1, "bytes": "cc", "assembly": "int3"}])

    def test_game_execution_requires_github_and_separate_offline_namespace(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GitHub runner"):
                current.require_offline_runner()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            with mock.patch.object(os, "readlink", return_value="net:[1]"):
                with self.assertRaisesRegex(RuntimeError, "separate network namespace"):
                    current.require_offline_runner()

    def test_collected_helper_bytes_cannot_approve_their_own_execution(self):
        gate = {"helperWindows": {"GET_TRIBE": {"sha256": "unreviewed"}}}
        with mock.patch.dict(current.REVIEWED_HELPERS, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "complete review before execution"):
                current.require_reviewed_helpers(mock.Mock(), {}, gate)
        self.assertNotIn("reviewedHelperBodies", gate)

    def test_refusal_report_cannot_overwrite_source_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            source = path / "raw.json"
            source.write_text('{"original":true}')
            for output, gate in [(source, path / "gate.json"), (path / "output.json", source),
                                 (path / "same.json", path / "same.json")]:
                with self.assertRaisesRegex(RuntimeError, "overlap"):
                    current.validate_output_paths(output, gate, {source})
            self.assertEqual(source.read_text(), '{"original":true}')

    @unittest.skipUnless(shutil.which("gcc"), "C compiler required")
    def test_generated_probe_compiles_and_keeps_original_source_unchanged(self):
        # Arbitrary test addresses provide compilation coverage only. They are
        # never loaded or treated as evidence about the game executable.
        names = ("MANAGER_HELPER", "GENERATE_KEYS", "FIND_ROW", "UNIQUE_FIND_ROW",
                 "MANAGER_FIND_ROW", "FREE", "ARRAY_GROW", "GET_TRIBE", "BREED", "BOSS_VARIANT")
        addresses = {name: 0x1000000 + index * 0x1000 for index, name in enumerate(names)}
        original_hash = hashlib.sha256(current.fixed.PROBE_SOURCE.read_bytes()).hexdigest()
        generated = current.generate_probe(addresses)
        self.assertIn('"current-build-native-runtime-matched"', generated)
        self.assertNotIn("return *(void **)((uint8_t *)second_owner + 0x5a0)", generated)
        self.assertIn("grow(result, 0);", generated)
        self.assertIn("g_manager_helper_trampoline(object)", generated)
        self.assertIn("_mm_getcsr()", generated)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            source = path / "probe.c"
            source.write_text(generated, encoding="utf-8")
            current.fixed.compile_shared(source, path / "probe.so", "-pthread")
        self.assertEqual(hashlib.sha256(current.fixed.PROBE_SOURCE.read_bytes()).hexdigest(), original_hash)


if __name__ == "__main__":
    unittest.main()
