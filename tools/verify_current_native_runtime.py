#!/usr/bin/env python3
"""Run the reviewed Build 25247047 breeding function against all fixed pairs.

This is a separate, deliberately build-bounded adapter.  It never rewrites the
fixed-build tools or evidence.  It verifies the current Steam files and known
machine-code layouts before compiling a derived copy of the fixed C harness.
Only an isolated GitHub runner network namespace may execute the game.

The result concerns the native child-species function with extracted rows
injected through table accessors.  It does not verify farm assignment or eggs
hatched through the complete game flow.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import Any

import compare_current_game_evidence as comparison
import extract_current_game_evidence as extraction
import verify_native_breeding_runtime as fixed


ROOT = Path(__file__).resolve().parents[1]
BUILD = "25247047"
VERSION = "1.0.5.102999"
MANIFEST = "7031055933861146620"
BINARY_BYTES = 196_506_712
BINARY_SHA256 = "8d5c5cb6277a46713df2ad329d7b6887068b39fa98fcf84b8a5dfa3a00caa666"
PAK_BYTES = 4_570_950_001
PAK_SHA256 = "8cb60497f18b047897a3dd16445b0be4e654797eea655fe9fe0b65991dc33d6b"
RAW_SHA256 = "f1b7e8e6c6b101a35843c3bf654cf9bdd5990d6c336caee44ba7fdec6959fbfc"
PALS_SHA256 = "584c969e0d9d4e9d0b64154b862baa5314914ff3cbe706d15aada035d464984c"
CORE_REGIONS = {
    "breeding-result-orchestration": (
        0x7132F80, 990,
        "efebddb0356b4e34cede3b8b42fccec6d24023a3fa0ffde62f9a9d693c7b212f",
    ),
    "normal-child-candidate-selection": (
        0x7135020, 721,
        "ef5db9af6daa80ef982931fe3bb26673dde5a5a20d56a8fd30f6edcc278c6265",
    ),
}
HOOK_PREFIXES = {
    "MANAGER_HELPER": bytes.fromhex("53 48 85 ff 74 09 48 89 fb f6 47 0b 60"),
    "FIND_ROW": bytes.fromhex("41 57 41 56 53 48 8b 5f 28 48 85 db"),
    "UNIQUE_FIND_ROW": bytes.fromhex("41 57 41 56 53 48 8b 5f 28 48 85 db"),
    "GENERATE_KEYS": bytes.fromhex("53 48 89 fb 0f 57 c0 0f 11 07 48 8d 7e 30"),
    "MANAGER_FIND_ROW": bytes.fromhex("41 57 41 56 41 54 53 48 81 ec 18 01 00 00"),
}
# These three bodies consume modeled object/row fields outside the reviewed
# orchestration/candidate functions. Collection alone cannot approve its own
# output: complete function boundaries, branches and field reads must first be
# reviewed and their exact hashes committed here. A missing profile always
# refuses game execution while retaining the newly collected helper windows.
REVIEWED_HELPERS: dict[str, tuple[int, int, str]] = {
    # Complete bodies from run 39239451919, independently reviewed before
    # execution. GET_TRIBE includes its null-row return after the first ret.
    "PARENT_TRIBE": (0x7291470, 25,
                     "56b7e85ab5e8e27c6bcb699020e87f6bdac47e1b5d5c5f63daed4efe02fa51ee"),
    "GET_TRIBE": (0x7156780, 21,
                  "66ef10bb48cca7503ca5a512e53bcdf7a90654784aa37cfef26be903eabddac9"),
    "UNIQUE_MEMBERSHIP": (0x715FEE0, 306,
                          "a6ce1713f03584f18f1f13d9066ae86a821c0e370ab0ccf7e2063b77d3d5cf8c"),
}
REQUIRED_HELPER_REVIEWS = ("PARENT_TRIBE", "GET_TRIBE", "UNIQUE_MEMBERSHIP")
EXCLUDED_BOSS_VARIANT = 0x7135300
DISASM_LINE = re.compile(r"^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_output_paths(output: Path, gate_output: Path, inputs: set[Path]) -> None:
    protected = {path.resolve() for path in inputs}
    require(output.resolve() not in protected and gate_output.resolve() not in protected and
            output.resolve() != gate_output.resolve(), "Output paths overlap input evidence")


def direct_target(address: int, instruction: bytes) -> int:
    require(len(instruction) == 5 and instruction[0] in (0xE8, 0xE9),
            f"Not a direct rel32 call/jump at {address:#x}")
    return address + 5 + struct.unpack_from("<i", instruction, 1)[0]


def indirect_jump(address: int) -> bytes:
    """An absolute jump which preserves every register and the flags."""
    return b"\xff\x25\0\0\0\0" + struct.pack("<Q", address)


def manager_trampoline(address: int, prefix: bytes) -> bytes:
    # The one short jz targets +15, outside the 13 overwritten bytes.  Invert it
    # over a register-preserving absolute jump; continue after the whole test.
    require(prefix == HOOK_PREFIXES["MANAGER_HELPER"], "Unknown manager prologue")
    return prefix[:4] + b"\x75\x0e" + indirect_jump(address + 15) + \
        prefix[6:] + indirect_jump(address + len(prefix))


class ElfImage:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.sections = extraction.elf_sections(self.data)
        require(struct.unpack_from("<H", self.data, 16)[0] == 2,
                "Runtime adapter requires the reviewed non-PIE ET_EXEC")
        require(struct.unpack_from("<H", self.data, 18)[0] == 62, "Expected x86-64 ELF")

    def read(self, address: int, size: int) -> bytes:
        section = next((item for item in self.sections
                        if item["type"] != 8 and item["virtualAddress"] <= address and
                        address + size <= item["virtualAddress"] + item["bytes"]), None)
        require(section is not None, f"Unmapped ELF read: {address:#x}+{size}")
        offset = section["fileOffset"] + address - section["virtualAddress"]
        return self.data[offset:offset + size]

    def call(self, address: int) -> int:
        target = direct_target(address, self.read(address, 5))
        text = next(item for item in self.sections if item["name"] == ".text")
        require(text["virtualAddress"] <= target < text["virtualAddress"] + text["bytes"],
                f"Call target outside .text: {address:#x} -> {target:#x}")
        return target

    def instructions(self, address: int, size: int) -> list[dict[str, Any]]:
        output = subprocess.run([
            "objdump", "-d", "-Mintel", "--insn-width=16",
            f"--start-address={address}", f"--stop-address={address + size}", str(self.path),
        ], check=True, stdout=subprocess.PIPE, text=True).stdout
        result = []
        cursor = address
        for line in output.splitlines():
            match = DISASM_LINE.match(line)
            if not match:
                continue
            location = int(match[1], 16)
            code = bytes.fromhex(match[2])
            require(location == cursor, f"Disassembly gap at {cursor:#x}")
            require(self.read(location, len(code)) == code, "Disassembly bytes differ from ELF")
            assembly = re.sub(r"\s+", " ", match[3].split(" # ", 1)[0]).strip()
            result.append({"address": location, "bytes": code.hex(), "assembly": assembly})
            cursor += len(code)
        require(result and cursor == address + size, f"Incomplete disassembly at {address:#x}")
        return result

    def window(self, address: int, size: int) -> dict[str, Any]:
        code = self.read(address, size)
        return {"virtualAddress": hex(address), "bytes": size, "sha256": sha(code),
                "disassembly": self.instructions(address, size)}


def routine_prefix(instructions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A short accessor must end in ret or a tail jump before any padding."""
    result = []
    for instruction in instructions:
        assembly = instruction["assembly"]
        require(not assembly.startswith(("int3", "(bad)", ".byte")),
                "Accessor contains padding/undecodable bytes before its return")
        result.append(instruction)
        if assembly == "ret" or bytes.fromhex(instruction["bytes"])[:1] == b"\xe9":
            return result
    raise RuntimeError("Accessor did not return or tail-jump inside collection window")


