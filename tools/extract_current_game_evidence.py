#!/usr/bin/env python3
"""Collect small, derived evidence from the public Palworld Linux server depot.

All downloaded game files, public mappings and compiled extractor files stay in
--work-dir. Only the four explicitly selected JSON outputs may be uploaded.
This command does not run the game or claim to verify breeding at runtime.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time


EXTRACTOR_REPO = "https://github.com/Awy64/palworld-atlas-data.git"
EXTRACTOR_COMMIT = "0385b3fd8bd757240d4a2c79615145122669abd5"
RAW_SOURCE_SHA256 = "79d44cd07efcf767d5be0153763333249229e798c86444f21ca48d7826423eb8"
MAPPING_COMMIT = "acdf1a6a6076f84fae3275e7c1cdd08188994da8"
MAPPING_BLOB_SHA1 = "f7e71a138a45b46246c07481ea998d7f767da4ba"
MAPPING_BYTES = 2794285
MAPPING_URL = (
    "https://raw.githubusercontent.com/PalworldModding/UsefulFiles/"
    f"{MAPPING_COMMIT}/Mappings.usmap"
)
STEAMCMD_URL = (
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
)
APP_ID = "2394010"
DEPOT_ID = "2394012"
EXE_PATH = Path("Pal/Binaries/Linux/PalServer-Linux-Shipping")


def run(args: list[str], *, cwd: Path | None = None, capture: bool = False,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    # Commands contain only paths and public source identifiers; no credentials.
    print("+ " + " ".join(str(arg) for arg in args), flush=True)
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def download(url: str, destination: Path) -> None:
    run([
        "curl", "--fail", "--location", "--retry", "5", "--retry-all-errors",
        "--proto", "=https", "--tlsv1.2", url, "--output", str(destination),
    ])


def parse_vdf(source: str) -> dict:
    """Parse the quoted key/value subset used by Steam app manifests."""
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', source)
    values = [quoted if brace == "" else brace for quoted, brace in tokens]
    index = 0

    def object_value() -> dict:
        nonlocal index
        result = {}
        while index < len(values) and values[index] != "}":
            key = values[index]
            index += 1
            if index >= len(values):
                raise ValueError("Truncated Steam manifest")
            value = values[index]
            index += 1
            if value == "{":
                value = object_value()
                if index >= len(values) or values[index] != "}":
                    raise ValueError("Unbalanced Steam manifest")
                index += 1
            result[key] = value
        return result

    return object_value()


def install_server(work: Path, expected_build: str) -> tuple[Path, dict]:
    steamcmd = work / "steamcmd"
    server = work / "palserver"
    steamcmd.mkdir(parents=True, exist_ok=True)
    server.mkdir(parents=True, exist_ok=True)
    archive = work / "steamcmd_linux.tar.gz"
    download(STEAMCMD_URL, archive)
    installer_sha256 = sha256_file(archive)
    run(["tar", "-xzf", str(archive), "-C", str(steamcmd)])
    install_command = [
        str(steamcmd / "steamcmd.sh"),
        "+@sSteamCmdForcePlatformType", "linux",
        "+force_install_dir", str(server),
        "+login", "anonymous",
        "+app_info_update", "1", "+app_info_print", APP_ID,
        "+app_update", APP_ID, "validate", "+quit",
    ]
    install_attempts = []
    for attempt in range(1, 4):
        # Warm the public app record before installation. A fresh SteamCMD can
        # otherwise fail with Missing configuration immediately after login.
        result = run(install_command, cwd=steamcmd, capture=True, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        log = work / f"steamcmd-install-attempt-{attempt}.log"
        log.write_text(output, encoding="utf-8")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        error_lines = [line[:1000] for line in lines if re.search(
            r"error|failed|missing configuration|no app info", line, re.IGNORECASE,
        )][-20:]
        missing_configuration = (
            f"failed to install app '{APP_ID}' (missing configuration)"
            in output.lower()
        )
        install_attempts.append({
            "attempt": attempt,
            "exitCode": result.returncode,
            "missingConfiguration": missing_configuration,
            "errorLines": error_lines,
            "temporaryLogSha256": sha256_file(log),
        })
        # Keep the full public diagnostic output in the temporary work area;
        # only a short tail and structured failure reasons enter CI/evidence.
        print(f"SteamCMD install attempt {attempt}: exit {result.returncode}", flush=True)
        print("\n".join(line[:1000] for line in lines[-20:]), flush=True)
        if result.returncode == 0 and not missing_configuration:
            break
        if not missing_configuration or attempt == 3:
            raise RuntimeError(
                "SteamCMD installation failed: "
                + json.dumps(install_attempts, ensure_ascii=False)
            )
        delay = attempt * 5
        print(f"Missing configuration; refreshing public app info again in {delay}s", flush=True)
        time.sleep(delay)
    manifests = sorted(work.rglob(f"appmanifest_{APP_ID}.acf"))
    matches = []
    for manifest in manifests:
        app = parse_vdf(manifest.read_text(encoding="utf-8")).get("AppState", {})
        if app.get("appid") == APP_ID and app.get("buildid") == expected_build:
            matches.append((manifest, app))
    if not matches:
        observed = []
        for manifest in manifests:
            app = parse_vdf(manifest.read_text(encoding="utf-8")).get("AppState", {})
            observed.append({"appid": app.get("appid"), "buildid": app.get("buildid")})
        raise RuntimeError(f"Expected server build {expected_build}; observed {observed}")
    binaries = sorted(server.rglob(EXE_PATH.name))
    binaries = [path for path in binaries if path.as_posix().endswith(EXE_PATH.as_posix())]
    if len(binaries) != 1:
        raise RuntimeError(f"Expected one Linux server executable; found {len(binaries)}")
    server = binaries[0].parents[3]
    manifest, app = matches[0]
    depot = app.get("InstalledDepots", {}).get(DEPOT_ID, {})
    manifest_id = depot.get("manifest")
    if not manifest_id:
        raise RuntimeError("Installed Linux depot manifest ID was not recorded")
    depot_manifests = sorted(work.rglob(f"{DEPOT_ID}_{manifest_id}.manifest"))
    provenance = {
        "serverAppId": APP_ID,
        "serverBuildId": expected_build,
        "platform": "linux",
        "branch": "public",
        "serverDepotId": DEPOT_ID,
        "serverDepotManifestId": manifest_id,
        "appManifestSha256": sha256_file(manifest),
        "depotManifestSha256": (
            sha256_file(depot_manifests[0]) if depot_manifests else None
        ),
        "steamcmdInstaller": {
            "url": STEAMCMD_URL, "sha256": installer_sha256,
            "hashStatus": "observed-after-official-https-download",
        },
        "steamcmdInstallAttempts": install_attempts,
        "source": "Valve SteamCMD anonymous app_update with manifest build check",
    }
    return server, provenance


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise RuntimeError(f"Pinned extractor patch anchor changed: {before[:80]}")
    return source.replace(before, after, 1)


def prepare_extractor(repo: Path, work: Path) -> tuple[Path, dict]:
    source = work / "extractor"
    source.mkdir()
    run(["git", "init", str(source)])
    run(["git", "remote", "add", "origin", EXTRACTOR_REPO], cwd=source)
    run(["git", "sparse-checkout", "init", "--cone"], cwd=source)
    run(["git", "sparse-checkout", "set", "src"], cwd=source)
    run([
        "git", "-c", "protocol.version=2", "fetch", "--depth=1",
        "--filter=blob:none", "origin", EXTRACTOR_COMMIT,
    ], cwd=source)
    run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=source)
    actual_commit = run(["git", "rev-parse", "HEAD"], cwd=source, capture=True).stdout.strip()
    if actual_commit != EXTRACTOR_COMMIT:
        raise RuntimeError("Extractor commit pin mismatch")
    project = source / "src/PalworldAtlas.Extractor"
    raw_path = repo / "tools/RawPalDump.cs"
    raw = raw_path.read_text(encoding="utf-8")
    if hashlib.sha256(raw.encode()).hexdigest() != RAW_SOURCE_SHA256:
        raise RuntimeError("RawPalDump.cs source hash differs from the reviewed baseline")
    # Add provenance/eligibility fields in the temporary copy only. Null means
    # the property was absent; it must not be treated as a default game value.
    raw = replace_once(
        raw,
        '                isPal = reader.Bool(false, "IsPal"),',
        '''                isPal = reader.Bool(false, "IsPal"),
                isUncapturable = row.Value.Properties.Any(property =>
                    property.Name.Text.Equals("IsUncapturable", StringComparison.OrdinalIgnoreCase))
                    ? (bool?)reader.Bool(false, "IsUncapturable") : null,
                maleProbability = row.Value.Properties.Any(property =>
                    property.Name.Text.Equals("MaleProbability", StringComparison.OrdinalIgnoreCase))
                    ? (int?)reader.Int(50, "MaleProbability") : null,''',
    )
    raw = replace_once(
        raw,
        "        var breedingItemEffectAsset = provider.LoadPackageObject<UObject>(breedingItemEffectPath);",
        '''        string? gameVersion = null;
        string? gameVersionError = null;
        string? gameConfigSha256 = null;
        const string gameVersionSource = "Pal/Config/DefaultGame.ini";
        try
        {
            var configBytes = provider.SaveAsset(gameVersionSource);
            gameConfigSha256 = Convert.ToHexString(SHA256.HashData(configBytes)).ToLowerInvariant();
            var match = System.Text.RegularExpressions.Regex.Match(
                System.Text.Encoding.UTF8.GetString(configBytes),
                @"(?m)^\\s*ProjectVersion\\s*=\\s*([^\\r\\n]+)");
            if (!match.Success) throw new InvalidDataException("ProjectVersion not present");
            gameVersion = match.Groups[1].Value.Trim();
        }
        catch (Exception error)
        {
            gameVersionError = error.GetType().Name + ": " + error.Message;
        }
        var breedingItemEffectAsset = provider.LoadPackageObject<UObject>(breedingItemEffectPath);''',
    )
    raw = replace_once(
        raw, "            buildId,\n            pakFiles,",
        "            buildId,\n            gameVersion,\n            gameVersionSource,\n"
        "            gameVersionError,\n            gameConfigSha256,\n            pakFiles,",
    )
    (project / "RawPalDump.cs").write_text(raw, encoding="utf-8")
    program_path = project / "Program.cs"
    program = program_path.read_text(encoding="utf-8")
    anchor = '        "probe" => Probe(pakDirectory, mappings, buildId, Required(options, "output")),'
    # Permit indentation variation while still requiring the exact invocation.
    matching_line = [line for line in program.splitlines() if line.strip() == anchor.strip()]
    if len(matching_line) != 1:
        raise RuntimeError("Pinned Program.cs dispatch changed")
    program = replace_once(
        program, matching_line[0],
        '        "raw-evidence" => RawPalDump.Write(pakDirectory, mappings, buildId, Required(options, "output")),\n'
        + matching_line[0],
    )
    program_path.write_text(program, encoding="utf-8")
    run(["dotnet", "build", str(project), "--configuration", "Release", "--nologo"])
    return project, {
        "repository": EXTRACTOR_REPO,
        "commit": EXTRACTOR_COMMIT,
        "license": "MIT (upstream extractor); game assets retain their own rights",
        "baselineRawPalDumpSha256": RAW_SOURCE_SHA256,
        "temporaryRawPalDumpSha256": sha256_file(project / "RawPalDump.cs"),
        "temporaryProgramSha256": sha256_file(program_path),
        "patch": "raw-evidence command, game version provenance and nullable eligibility fields",
    }


def extract_assets(project: Path, server: Path, work: Path, output: Path,
                   build: str) -> dict:
    command = [
        "dotnet", "run", "--project", str(project), "--configuration", "Release",
        "--no-build", "--", "raw-evidence", "--pak-dir",
        str(server / "Pal/Content/Paks"), "--build-id", build, "--output", str(output),
    ]
    result = run(command, check=False)
    if result.returncode == 0:
        return {"used": False, "reason": "Linux named-property extraction succeeded"}
    print("Retrying extraction with the pinned public community mapping.", flush=True)
    mapping = work / "Mappings.usmap"
    download(MAPPING_URL, mapping)
    content = mapping.read_bytes()
    blob_hash = hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()
    if len(content) != MAPPING_BYTES or blob_hash != MAPPING_BLOB_SHA1:
        raise RuntimeError("Public mapping length or pinned Git blob SHA-1 mismatch")
    run(command + ["--mappings", str(mapping)])
    return {
        "used": True, "url": MAPPING_URL, "commit": MAPPING_COMMIT,
        "gitBlobSha1": blob_hash, "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "hashStatus": "Git content hash pinned; SHA-256 observed after verification",
    }


def elf_sections(binary: mmap.mmap) -> list[dict]:
    if binary[:6] != b"\x7fELF\x02\x01":
        raise RuntimeError("Expected a little-endian ELF64 executable")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", binary)
    sh_offset, sh_size, sh_count, name_index = header[6], header[11], header[12], header[13]
    raw_sections = [
        struct.unpack_from("<IIQQQQIIQQ", binary, sh_offset + index * sh_size)
        for index in range(sh_count)
    ]
    names = raw_sections[name_index]
    names_data = binary[names[4]:names[4] + names[5]]
    sections = []
    for raw in raw_sections:
        name_end = names_data.find(b"\0", raw[0])
        name = names_data[raw[0]:name_end].decode("utf-8", errors="replace")
        sections.append({
            "name": name, "type": raw[1], "flags": raw[2],
            "virtualAddress": raw[3], "fileOffset": raw[4], "bytes": raw[5],
        })
    return sections


def offset_to_va(offset: int, sections: list[dict]) -> int | None:
    for section in sections:
        if section["type"] != 8 and section["fileOffset"] <= offset < section["fileOffset"] + section["bytes"]:
            return section["virtualAddress"] + offset - section["fileOffset"]
    return None


def va_to_offset(address: int, sections: list[dict]) -> int | None:
    for section in sections:
        if section["type"] != 8 and section["virtualAddress"] <= address < section["virtualAddress"] + section["bytes"]:
            return section["fileOffset"] + address - section["virtualAddress"]
    return None


DISASM_LINE = re.compile(r"^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$")


def instruction_mask(fragment: bytes, address: int, work: Path) -> bytes:
    """Ignore only PC-relative relocation bytes in a known baseline fragment."""
    scratch = work / "baseline-instruction-fragment.bin"
    scratch.write_bytes(fragment)
    output = run([
        "objdump", "-D", "-b", "binary", "-m", "i386:x86-64",
        "--insn-width=16", f"--adjust-vma={address}", str(scratch),
    ], capture=True).stdout
    mask = bytearray(b"\xff" * len(fragment))
    for line in output.splitlines():
        match = DISASM_LINE.match(line)
        if not match:
            continue
        start = int(match[1], 16) - address
        code = bytes.fromhex(match[2])
        assembly = match[3]
        displacement = 0
        if "(%rip)" in assembly:
            displacement = 4
        elif code[:1] in (b"\xe8", b"\xe9"):
            displacement = 4
        elif len(code) >= 2 and code[0] == 0x0F and 0x80 <= code[1] <= 0x8F:
            displacement = 4
        elif code[:1] == b"\xeb" or (code and 0x70 <= code[0] <= 0x7F):
            displacement = 1
        if displacement:
            end = start + len(code)
            mask[end - displacement:end] = b"\0" * displacement
    return bytes(mask)


def find_pattern(binary: mmap.mmap, pattern: bytes, mask: bytes,
                 start: int, end: int, limit: int = 8) -> list[int]:
    stretches = list(re.finditer(b"\xff+", mask))
    longest = max(stretches, key=lambda match: match.end() - match.start())
    anchor_offset = longest.start()
    anchor = pattern[longest.start():longest.end()]
    position = start
    results = []
    while position < end:
        found = binary.find(anchor, position, end)
        if found < 0:
            break
        candidate = found - anchor_offset
        if candidate >= start and candidate + len(pattern) <= end:
            content = binary[candidate:candidate + len(pattern)]
            if all(not required or left == right for left, right, required in zip(content, pattern, mask)):
                results.append(candidate)
                if len(results) >= limit:
                    break
        position = found + 1
    return results


def native_evidence(executable: Path, baseline: Path, work: Path,
                    target: dict) -> dict:
    reference = json.loads(baseline.read_text(encoding="utf-8"))
    notes = run(["readelf", "-n", str(executable)], capture=True, check=False)
    build_id = re.search(r"Build ID:\s*([0-9a-fA-F]+)", notes.stdout)
    symbols_result = run(
        ["nm", "-C", "--defined-only", str(executable)], capture=True, check=False,
    )
    symbols = [
        line for line in symbols_result.stdout.splitlines()
        if re.search(r"(FindChildCharacterID|FindNearestCombiRank|PalCombi|Breeding)", line)
    ][:100]
    matches = []
    candidates = {}
    with executable.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as binary:
        sections = elf_sections(binary)
        text_section = next(section for section in sections if section["name"] == ".text")
        text_start = text_section["fileOffset"]
        text_end = text_start + text_section["bytes"]
        for instruction in reference["instructionEvidence"]:
            fragment = bytes.fromhex(instruction["bytes"])
            mask = instruction_mask(fragment, int(instruction["virtualAddress"], 16), work)
            locations = find_pattern(binary, fragment, mask, text_start, text_end)
            match_result = {
                "name": instruction["name"],
                "baselineVirtualAddress": instruction["virtualAddress"],
                "baselineBytes": instruction["bytes"],
                "fixedByteMask": mask.hex(),
                "matchMethod": "instruction bytes with PC-relative displacements ignored",
                "matchLimit": 8,
                "matches": [],
            }
            for location in locations:
                address = offset_to_va(location, sections)
                actual = binary[location:location + len(fragment)]
                match_result["matches"].append({
                    "fileOffset": hex(location), "virtualAddress": hex(address),
                    "bytes": actual.hex(), "exactBytesEqual": actual == fragment,
                })
            if len(locations) == 1:
                location = locations[0]
                old_offset = int(instruction["fileOffset"], 16)
                for region in reference["verifiedRegions"]:
                    region_offset = int(region["fileOffset"], 16)
                    if region_offset <= old_offset < region_offset + region["bytes"]:
                        candidate_start = location - (old_offset - region_offset)
                        candidate_va = offset_to_va(candidate_start, sections)
                        key = (region["name"], candidate_start)
                        if candidate_va is not None:
                            candidates[key] = {
                                "name": region["name"], "fileOffset": hex(candidate_start),
                                "virtualAddress": hex(candidate_va),
                                "bytes": region["bytes"] + 64,
                                "boundaryStatus": "candidate inferred from baseline relative offset",
                            }
            matches.append(match_result)
        windows = []
        for (_, start), candidate in list(candidates.items())[:12]:
            address = int(candidate["virtualAddress"], 16)
            length = candidate["bytes"]
            output = run([
                "objdump", "-d", "-C", "--insn-width=16",
                f"--start-address={address}", f"--stop-address={address + length}",
                str(executable),
            ], capture=True).stdout
            # Include machine-code lines only; never expose local temporary paths.
            lines = [line.rstrip() for line in output.splitlines() if DISASM_LINE.match(line)]
            references = []
            for line in lines:
                if "(%rip)" not in line:
                    continue
                match = re.search(r"#\s*([0-9a-f]+)", line)
                if not match:
                    continue
                referred_va = int(match[1], 16)
                referred_offset = va_to_offset(referred_va, sections)
                if referred_offset is None:
                    continue
                data = binary[referred_offset:referred_offset + 16]
                floats = [struct.unpack_from("<f", data, pos)[0] for pos in (0, 4, 8, 12)]
                references.append({
                    "instruction": line.strip(),
                    "virtualAddress": hex(referred_va), "fileOffset": hex(referred_offset),
                    "bytes": data.hex(),
                    "float32LittleEndian": [
                        value if math.isfinite(value) else str(value) for value in floats
                    ],
                    "int32LittleEndian": list(struct.unpack("<4i", data)),
                    "interpretation": "raw referenced bytes; data type requires instruction analysis",
                })
            windows.append({
                **candidate,
                "sha256": hashlib.sha256(binary[start:start + length]).hexdigest(),
                "disassembly": lines,
                "ripRelativeData": references,
            })
        exported_sections = [
            {
                **section,
                "virtualAddress": hex(section["virtualAddress"]),
                "fileOffset": hex(section["fileOffset"]),
            }
            for section in sections
            if section["name"] in (".text", ".rodata", ".data", ".data.rel.ro", ".note.gnu.build-id")
        ]
    return {
        "schemaVersion": 1,
        "status": "current-build-native-static-evidence-collected",
        "target": target,
        "executable": {
            "relativeDepotPath": EXE_PATH.as_posix(),
            "bytes": executable.stat().st_size, "sha256": sha256_file(executable),
            "elfBuildId": build_id[1].lower() if build_id else None,
            "sections": exported_sections,
        },
        "symbolStatus": "matching symbols found" if symbols else "no matching defined symbols; executable may be stripped",
        "functionSymbols": symbols,
        "baselineEvidence": {
            "path": baseline.name, "sha256": sha256_file(baseline),
            "serverBuildId": reference["target"]["serverBuildId"],
        },
        "instructionMatches": matches,
        "candidateRegions": windows,
        "limits": {
            "gameExecutableRun": False,
            "nativeFunctionInvokedForEveryPair": False,
            "currentRuntimeResultsVerified": False,
            "candidateFunctionBoundariesVerified": False,
            "inGameHatchObservedForEveryPair": False,
            "farmAssignmentEligibilityVerified": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-build", default="25247047")
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    work = args.work_dir.resolve()
    output = args.output_dir.resolve()
    if not re.fullmatch(r"\d+", args.expected_build):
        parser.error("--expected-build must contain digits only")
    if work == output or work in output.parents or output in work.parents:
        parser.error("Temporary work and public evidence directories must be separate")
    if work == repo or repo in work.parents or work in repo.parents:
        parser.error("Downloaded game files must stay outside the repository")
    if work.exists() and any(work.iterdir()):
        parser.error("--work-dir must be empty to avoid mixing builds")
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    build = args.expected_build
    asset_path = output / f"build-{build}.assets.json"
    provenance_path = output / f"build-{build}.provenance.json"
    native_path = output / f"build-{build}.native-static.json"
    provenance = {
        "schemaVersion": 1,
        "status": "started",
        "startedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "expectedServerBuildId": build,
        "workflowCommit": __import__("os").environ.get("GITHUB_SHA"),
        "workflowRunId": __import__("os").environ.get("GITHUB_RUN_ID"),
        "extractionScriptSha256": sha256_file(Path(__file__)),
        "publicArtifactPolicy": "derived JSON only; no game binaries, raw assets, mappings or compiled files",
    }
    write_json(provenance_path, provenance)
    try:
        server, steam = install_server(work, build)
        provenance["steam"] = steam
        write_json(provenance_path, provenance)
        project, extractor = prepare_extractor(repo, work)
        provenance["extractor"] = extractor
        provenance["mapping"] = extract_assets(project, server, work, asset_path, build)
        raw = json.loads(asset_path.read_text(encoding="utf-8"))
        if str(raw.get("buildId")) != build or not raw.get("pals") or not raw.get("combinations"):
            raise RuntimeError("Extracted game evidence failed minimum completeness checks")
        provenance["gameVersion"] = raw.get("gameVersion")
        provenance["gameVersionSource"] = raw.get("gameVersionSource")
        provenance["gameVersionError"] = raw.get("gameVersionError")
        provenance["gameConfigSha256"] = raw.get("gameConfigSha256")
        provenance["assets"] = {
            "file": asset_path.name, "bytes": asset_path.stat().st_size,
            "sha256": sha256_file(asset_path),
            "palRows": len(raw["pals"]), "uniqueRows": len(raw["combinations"]),
            "breedingItemEffects": len(raw.get("breedingItemEffects", [])),
            "pakFiles": raw.get("pakFiles", []),
        }
        provenance["status"] = "current-game-assets-extracted"
        write_json(provenance_path, provenance)
        target = {
            "gameVersion": raw.get("gameVersion"),
            **{key: steam[key] for key in (
                "serverAppId", "serverBuildId", "serverDepotId",
                "serverDepotManifestId", "depotManifestSha256",
            )},
        }
        write_json(native_path, native_evidence(
            server / EXE_PATH, repo / "evidence/build-24181105.native-breeding.json",
            work, target,
        ))
        provenance["nativeStaticEvidence"] = {
            "file": native_path.name, "bytes": native_path.stat().st_size,
            "sha256": sha256_file(native_path),
        }
        provenance["status"] = "current-game-evidence-collected"
        provenance["completedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(provenance_path, provenance)
        summary = (
            f"## Current Palworld game evidence\n\n"
            f"- Dedicated server build: {build}\n"
            f"- Game version from packaged configuration: {raw.get('gameVersion')}\n"
            f"- Raw Pal rows: {len(raw['pals'])}; unique combinations: {len(raw['combinations'])}\n"
            f"- Extracted assets SHA-256: {sha256_file(asset_path)}\n"
            f"- Native static evidence SHA-256: {sha256_file(native_path)}\n"
            f"- Game executable was not run; runtime and farm eligibility remain unverified.\n"
        )
        print(summary, flush=True)
        summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as stream:
                stream.write(summary)
        return 0
    except Exception as error:
        provenance["status"] = "failed"
        provenance["error"] = f"{type(error).__name__}: {error}"
        write_json(provenance_path, provenance)
        raise


if __name__ == "__main__":
    sys.exit(main())
