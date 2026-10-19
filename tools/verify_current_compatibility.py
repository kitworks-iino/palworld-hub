#!/usr/bin/env python3
"""Gate publication on reproducible current-build inputs and native evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import compare_current_game_evidence as comparison

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest_path = ROOT / "data/current-compatibility.json"
    manifest = read_json(manifest_path)
    baseline = read_json(ROOT / "data/verification.json")
    require(manifest["schemaVersion"] == 1, "Current compatibility schema changed")
    require(manifest["baselineDatasetId"] == baseline["datasetId"], "Baseline dataset mismatch")
    require(manifest["status"] == "current-build-native-runtime-matched", "Current native verification is incomplete")
    require(manifest["compatibleServerBuildId"] == "25247047", "Unsupported current server build")
    require(manifest["compatibleGameVersion"] == "v1.0.5.102999", "Unsupported game version")
    require(f'const EXPECTED_COMPATIBILITY_SHA256="{digest(manifest_path)}";'
            in (ROOT / "data.js").read_text(encoding="utf-8"),
            "The application is not pinned to this compatibility manifest")

    documents = {}
    for role, item in manifest["evidence"].items():
        path = (ROOT / item["path"]).resolve()
        require(path.is_relative_to(ROOT) and path.is_file(), f"Invalid evidence path: {role}")
        require(digest(path) == item["sha256"], f"Evidence SHA-256 mismatch: {role}")
        documents[role] = read_json(path)
    raw = documents["currentAssets"]
    provenance = documents["extractionProvenance"]
    native = documents["nativeStatic"]
    runtime = documents["nativeRuntime"]
    runtime_provenance = documents["runtimeProvenance"]
    gate = documents["runtimeGate"]
    target = manifest["compatibleServerBuildId"]
    require(str(raw["buildId"]) == target and provenance["steam"]["serverBuildId"] == target,
            "Extraction target does not match the release")
    require("v" + raw["gameVersion"].removeprefix("v") == manifest["compatibleGameVersion"],
            "Packaged game version does not match the release")
    require(provenance["assets"]["sha256"] == manifest["evidence"]["currentAssets"]["sha256"],
            "Extraction provenance does not identify the current raw inputs")
    require(native["target"]["serverBuildId"] == target, "Static native target mismatch")
    require(runtime["target"]["serverBuildId"] == target, "Runtime native target mismatch")
    require(runtime["schemaVersion"] == 2 and runtime["status"] == manifest["status"],
            "The runtime report is not a successful current-build verification")
    require(runtime["target"]["gameVersion"] == manifest["compatibleGameVersion"],
            "Runtime game version mismatch")
    require(runtime["target"]["serverExecutableSha256"] == native["executable"]["sha256"],
            "Static and runtime executable hashes differ")
    require(runtime["target"]["serverPakSha256"] == raw["pakFiles"][0]["sha256"],
            "Runtime and extracted PAK hashes differ")
    require(runtime["target"]["serverDepotManifestId"] == provenance["steam"]["serverDepotManifestId"],
            "Runtime and extracted depot manifests differ")
    require(runtime["counts"]["nativeInvocations"] == 166_464, "Native call coverage is incomplete")
    require(runtime["counts"]["unorderedParentPairs"] == 41_616, "Native pair coverage is incomplete")
    require(runtime["counts"]["logicalResultRows"] == 41_617, "Native gender coverage is incomplete")
    require(runtime["counts"]["matchingLogicalResultRows"] == 41_617, "Native matching row coverage is incomplete")
    difference_names = {"runtimeRowMetadata", "runtimeUniqueRows", "runtimeLogicalResults", "runtimeCalls",
                        "parentOrder", "hiddenGender", "sameSpecies", "specialCombination",
                        "normalSelection"}
    require(set(runtime["differences"]) == difference_names
            and all(type(value) is int and value == 0 for value in runtime["differences"].values()),
            "Current native results contain differences")
    require(runtime["invocation"]["selectionOrRecipeLogicStubbed"] is False
            and runtime["invocation"]["internetEgressBlocked"] is True,
            "Runtime invocation scope changed")
    expected_scope = {"currentNativeExecutableInvoked": True, "extractedTableRowsInjected": True,
                      "livePakDataTablesReadByProbe": False, "baseChildSpeciesIdsVerified": True,
                      "farmAssignmentEligibilityVerified": False, "inGameHatchesObserved": False,
                      "nativeRoundingModeNearestEvenChecked": True, "syntheticFNamesAndTribeIds": True,
                      "bossAlphaPostProcessingVerified": False}
    require(runtime["verificationScope"] == expected_scope, "Native verification scope changed")
    require(manifest["verificationScope"] == expected_scope
            and manifest["verifiedAtUtc"] == runtime["verifiedAtUtc"]
            and manifest["nativeRuntimeComparison"]["canonicalEvidenceSha256"] == runtime["evidenceSha256"]
            and manifest["nativeRuntimeComparison"]["nativeInvocationCount"] == 166_464
            and manifest["nativeRuntimeComparison"]["matchingLogicalRowCount"] == 41_617
            and manifest["nativeRuntimeComparison"]["differences"] == runtime["differences"],
            "Published native verification details differ from the runtime report")
    require(runtime["bossAlphaPostProcessing"]["modeled"] is False
            and runtime["bossAlphaPostProcessing"]["nativeFunctionInvoked"] is False
            and runtime["bossAlphaPostProcessing"]["status"] == "not-verified",
            "Unmodeled alpha/boss postprocessing must remain outside the verified scope")
    require(runtime["serverInitialization"]["reachedRunningState"] is True
            and runtime["serverInitialization"]["reportedGameVersion"] == manifest["compatibleGameVersion"],
            "Current game initialization was not observed")
    isolation = runtime["isolation"]
    require(isolation["githubActions"] is True and isolation["separateNetworkNamespace"] is True
            and set(isolation["networkInterfaces"]) <= {"lo"}
            and isolation["networkNamespace"] != isolation["initialNetworkNamespace"],
            "Runtime network isolation was not established")
    report_digest = runtime["evidenceSha256"]
    report_body = {key: value for key, value in runtime.items() if key != "evidenceSha256"}
    require(hashlib.sha256(json.dumps(report_body, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest() == report_digest,
            "Runtime canonical evidence digest changed")
    require(gate["status"] == "current-runtime-machine-layout-matched"
            and gate["serverBuildId"] == target
            and gate["serverExecutableSha256"] == native["executable"]["sha256"],
            "Runtime machine-code review gate is incomplete")
    require(gate["baseChildScope"]["bossAlphaPostProcessingInvoked"] is False
            and gate["baseChildScope"]["reviewedFunctionDirectCallsExcludeBoss"] is True,
            "The base-child path was not isolated from unmodeled postprocessing")
    required_helpers = {"PARENT_TRIBE", "GET_TRIBE", "UNIQUE_MEMBERSHIP"}
    require(set(gate["reviewedHelperBodies"]) == required_helpers
            and all(item["fieldReadsAndAllReachableBranchesReviewed"] is True
                    for item in gate["reviewedHelperBodies"].values()),
            "Runtime helper review is incomplete")
    helper_review = documents["helperReview"]
    require(helper_review["source"]["sha256"] == manifest["evidence"]["helperCollection"]["sha256"]
            and helper_review["uniqueMembership"]["approvedForCurrentBaseChildInputModel"] is True
            and helper_review["bossVariant"]["approvedForCurrentInjectedModel"] is False
            and helper_review["baseChildIsolationFromBossFields"]["bossVariantIsCalledByTheseBodies"] is False,
            "Helper review and the native verification scope differ")
    inputs = runtime["inputs"]
    input_roles = {"rawAssetsSha256": "currentAssets", "staticNativeEvidenceSha256": "nativeStatic",
                   "currentProvenanceSha256": "runtimeProvenance", "runtimeGateSha256": "runtimeGate"}
    for field, role in input_roles.items():
        require(inputs[field] == manifest["evidence"][role]["sha256"], f"Runtime input mismatch: {field}")
    require(inputs["expectedDatasetServerBuildId"] == baseline["targetServerBuildId"]
            and inputs["rawExtractionHeaderRewritten"] is False
            and inputs["palsSha256"] == baseline["palDataSha256"]
            and inputs["breedingSha256"] == baseline["breedingDataSha256"],
            "Runtime baseline provenance changed")
    for field, relative in {"runtimeAdapterSha256": "tools/verify_current_native_runtime.py",
                            "originalRuntimeProbeSourceSha256": "tools/native_breeding_runtime_probe.c",
                            "offlineShimSourceSha256": "tools/fixed_server_nonroot_shim.c"}.items():
        require(inputs[field] == digest(ROOT / relative), f"Runtime source drift: {field}")
    require(runtime_provenance["steam"]["serverBuildId"] == target
            and runtime_provenance["assets"]["sha256"] == inputs["rawAssetsSha256"]
            and runtime_provenance["nativeStaticEvidence"]["sha256"] == inputs["staticNativeEvidenceSha256"]
            and runtime_provenance["extractionScriptSha256"] == digest(ROOT / "tools/extract_current_game_evidence.py"),
            "Runtime extraction provenance differs")

    original = ROOT / "evidence/build-24181105.assets.json"
    require(digest(original) == baseline["rawAssetExtractionSha256"], "Fixed raw inputs changed")
    report = comparison.compare_assets(read_json(original), raw)
    require(report["breedingInputs"]["equal"], "Current breeding inputs differ from the fixed table")
    require(report["roster"]["sameIdSet"] and report["roster"]["sameDisplayOrder"], "Current roster changed")
    predictions = report["predictedResults"]
    require(predictions["status"] == "matched" and predictions["matchingLogicalRowCount"] == 41_617,
            "Current inputs do not reproduce every committed offspring row")
    for name in ("baselineOnlyRowCount", "candidateOnlyRowCount"):
        require(predictions[name] == 0, f"Offspring differences: {name}")
    require(manifest["breedingInputComparison"]["matchingLogicalRowCount"] == 41_617
            and manifest["breedingInputComparison"]["mismatchCount"] == 0
            and manifest["breedingInputComparison"]["equal"] is True,
            "Published input comparison counts differ")
    require(manifest["breedingInputComparison"]["semanticSha256"] == report["breedingInputs"]["candidateSha256"],
            "Published input digest differs")

    metadata = report["differences"]["publicPalMetadata"]
    require(not metadata["added"] and not metadata["removed"], "Public metadata roster changed")
    actual_overrides = {}
    for change in metadata["changed"]:
        require(change["changedFields"] == ["en"], "Unreviewed public metadata changed")
        actual_overrides[change["id"]] = {"en": change["candidate"]["en"]}
    require(manifest["displayOverrides"] == actual_overrides, "Name corrections differ from the current game")
    require(manifest["gameplay"]["excludedParentIds"] == ["kingwhale"], "Farm eligibility policy changed")
    released = set(read_json(ROOT / "data/breeding.verified.json")["palOrder"])
    for row in raw["pals"]:
        if row["rowName"].lower() in released:
            require(row["isUncapturable"] is False, "Uncapturable Pal in released roster")
            require(isinstance(row["maleProbability"], int) and 0 < row["maleProbability"] < 100,
                    "Parent gender eligibility requires a new policy")
    parent_count = len(released) - len(manifest["gameplay"]["excludedParentIds"])
    require(manifest["releasedPalCount"] == len(released) == 288
            and manifest["gameplay"]["availableParentCount"] == parent_count == 287,
            "Published Pal and parent counts differ")
    require(manifest["gameplay"]["availablePairCount"] == parent_count * (parent_count + 1) // 2 == 41_328,
            "Playable pair count changed")
    print("Current Build 25247047: game inputs, 166,464 native calls, display corrections and 41,328 playable pairs verified.")


if __name__ == "__main__":
    main()