def validate_getters(image: ElfImage, addresses: dict[str, int], gate: dict[str, Any]) -> None:
    # These accessors are called by the exact, hash-reviewed orchestration body.
    expected = {
        "PARENT_CHARACTER_ID": bytes.fromhex("48 8b 87 d0 03 00 00 c3"),
        # The current getter returns al; the reviewed caller compares al/r15b.
        "PARENT_GENDER": bytes.fromhex("8a 87 e0 03 00 00 c3"),
    }
    for name, prefix in expected.items():
        require(image.read(addresses[name], len(prefix)) == prefix,
                f"Current {name} is not the reviewed direct field accessor")
    parent = routine_prefix(image.instructions(addresses["PARENT_TRIBE"], 128))
    parent_asm = [item["assembly"] for item in parent]
    transfers = [item for item in parent if bytes.fromhex(item["bytes"])[:1] in (b"\xe8", b"\xe9")]
    require(len(transfers) == 2, "Unexpected parent-tribe call graph")
    require(direct_target(transfers[0]["address"], bytes.fromhex(transfers[0]["bytes"])) ==
            addresses["MANAGER_HELPER"], "Parent tribe accessor does not use the gated manager helper")
    discovered_tribe = direct_target(transfers[1]["address"], bytes.fromhex(transfers[1]["bytes"]))
    require(addresses.get("GET_TRIBE") == discovered_tribe,
            "Parent tribe accessor target differs from the reviewed tribe getter")
    # Permit only the ordinary SysV this/name forwarding sequence.  Any extra
    # field, capability check, branch or helper must be reviewed before use.
    allowed = {
        "push rbx", "mov rbx,rdi", "mov rsi,QWORD PTR [rbx+0x3d0]",
        "mov rdi,rax", "pop rbx", "ret", "sub rsp,0x8", "add rsp,0x8",
    }
    require(all(item in allowed or item.startswith(("call ", "jmp ")) for item in parent_asm),
            "Unknown instruction in parent tribe accessor")
    require("mov rsi,QWORD PTR [rbx+0x3d0]" in parent_asm,
            "Parent tribe accessor does not read CharacterID at +0x3d0")
    getter_window = image.window(addresses["GET_TRIBE"], 128)
    gate["helperWindows"]["GET_TRIBE"] = getter_window
    getter = routine_prefix(getter_window["disassembly"])
    transfers = [item for item in getter if bytes.fromhex(item["bytes"])[:1] == b"\xe8"]
    require(len(transfers) == 1 and direct_target(transfers[0]["address"], bytes.fromhex(transfers[0]["bytes"])) ==
            addresses["MANAGER_FIND_ROW"], "Tribe getter does not use the gated manager row lookup")
    assembly = [item["assembly"] for item in getter_window["disassembly"]]
    require(any(item.startswith("movzx eax,WORD PTR [rax+0x2a]") for item in assembly),
            "Tribe field +0x2a is not supported by the current native getter")
    # No additional row fields may be silently initialized to zero in the model.
    row_offsets = set(re.findall(r"\[rax(?:\+(0x[0-9a-f]+))?\]", "\n".join(item["assembly"] for item in getter)))
    require(row_offsets <= {"0x2a"}, f"Unknown fields read by tribe getter: {sorted(row_offsets)}")
    gate["fieldOffsets"]["parentCharacterId"] = "0x3d0"
    gate["fieldOffsets"]["parentGender"] = "0x3e0"
    gate["fieldOffsets"]["rawTribe"] = "0x2a"


def require_reviewed_helpers(image: ElfImage, addresses: dict[str, int], gate: dict[str, Any]) -> None:
    missing = [name for name in REQUIRED_HELPER_REVIEWS if name not in REVIEWED_HELPERS]
    require(not missing, "Current helper bodies require complete review before execution: " + ", ".join(missing))
    for name in REQUIRED_HELPER_REVIEWS:
        address, length, digest = REVIEWED_HELPERS[name]
        require(name not in addresses or addresses[name] == address, f"Reviewed helper address differs: {name}")
        require(sha(image.read(address, length)) == digest, f"Reviewed helper body differs: {name}")
        addresses[name] = address
        gate.setdefault("reviewedHelperBodies", {})[name] = {
            "virtualAddress": hex(address), "bytes": length, "sha256": digest,
            "fieldReadsAndAllReachableBranchesReviewed": True,
        }


def collect_gate(image: ElfImage, static: dict[str, Any], gate: dict[str, Any]) -> dict[str, int]:
    regions = {item["name"]: item for item in static["candidateRegions"]}
    for name, (address, length, digest) in CORE_REGIONS.items():
        region = regions[name]
        require(int(region["virtualAddress"], 0) == address, f"Unexpected {name} address")
        require(sha(image.read(address, length)) == digest, f"Reviewed {name} body changed")
        require(sha(image.read(address, region["bytes"])) == region["sha256"],
                f"Current static artifact and executable differ for {name}")
        gate["reviewedCoreRegions"].append({"name": name, "virtualAddress": hex(address),
                                             "bytes": length, "sha256": digest})
    addresses = {
        "BREED": CORE_REGIONS["breeding-result-orchestration"][0],
        "NEAREST": CORE_REGIONS["normal-child-candidate-selection"][0],
        "MANAGER_HELPER": image.call(0x7132F9D),
        "GENERATE_KEYS": image.call(0x7132FE2),
        "FIND_ROW": image.call(0x713512F),
        "UNIQUE_FIND_ROW": image.call(0x71330AE),
        "MANAGER_FIND_ROW": image.call(0x713329C),
        "FREE": image.call(0x7133150),
        "ARRAY_GROW": image.call(0x7135095),
        "UNIQUE_MEMBERSHIP": image.call(0x7135172),
        "PARENT_TRIBE": image.call(0x7132FB4),
        "PARENT_CHARACTER_ID": image.call(0x7133291),
        "PARENT_GENDER": image.call(0x7133165),
    }
    require(image.call(0x7133326) == addresses["NEAREST"], "Normal selection call does not connect")
    require(image.call(0x7135052) == addresses["GENERATE_KEYS"], "Table-key helper mismatch")
    require(image.call(0x713526E) == addresses["MANAGER_FIND_ROW"], "Priority lookup helper mismatch")
    require(image.call(0x7132FC6) == addresses["PARENT_TRIBE"], "Second parent tribe helper mismatch")
    require(image.call(0x7133172) == addresses["PARENT_GENDER"], "Second parent gender helper mismatch")
    require(image.call(0x71332B8) == addresses["PARENT_CHARACTER_ID"], "Second parent name helper mismatch")
    for call in (0x7135144, 0x713520B, 0x71352BC, 0x7133338):
        require(image.call(call) == addresses["FREE"], "Native deallocator call graph differs")
    # Collect all relevant windows before any adaptive check can fail, so a
    # refused first run still provides enough evidence for a bounded review.
    for name, address in addresses.items():
        if name in ("BREED", "NEAREST"):
            continue
        size = 1024 if name in ("UNIQUE_MEMBERSHIP", "ARRAY_GROW") else 128
        gate["helperWindows"][name] = image.window(address, size)
    # The parent tribe accessor forwards to another getter not present in the
    # earlier static artifact. Collect its direct callees before accepting any
    # accessor shape, including when that shape turns out to need review.
    transfers = [item for item in gate["helperWindows"]["PARENT_TRIBE"]["disassembly"]
                 if bytes.fromhex(item["bytes"])[:1] in (b"\xe8", b"\xe9")]
    for index, instruction in enumerate(transfers[:10]):
        address = direct_target(instruction["address"], bytes.fromhex(instruction["bytes"]))
        if address not in addresses.values():
            window = image.window(address, 256)
            window["collectedFromTransfer"] = hex(instruction["address"])
            gate["helperWindows"][f"PARENT_TRIBE_CALLEE_{index}"] = window
    gate["addresses"] = {name: hex(value) for name, value in addresses.items()}
    for name, prefix in HOOK_PREFIXES.items():
        require(image.read(addresses[name], len(prefix)) == prefix,
                f"Unsafe or changed {name} hook prefix")
        gate["hookPrefixes"][name] = {"address": hex(addresses[name]), "bytes": prefix.hex(),
                                      "wholeInstructions": True,
                                      "shortConditionalBranchRelocated": name == "MANAGER_HELPER"}
    # The already reviewed nearest body proves the grow helper's ABI: the
    # TArray has pointer/count/capacity at 0/8/12, a pre-incremented count, and
    # receives its previous count in esi; the subsequent write has stride 8.
    grow_before = bytes.fromhex("48 89 54 24 28 48 8d 7c 24 10 48 8b 74 24 28")
    grow_after = bytes.fromhex("48 8b 54 24 28 48 8b 44 24 10 48 63 ca 4c 89 34 c8")
    require(image.read(0x7135086, len(grow_before)) == grow_before and
            image.read(0x713509A, len(grow_after)) == grow_after, "Unknown native TArray grow ABI")
    gate["allocator"] = {
        "method": "native 8-byte TArray grow helper reached from reviewed nearest function",
        "growAddress": hex(addresses["ARRAY_GROW"]), "freeAddress": hex(addresses["FREE"]),
        "libcMemoryPassedToGameFree": False, "guessedMallocAddress": False,
        "arrayOffsets": {"data": 0, "count": 8, "capacity": 12},
    }
    require(image.read(0x735AB8, 4) == struct.pack("<f", 0.5), "Rank multiplier is not +0.5")
    require(image.read(0x735A28, 4) == struct.pack("<f", -0.5), "Rank rounding constant is not -0.5")
    gate["rankConstants"] = {"multiplier": 0.5, "roundingOffset": -0.5}
    gate["fieldOffsets"].update({"rawBoss": "0xcc", "rawRank": "0x100",
                                  "rawPriority": "0x104", "rawIgnoreCombi": "0x108",
                                  "uniqueParentA": "0x8", "uniqueGenderA": "0xa",
                                  "uniqueParentB": "0xc", "uniqueGenderB": "0xe",
                                  "uniqueChild": "0x10", "managerRawTable": "0xd8",
                                  "managerUniqueTable": "0x140"})
    require_reviewed_helpers(image, addresses, gate)
    validate_getters(image, addresses, gate)
    membership = gate["helperWindows"]["UNIQUE_MEMBERSHIP"]["disassembly"]
    membership_text = "\n".join(item["assembly"] for item in membership)
    require("+0x140]" in membership_text and "+0x10]" in membership_text,
            "Unique membership function does not support current injected row layout")
    # Review found three additional raw-row fields (+0xcd/+0xce/+0xd0) in
    # alpha/boss post-processing. They are outside this base-child audit and
    # must never be silently supplied as zero then reported as verified.
    # The complete reviewed child bodies return without calling that function.
    reviewed_calls = []
    for name, (address, length, _) in {**CORE_REGIONS, **REVIEWED_HELPERS}.items():
        for item in image.instructions(address, length):
            code = bytes.fromhex(item["bytes"])
            if item["assembly"].startswith("call "):
                require(code[:1] == b"\xe8", f"Unreviewed indirect call in {name}")
                target = direct_target(item["address"], code)
                require(target != EXCLUDED_BOSS_VARIANT,
                        f"Base-child code calls excluded alpha post-processing: {name}")
                reviewed_calls.append({"function": name, "callAddress": hex(item["address"]),
                                       "targetAddress": hex(target)})
    gate["baseChildScope"] = {
        "bossAlphaPostProcessingInvoked": False,
        "excludedNativeFunctionAddress": hex(EXCLUDED_BOSS_VARIANT),
        "reviewedFunctionDirectCallsExcludeBoss": True,
        "reviewedDirectCalls": reviewed_calls,
        "reason": "Alpha post-processing reads additional unmodeled raw fields +0xcd/+0xce/+0xd0; the generated probe omits that function and all mapping checks.",
    }
    gate["addresses"] = {name: hex(value) for name, value in addresses.items()}
    gate["status"] = "current-runtime-machine-layout-matched"
    return addresses


def replace_once(source: str, old: str, new: str) -> str:
    require(source.count(old) == 1, f"Fixed C template changed around: {old[:80]}")
    return source.replace(old, new, 1)


def c_bytes(data: bytes) -> str:
    return ", ".join(f"0x{item:02x}" for item in data)


def remove_alpha_probe(source: str) -> str:
    """Remove execution and success claims for unmodeled alpha post-processing."""
    source = replace_once(source, "#define ADDRESS_BOSS_VARIANT ((uintptr_t)0x7118c40)\n", "")
    source = replace_once(source, """struct boss_mapping {
    uint16_t released_index;
    int16_t boss_source;
    uint16_t source_tribe;
    uint16_t boss_tribe;
    uint8_t valid;
};

""", "")
    source = replace_once(source, "typedef uint64_t (*boss_variant_fn)(void *, uint64_t);\n", "")
    source = replace_once(source, """    const struct boss_mapping *boss_mappings,
    uint32_t boss_mapping_count,
    uint32_t boss_mapping_mismatch_count,
""", "")
    source = replace_once(source,
                          "logical_mismatch_count == 0u && boss_mapping_mismatch_count == 0u &&",
                          "logical_mismatch_count == 0u &&")
    source = replace_once(source, r'''            "  \"bossVariantMappingCount\": %u,\n"
            "  \"bossVariantMappingMismatchCount\": %u,\n",''',
                          r'''            "  \"bossAlphaPostProcessingInvoked\": false,\n",''')
    source = replace_once(source, """            special_mismatch_count, normal_mismatch_count, boss_mapping_count,
            boss_mapping_mismatch_count);""", "            special_mismatch_count, normal_mismatch_count);")
    start = source.index(r'''    fputs("\n  ],\n", output);

    fputs("  \"bossVariantMappings\": [", output);''')
    stop = source.index("    if (fflush(output)", start)
    source = source[:start] + r'''    fputs("\n  ]\n}\n", output);

''' + source[stop:]
    source = replace_once(source, "    boss_variant_fn boss_variant = (boss_variant_fn)ADDRESS_BOSS_VARIANT;\n", "")
    source = replace_once(source, """    struct boss_mapping *boss_mappings = calloc(header->released_count, sizeof(*boss_mappings));
    bool *released_sources = calloc(header->raw_count, sizeof(*released_sources));
""", "")
    source = replace_once(source,
                          "pair_mismatches == NULL || boss_mappings == NULL || released_sources == NULL)",
                          "pair_mismatches == NULL)")
    source = replace_once(source, "        released_sources[released[index].source_order] = true;\n", "")
    start = source.index("    uint32_t boss_mapping_count = 0u;")
    stop = source.index("    int write_status = write_result(", start)
    source = source[:start] + source[stop:]
    source = replace_once(source, """        pair_mismatch_count, logical_mismatch_count, boss_mappings, boss_mapping_count,
        boss_mapping_mismatch_count, parent_order_mismatch_count,""",
                          "        pair_mismatch_count, logical_mismatch_count, parent_order_mismatch_count,")
    source = replace_once(source, "    free(released_sources);\n    free(boss_mappings);\n", "")
    require(not any(token in source for token in
                    ("BOSS_VARIANT", "boss_variant", "boss_mapping", "bossVariant", "released_sources")),
            "Derived base-child probe retains alpha execution or mapping claims")
    return source


def generate_probe(addresses: dict[str, int]) -> str:
    source = remove_alpha_probe(fixed.PROBE_SOURCE.read_text(encoding="utf-8"))
    # Only this temporary string is modified. Original source and old reports
    # remain reproducible, and the derived source is hashed in the new report.
    original_addresses = dict(re.findall(r"#define ADDRESS_(\w+) \(\(uintptr_t\)(0x[0-9a-f]+)\)", source))
    for name, old in original_addresses.items():
        value = addresses.get(name, 0)
        source = source.replace(old, hex(value))
    source = source.replace("24181105", BUILD).replace("fixed-build", "current-build")
    source = source.replace("Fixed-build Palworld native breeding runtime probe.",
                            "Current-build extracted-table native breeding runtime probe.")
    start = source.index("static void *manager_helper_hook(void *object) {")
    stop = source.index("static int name_index(", start)
    source = source[:start] + """static get_owner_fn g_manager_helper_trampoline = NULL;

static void *manager_helper_hook(void *object) {
    if (object == g_parent_a || object == g_parent_b) {
        return atomic_load_explicit(&g_manager, memory_order_acquire);
    }
    return g_manager_helper_trampoline(object);
}

""" + source[stop:]
    source = replace_once(source, """    alloc_fn runtime_alloc = (alloc_fn)ADDRESS_ALLOC;
    result->data = runtime_alloc((size_t)count * sizeof(*result->data), 0u);
    if (result->data == NULL) {
        return result;
    }
    memcpy(result->data, names, (size_t)count * sizeof(*result->data));
    result->count = (int32_t)count;
    result->capacity = (int32_t)count;
""", f"""    typedef void (*array_grow_fn)(struct runtime_array *, int32_t);
    array_grow_fn grow = (array_grow_fn)(uintptr_t){addresses['ARRAY_GROW']:#x};
    result->count = (int32_t)count;
    grow(result, 0);
    if (result->data == NULL || result->capacity < (int32_t)count) {{
        /* This cannot be treated as a successful empty native table. */
        abort();
    }}
    memcpy(result->data, names, (size_t)count * sizeof(*result->data));
""")
    old_prefix = """    static const uint8_t manager_prefix[12] = {
        0x53, 0x48, 0x85, 0xff, 0x74, 0x09, 0x48, 0x89, 0xfb, 0xf6, 0x47, 0x0b,
    };
"""
    trampoline = manager_trampoline(addresses["MANAGER_HELPER"], HOOK_PREFIXES["MANAGER_HELPER"])
    new_prefix = f"""    static const uint8_t manager_prefix[13] = {{
        {c_bytes(HOOK_PREFIXES['MANAGER_HELPER'])},
    }};
    static const uint8_t manager_relocated[{len(trampoline)}] = {{
        {c_bytes(trampoline)},
    }};
"""
    source = replace_once(source, old_prefix, new_prefix)
    source = replace_once(source, """    return install_absolute_hook(ADDRESS_MANAGER_HELPER, manager_prefix, sizeof(manager_prefix),
                                 (uintptr_t)&manager_helper_hook, NULL);
""", """    long manager_page_size = sysconf(_SC_PAGESIZE);
    if (manager_page_size <= 0) return -1;
    void *manager_copy = mmap(NULL, (size_t)manager_page_size, PROT_READ | PROT_WRITE,
                              MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (manager_copy == MAP_FAILED) return -1;
    memcpy(manager_copy, manager_relocated, sizeof(manager_relocated));
    if (mprotect(manager_copy, (size_t)manager_page_size, PROT_READ | PROT_EXEC) != 0) {
        munmap(manager_copy, (size_t)manager_page_size);
        return -1;
    }
    g_manager_helper_trampoline = (get_owner_fn)(uintptr_t)manager_copy;
    return install_absolute_hook(ADDRESS_MANAGER_HELPER, manager_prefix, sizeof(manager_prefix),
                                 (uintptr_t)&manager_helper_hook, NULL);
""")
    # Check the rounding mode rather than forcing it to fit the model. The real
    # cvtss2si instruction is MXCSR-dependent; other modes must fail explicitly.
    source = replace_once(source, "#include <unistd.h>", "#include <unistd.h>\n#include <xmmintrin.h>")
    source = replace_once(source, "    uint64_t invocation_count = 0u;", """    uint64_t invocation_count = 0u;
    if ((_mm_getcsr() & 0x6000u) != 0u) {
        write_failure(output_path, "unexpected-native-float-rounding-mode");
        kill(getpid(), SIGTERM);
        return NULL;
    }""")
    # Ensure no unbound old helper can accidentally be called in the new source.
    require("ADDRESS_GET_OWNER;" not in source and "ADDRESS_ALLOC;" not in source,
            "Derived probe retains an unverified owner/allocator call")
    return source


def validate_current_inputs(raw_path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    require(fixed.sha256_file(raw_path) == RAW_SHA256, "Current extraction hash differs from reviewed artifact")
    require(raw.get("buildId") == BUILD and raw.get("gameVersion") == VERSION,
            "Current extraction target mismatch")
    baseline = json_file(fixed.RAW_ASSETS)
    require(fixed.sha256_file(fixed.RAW_ASSETS) == comparison.fixed.RAW_ASSETS_SHA256,
            "Fixed extraction hash mismatch")
    expected_rows = comparison.predicted_rows(comparison.normalise(baseline))
    require(expected_rows == comparison.fixed.decode_compact(json_file(fixed.BREEDING)),
            "Fixed expected table does not match the independently computed baseline")
    baseline_report_path = ROOT / "audit/native-runtime-comparison.json"
    require(fixed.sha256_file(baseline_report_path) == comparison.fixed.NATIVE_RUNTIME_EVIDENCE_SHA256,
            "Pinned fixed runtime evidence has changed")
    baseline_report = json_file(baseline_report_path)
    # Public pal JSON subsequently acquired local icon provenance. The complete
    # published file has its own pinned hash; the old runtime JSON predates that
    # non-breeding metadata. Pair bytes still match the old native evidence.
    require(PALS_SHA256 == fixed.sha256_file(fixed.PALS) and
            baseline_report["inputs"]["breedingSha256"] == fixed.sha256_file(fixed.BREEDING),
            "Expected tables have drifted from their fixed runtime verification")
    result = comparison.compare_assets(baseline, raw)
    require(result["breedingInputs"]["equal"], "Current native-model input fields differ")
    require(result["roster"]["sameIdSet"] and result["roster"]["sameDisplayOrder"], "Current roster changed")
    require(result["predictedResults"]["status"] == "matched", "Current expected result table differs")
    # The unchanged fixed encoder also records dex indices. Validate every
    # encoded source field independently, not just the public roster/hash.
    fields = ("sourceOrder", "combiRank", "combiDuplicatePriority", "zukanIndex", "isBoss", "ignoreCombi")
    require(len(baseline["pals"]) == len(raw["pals"]), "Raw input count differs")
    for old, current in zip(baseline["pals"], raw["pals"], strict=True):
        require(all(old[field] == current[field] for field in fields), "Encoded current raw field differs")
        require(fixed.enum_tail(old["tribe"]).lower() == fixed.enum_tail(current["tribe"]).lower(),
                "Encoded current tribe differs")
    return result


def validate_files(server: Path, raw_path: Path, provenance_path: Path,
                   static_path: Path) -> tuple[Path, dict, dict, dict]:
    binary = server / "Pal/Binaries/Linux/PalServer-Linux-Shipping"
    pak = server / "Pal/Content/Paks/Pal-LinuxServer.pak"
    require(binary.is_file() and pak.is_file(), "Current server files are missing")
    require(binary.stat().st_size == BINARY_BYTES and pak.stat().st_size == PAK_BYTES,
            "Current server file sizes differ")
    require(fixed.sha256_file(binary) == BINARY_SHA256, "Current executable hash differs")
    require(fixed.sha256_file(pak) == PAK_SHA256, "Current PAK hash differs")
    raw, provenance, static = json_file(raw_path), json_file(provenance_path), json_file(static_path)
    require(provenance.get("status") == "current-game-evidence-collected", "Extraction provenance is incomplete")
    require(provenance["steam"]["serverBuildId"] == BUILD and
            provenance["steam"]["serverDepotManifestId"] == MANIFEST, "Steam provenance target differs")
    require(provenance["assets"]["sha256"] == fixed.sha256_file(raw_path), "Raw provenance hash differs")
    require(provenance["nativeStaticEvidence"]["sha256"] == fixed.sha256_file(static_path),
            "Native static provenance hash differs")
    require(static["target"]["serverBuildId"] == BUILD and
            static["executable"]["sha256"] == BINARY_SHA256, "Native static target differs")
    return binary, raw, provenance, static


def require_offline_runner() -> dict[str, Any]:
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Game execution is restricted to a GitHub runner")
    current = os.readlink("/proc/self/ns/net")
    initial = os.readlink("/proc/1/ns/net")
    require(current != initial, "Game execution requires a separate network namespace")
    # /sys may still be mounted for the initial network namespace after unshare.
    # /proc/net resolves through /proc/self/net and reflects this process.
    interfaces = sorted(line.split(":", 1)[0].strip()
                        for line in Path("/proc/net/dev").read_text().splitlines()[2:] if ":" in line)
    require(set(interfaces) <= {"lo"}, f"Network namespace has external interfaces: {interfaces}")
    return {"githubActions": True, "separateNetworkNamespace": True,
            "networkInterfaces": interfaces, "networkNamespace": current,
            "initialNetworkNamespace": initial}


def run_game(binary: Path, server: Path, input_path: Path, probe: Path,
             shim: Path, work: Path, timeout: int) -> tuple[dict, str, int]:
    runtime_output = work / "runtime-output.json"
    environment = {key: value for key, value in os.environ.items()
                   if not key.lower().endswith("_proxy")}
    environment.update({"LD_PRELOAD": f"{shim}:{probe}",
                        "PAL_NATIVE_AUDIT_INPUT": str(input_path),
                        "PAL_NATIVE_AUDIT_OUTPUT": str(runtime_output)})
    # Avoid repurposing HOME or credentials. The dedicated server's writable
    # files live in its transient Steam install, removed by the workflow.
    command = [str(binary), "Pal", "-NoSteam", "-NoEOS", "-log"]
    process = subprocess.Popen(command, cwd=server, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise RuntimeError(f"Current native audit timed out after {timeout}s")
    log = output.decode("utf-8", errors="replace").replace("\x00", "")
    require(runtime_output.is_file(), f"Runtime produced no result (exit {process.returncode}): {log[-3000:]}")
    runtime = json_file(runtime_output)
    require(runtime["status"] == "current-build-native-runtime-matched",
            f"Current native runtime did not match: {json.dumps(runtime)[:3000]}")
    require(f"Game version is v{VERSION}" in log and "Running Palworld dedicated server" in log,
            "Current game did not report its reviewed version and running state")
    return runtime, log, process.returncode


def build_report(runtime: dict, raw: dict, input_evidence: dict, addresses: dict[str, int],
                 isolation: dict, paths: dict[str, Path], exit_code: int) -> dict[str, Any]:
    require(runtime["serverBuildId"] == BUILD, "C probe reported a different build")
    expected_counts = {"nativeInvocationCount": 166_464, "rawPalRowCount": 753,
                       "releasedPalCount": 288, "unorderedPairCount": 41_616,
                       "logicalResultRowCount": 41_617, "uniqueCombinationRowCount": 258}
    for key, value in expected_counts.items():
        require(runtime[key] == value, f"Current native count mismatch: {key}")
    mismatch_keys = {
        "runtimeRowMetadata": "runtimeRowMetadataMismatchCount",
        "runtimeUniqueRows": "runtimeUniqueRowMismatchCount",
        "runtimeLogicalResults": "runtimeLogicalResultMismatchCount",
        "runtimeCalls": "runtimeCallMismatchCount", "parentOrder": "parentOrderMismatchCount",
        "hiddenGender": "hiddenGenderMismatchCount", "sameSpecies": "sameSpeciesMismatchCount",
        "specialCombination": "specialCombinationMismatchCount",
        "normalSelection": "normalSelectionMismatchCount",
    }
    differences = {name: runtime[key] for name, key in mismatch_keys.items()}
    require(all(type(value) is int and value == 0 for value in differences.values()),
            "Current native differences are nonzero")
    require(runtime["maleRuntimeCode"] == 1 and runtime["femaleRuntimeCode"] == 2,
            "Unexpected runtime gender encoding")
    require(runtime.get("bossAlphaPostProcessingInvoked") is False,
            "Current probe did not explicitly exclude unmodeled alpha post-processing")
    tribe_evidence = fixed.validate_runtime_rows(runtime, raw)
    report = {
        "schemaVersion": 2, "status": "current-build-native-runtime-matched",
        "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
        "target": {"gameVersion": f"v{VERSION}", "serverAppId": "2394010", "serverBuildId": BUILD,
                   "serverDepotId": "2394012", "serverDepotManifestId": MANIFEST,
                   "serverExecutableBytes": BINARY_BYTES, "serverExecutableSha256": BINARY_SHA256,
                   "serverPakBytes": PAK_BYTES, "serverPakSha256": PAK_SHA256},
        "invocation": {"nativeFunctionAddress": hex(addresses["BREED"]),
                       "managerHelperAddress": hex(addresses["MANAGER_HELPER"]),
                       "method": "direct current native child-species function with injected extracted tables",
                       "parentOrdersPerGenderOrientation": 2, "genderOrientationsPerPair": 2,
                       "nativeInvocationCount": runtime["nativeInvocationCount"],
                       "harnessHelperScope": "four table-access hooks and one manager hook for synthetic parents; original manager behavior uses a relocated trampoline",
                       "selectionOrRecipeLogicStubbed": False, "internetEgressBlocked": True},
        "counts": {"rawPalRows": 753, "releasedPals": 288, "uniqueCombinationRows": 258,
                   "unorderedParentPairs": 41_616, "logicalResultRows": 41_617,
                   "matchingLogicalResultRows": 41_617, "nativeInvocations": 166_464},
        "differences": differences,
        "gender": {"maleRuntimeCode": 1, "femaleRuntimeCode": 2, "genderDependentPair": "catmage|foxmage"},
        "verificationScope": {"currentNativeExecutableInvoked": True, "extractedTableRowsInjected": True,
                              "livePakDataTablesReadByProbe": False, "baseChildSpeciesIdsVerified": True,
                              "farmAssignmentEligibilityVerified": False, "inGameHatchesObserved": False,
                              "nativeRoundingModeNearestEvenChecked": True,
                              "syntheticFNamesAndTribeIds": True,
                              "bossAlphaPostProcessingVerified": False},
        "runtimeTableIdentity": {**tribe_evidence,
                                 "runtimeRowsSha256": sha(fixed.canonical_bytes(runtime["runtimeRows"]))},
        "bossAlphaPostProcessing": {
            "nativeFunctionAddress": hex(EXCLUDED_BOSS_VARIANT),
            "modeled": False, "status": "not-verified", "nativeFunctionInvoked": False,
            "reason": "The separate alpha post-processing function reads additional raw fields +0xcd/+0xce/+0xd0 that are not injected. It is excluded from this base-child audit; no alpha mapping or hatch outcome is verified.",
        },
        "allDifferences": {"rowMetadata": runtime["rowMetadataMismatches"],
                           "uniqueRows": runtime["uniqueRowMismatches"],
                           "logicalResults": runtime["logicalResultMismatches"]},
        "inputs": {"runtimeInput": input_evidence, "rawAssetsSha256": fixed.sha256_file(paths["raw"]),
                   "expectedDatasetServerBuildId": fixed.EXPECTED_SERVER_BUILD,
                   "rawExtractionHeaderRewritten": False,
                   "runtimeInputEncoding": "fixed encoder after field-by-field equality of every encoded current extraction field",
                   "palsSha256": fixed.sha256_file(fixed.PALS), "breedingSha256": fixed.sha256_file(fixed.BREEDING),
                   "staticNativeEvidenceSha256": fixed.sha256_file(paths["static"]),
                   "currentProvenanceSha256": fixed.sha256_file(paths["provenance"]),
                   "runtimeGateSha256": fixed.sha256_file(paths["gate"]),
                   "runtimeAdapterSha256": fixed.sha256_file(Path(__file__)),
                   "originalRuntimeProbeSourceSha256": fixed.sha256_file(fixed.PROBE_SOURCE),
                   "generatedRuntimeProbeSourceSha256": fixed.sha256_file(paths["probe_source"]),
                   "offlineShimSourceSha256": fixed.sha256_file(fixed.OFFLINE_SHIM_SOURCE)},
        "isolation": isolation,
        "serverInitialization": {"reportedGameVersion": f"v{VERSION}", "reachedRunningState": True,
                                 "processExitCode": exit_code},
    }
    report["evidenceSha256"] = sha(fixed.canonical_bytes(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", type=Path, required=True)
    parser.add_argument("--raw-assets", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--native-static", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate-output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--collect-only", action="store_true", help="Validate/collect machine evidence without starting the game")
    args = parser.parse_args()
    gate: dict[str, Any] = {"schemaVersion": 1, "status": "collecting", "serverBuildId": BUILD,
                            "serverExecutableSha256": BINARY_SHA256, "reviewedCoreRegions": [],
                            "helperWindows": {}, "hookPrefixes": {}, "fieldOffsets": {},
                            "currentNativeFunctionInvoked": False}
    outputs_validated = False
    try:
        inputs = {args.raw_assets, args.provenance, args.native_static,
                  fixed.RAW_ASSETS, fixed.NATIVE_STATIC, fixed.PALS, fixed.BREEDING,
                  fixed.PROBE_SOURCE, fixed.OFFLINE_SHIM_SOURCE, Path(__file__),
                  args.server_root / "Pal/Binaries/Linux/PalServer-Linux-Shipping",
                  args.server_root / "Pal/Content/Paks/Pal-LinuxServer.pak"}
        validate_output_paths(args.output, args.gate_output, inputs)
        outputs_validated = True
        binary, raw, provenance, static = validate_files(args.server_root.resolve(), args.raw_assets,
                                                         args.provenance, args.native_static)
        compare = validate_current_inputs(args.raw_assets, raw)
        gate["breedingInputsSha256"] = compare["breedingInputs"]["candidateSha256"]
        gate["inputComparisonStatus"] = compare["predictedResults"]["status"]
        addresses = collect_gate(ElfImage(binary), static, gate)
        save_json(args.gate_output, gate)
        if args.collect_only:
            print(json.dumps({"status": gate["status"], "gameExecuted": False}))
            return
        isolation = require_offline_runner()
        with tempfile.TemporaryDirectory(prefix="palworld-current-native-") as temporary:
            work = Path(temporary)
            input_path = work / "runtime-input.bin"
            input_evidence = fixed.build_runtime_input(input_path)
            source = work / "current-native-runtime-probe.c"
            source.write_text(generate_probe(addresses), encoding="utf-8")
            probe, shim = work / "probe.so", work / "offline-shim.so"
            fixed.compile_shared(source, probe, "-pthread")
            fixed.compile_shared(fixed.OFFLINE_SHIM_SOURCE, shim, "-Wno-pedantic", "-ldl")
            runtime, _, exit_code = run_game(binary, args.server_root.resolve(), input_path, probe, shim, work, args.timeout)
            paths = {"raw": args.raw_assets, "static": args.native_static, "provenance": args.provenance,
                     "gate": args.gate_output, "probe_source": source}
            report = build_report(runtime, raw, input_evidence, addresses, isolation, paths, exit_code)
            save_json(args.output, report)
            print(json.dumps({"status": report["status"], "counts": report["counts"],
                              "differences": report["differences"]}))
    except Exception as error:
        if not outputs_validated:
            raise
        gate["status"] = "current-runtime-refused-or-failed"
        gate["reason"] = str(error)
        save_json(args.gate_output, gate)
        save_json(args.output, {"schemaVersion": 2, "status": "current-build-native-runtime-not-verified",
                                "target": {"serverBuildId": BUILD}, "reason": str(error)})
        raise


if __name__ == "__main__":
    main()
