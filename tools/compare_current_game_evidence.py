#!/usr/bin/env python3
"""Compare a new RawPalDump extraction with the verified fixed-build inputs.

This is an asset comparison, not a verification of a newer game executable.
The optional offspring recalculation always uses the committed fixed-build
native semantics and never promotes a candidate build to native-verified.
No source files, generated site data, or existing evidence are modified.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_verified_dataset as fixed

ROOT = Path(__file__).resolve().parents[1]
BREEDING_FIELDS = (
    "rowName", "sourceOrder", "tribe", "isBoss", "ignoreCombi",
    "combiRank", "combiDuplicatePriority",
)
SELECTION_FIELDS = (
    "rowName", "isPal", "isBoss", "isRaidBoss", "isTowerBoss", "tribe",
    "zukanIndex", "zukanIndexSuffix", "rarity", "runSpeed", "walkSpeed",
)
COMBINATION_FIELDS = (
    "sourceOrder", "rowName", "parentTribeA", "parentTribeB",
    "parentGenderA", "parentGenderB", "childCharacterId",
)
BOOL_FIELDS = ("isPal", "isBoss", "isRaidBoss", "isTowerBoss", "ignoreCombi")
INT_FIELDS = (
    "sourceOrder", "zukanIndex", "rarity", "runSpeed", "walkSpeed",
    "combiRank", "combiDuplicatePriority",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def differences(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Keep every changed value; do not turn absent fields into null values."""
    shared = sorted(before.keys() & after.keys())
    changed = []
    for key in shared:
        if before[key] == after[key]:
            continue
        old, new = before[key], after[key]
        changed.append({
            "id": key,
            "changedFields": sorted(
                field for field in old.keys() | new.keys()
                if field not in old or field not in new or old[field] != new[field]
            ) if isinstance(old, dict) and isinstance(new, dict) else [],
            "baseline": old,
            "candidate": new,
        })
    return {
        "added": [{"id": key, "value": after[key]} for key in sorted(after.keys() - before.keys())],
        "removed": [{"id": key, "value": before[key]} for key in sorted(before.keys() - after.keys())],
        "changed": changed,
        "differenceCount": len(before.keys() ^ after.keys()) + len(changed),
    }


def keyed_rows(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {str(row[key]): row for row in rows}
    require(len(result) == len(rows), f"Duplicate {key} values")
    return result


def projected_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Use the generator's ID/enum/gender rules for semantic input hashes."""
    projected = []
    for row in rows:
        item = {field: row[field] for field in fields}
        for field in ("rowName", "childCharacterId"):
            if field in item:
                item[field] = fixed.pal_id(item[field])
        for field in ("tribe", "parentTribeA", "parentTribeB"):
            if field in item:
                item[field] = fixed.pal_id(fixed.enum_tail(item[field]))
        for field in ("parentGenderA", "parentGenderB"):
            if field in item:
                item[field] = fixed.gender(item[field])
        projected.append(item)
    return projected


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    require(type(raw.get("schemaVersion")) is int and raw["schemaVersion"] == 1,
            "Expected RawPalDump schemaVersion 1")
    require(isinstance(raw.get("buildId"), str) and raw["buildId"].isdigit(), "Invalid buildId")
    for field in ("pals", "combinations", "icons", "breedingItemEffects", "pakFiles"):
        require(isinstance(raw.get(field), list), f"Missing extraction array: {field}")
    require(bool(raw["pals"]) and bool(raw["pakFiles"]), "Empty extraction")
    keyed_rows(raw["pals"], "rowName")
    keyed_rows(raw["combinations"], "rowName")
    keyed_rows(raw["breedingItemEffects"], "itemId")
    for table in ("pals", "combinations"):
        require([row["sourceOrder"] for row in raw[table]] == list(range(len(raw[table]))),
                f"{table} must retain the extractor's complete row enumeration order")
    for row in raw["pals"]:
        for field in BOOL_FIELDS:
            require(type(row.get(field)) is bool, f"Invalid {field}: {row.get('rowName')}")
        for field in INT_FIELDS:
            require(type(row.get(field)) is int, f"Invalid {field}: {row.get('rowName')}")
        require(isinstance(row.get("workSuitability"), dict), "Missing work suitability")
    for row in raw["combinations"]:
        for field in COMBINATION_FIELDS:
            require(field in row, f"Incomplete special recipe: {row.get('rowName')}")
        require(all(fixed.gender(row[field]) in {"WILDCARD", "FEMALE", "MALE"}
                    for field in ("parentGenderA", "parentGenderB")), "Unknown parent gender")
    for row in raw["breedingItemEffects"]:
        require(type(row.get("combiRankBonus")) is int, "Invalid breeding item rank bonus")

    icon_rows = [row for row in raw["icons"] if "t_dummy_icon" not in str(row["path"]).lower()]
    icon_by_id = {fixed.pal_id(row["id"]): row for row in icon_rows}
    require(len(icon_by_id) == len(icon_rows), "Duplicate non-dummy icon IDs")
    icons = set(icon_by_id)
    groups: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    excluded = {}
    for row in raw["pals"]:
        reason = fixed.exclusion_reason(row, icons)
        if reason:
            excluded[fixed.pal_id(row["rowName"])] = reason
        else:
            groups[fixed.public_form_key(row)].append(row)
    chosen = []
    for identity, rows in groups.items():
        if len(rows) == 1:
            chosen.append(rows[0])
            continue
        exact_icons = [row for row in rows if fixed.pal_id(row["rowName"]) in icons]
        require(len(exact_icons) == 1, f"Ambiguous public form: {identity}")
        chosen.append(exact_icons[0])
        for row in rows:
            if row is not exact_icons[0]:
                excluded[fixed.pal_id(row["rowName"])] = "DUPLICATE_PUBLIC_FORM_PARAMETER_ROW"
    names = {}
    for field in ("japaneseNames", "englishNames"):
        require(isinstance(raw.get(field), dict), f"Missing localization table: {field}")
        names[field] = {**raw[field], **{key.lower(): value for key, value in raw[field].items()}}
    roster = {}
    for row in chosen:
        identifier = fixed.pal_id(row["rowName"])
        require(identifier not in roster, f"Duplicate public ID: {identifier}")
        roster[identifier] = {
            "id": identifier, "sourceId": row["rowName"],
            "tribe": fixed.enum_tail(row["tribe"]),
            "no": row["zukanIndex"], "suffix": row["zukanIndexSuffix"],
            "rarity": row["rarity"], "sourceOrder": row["sourceOrder"],
            "combiRank": row["combiRank"],
            "combiDuplicatePriority": row["combiDuplicatePriority"],
            "ignoreCombi": row["ignoreCombi"],
            "jp": fixed.display_name(row, names["japaneseNames"]),
            "en": fixed.display_name(row, names["englishNames"]),
            "elements": fixed.element_list(row),
            "work": {key.lower(): int(value) for key, value in row["workSuitability"].items() if int(value) > 0},
        }
        require(roster[identifier]["jp"] and roster[identifier]["en"] and roster[identifier]["elements"],
                f"Incomplete public metadata: {identifier}")
    order = sorted(roster, key=lambda key: (
        roster[key]["no"], roster[key]["suffix"], roster[key]["sourceOrder"], key
    ))
    return {
        "raw": raw, "roster": roster, "order": order, "excluded": excluded,
        "breedingInputs": {
            "pals": projected_rows(raw["pals"], BREEDING_FIELDS),
            "combinations": projected_rows(raw["combinations"], COMBINATION_FIELDS),
            "itemEffects": [{"itemId": row["itemId"], "combiRankBonus": row["combiRankBonus"]}
                            for row in raw["breedingItemEffects"]],
            "itemEffectAssetPath": raw.get("breedingItemEffectPath"),
        },
        "selectionInputs": {
            "pals": projected_rows(raw["pals"], SELECTION_FIELDS),
            "usableIconIds": sorted(icons),
        },
    }


def predicted_rows(dataset: dict[str, Any]) -> set[tuple[str, str, str, str, str]]:
    """Apply baseline semantics to the candidate inputs, without game claims."""
    raw, roster = dataset["raw"], dataset["roster"]
    require(all(row["combiRankBonus"] == 0 for row in raw["breedingItemEffects"]),
            "Nonzero breeding-item rank bonuses require a separate native verification")
    all_children = {fixed.pal_id(row["childCharacterId"]) for row in raw["combinations"]}
    candidates = [{
        "id": fixed.pal_id(row["rowName"]), "combiRank": row["combiRank"],
        "combiDuplicatePriority": row["combiDuplicatePriority"], "sourceOrder": row["sourceOrder"],
    } for row in raw["pals"] if not row["isBoss"] and not row["ignoreCombi"]
        and fixed.pal_id(row["rowName"]) not in all_children]
    require(bool(candidates), "No normal-child candidates")
    recipes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw["combinations"]:
        recipe = {
            "parentA": fixed.pal_id(fixed.enum_tail(row["parentTribeA"])),
            "parentB": fixed.pal_id(fixed.enum_tail(row["parentTribeB"])),
            "genderA": fixed.gender(row["parentGenderA"]),
            "genderB": fixed.gender(row["parentGenderB"]),
            "child": fixed.pal_id(row["childCharacterId"]),
        }
        recipes[fixed.pair_key(recipe["parentA"], recipe["parentB"])].append(recipe)
    normal_cache: dict[int, str] = {}
    output = set()
    ordered = sorted(roster)
    for index, first_id in enumerate(ordered):
        first = roster[first_id]
        for second_id in ordered[index:]:
            second = roster[second_id]
            total = first["combiRank"] + second["combiRank"]
            if total not in normal_cache:
                normal_cache[total] = fixed.normal_child((first, second), candidates)["id"]
            pair_recipes = recipes.get(fixed.pair_key(first["tribe"], second["tribe"]), [])
            orientations = []
            for gender_a, gender_b in (("FEMALE", "MALE"), ("MALE", "FEMALE")):
                matches = {
                    row["child"] for row in pair_recipes
                    if (fixed.special_matches(row, {"id": first["tribe"].lower()}, gender_a,
                                              {"id": second["tribe"].lower()}, gender_b)
                        or fixed.special_matches(row, {"id": second["tribe"].lower()}, gender_b,
                                                 {"id": first["tribe"].lower()}, gender_a))
                }
                require(len(matches) <= 1, f"Conflicting special recipes: {first_id}|{second_id}")
                child = next(iter(matches)) if matches else normal_cache[total]
                orientations.append((gender_a, gender_b, child))
            if orientations[0][2] == orientations[1][2]:
                output.add(fixed.canonical_row(first_id, "WILDCARD", second_id, "WILDCARD", orientations[0][2]))
            else:
                for gender_a, gender_b, child in orientations:
                    output.add(fixed.canonical_row(first_id, gender_a, second_id, gender_b, child))
    return output


def compare_assets(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    before, after = normalise(baseline), normalise(candidate)
    breeding_equal = before["breedingInputs"] == after["breedingInputs"]
    selection_equal = before["selectionInputs"] == after["selectionInputs"]
    extracted_data_equal = (
        {key: value for key, value in baseline.items() if key not in {"buildId", "pakFiles"}}
        == {key: value for key, value in candidate.items() if key not in {"buildId", "pakFiles"}}
    )
    old_fields = set().union(*(row.keys() for row in baseline["pals"]))
    new_fields = set().union(*(row.keys() for row in candidate["pals"]))
    old_ids, new_ids = set(before["roster"]), set(after["roster"])
    detailed_fields = {"pals", "combinations", "breedingItemEffects", "icons", "japaneseNames", "englishNames", "pakFiles", "buildId"}
    categories = {
        "rawPalRows": differences(keyed_rows(baseline["pals"], "rowName"), keyed_rows(candidate["pals"], "rowName")),
        "specialRecipes": differences(keyed_rows(baseline["combinations"], "rowName"), keyed_rows(candidate["combinations"], "rowName")),
        "breedingItemEffects": differences(keyed_rows(baseline["breedingItemEffects"], "itemId"), keyed_rows(candidate["breedingItemEffects"], "itemId")),
        "icons": differences(keyed_rows(baseline["icons"], "id"), keyed_rows(candidate["icons"], "id")),
        "japaneseNames": differences(baseline["japaneseNames"], candidate["japaneseNames"]),
        "englishNames": differences(baseline["englishNames"], candidate["englishNames"]),
        "publicPalMetadata": differences(before["roster"], after["roster"]),
        "otherTopLevelFields": differences(
            {key: value for key, value in baseline.items() if key not in detailed_fields},
            {key: value for key, value in candidate.items() if key not in detailed_fields},
        ),
    }
    report = {
        "schemaVersion": 1,
        "status": "extracted-game-data-matched" if extracted_data_equal else "extracted-game-data-differ",
        "comparisonScope": "RawPalDump inputs and predictions under fixed-build native semantics",
        "allExtractedGameDataEqual": extracted_data_equal,
        "baseline": {"serverBuildId": baseline["buildId"], "pakFiles": baseline["pakFiles"]},
        "candidate": {"serverBuildId": candidate["buildId"], "pakFiles": candidate["pakFiles"]},
        "breedingInputs": {
            "equal": breeding_equal,
            "normalization": "generator lowercase IDs, enum tails, and wildcard/explicit gender values",
            "palFields": list(BREEDING_FIELDS), "specialRecipeFields": list(COMBINATION_FIELDS),
            "baselineSha256": fixed.stable_digest(before["breedingInputs"]),
            "candidateSha256": fixed.stable_digest(after["breedingInputs"]),
        },
        "rosterSelectionInputsEqual": selection_equal,
        "palFieldCoverage": {
            "baselineFields": sorted(old_fields), "candidateFields": sorted(new_fields),
            "candidateOnlyFields": sorted(new_fields - old_fields),
            "baselineOnlyFields": sorted(old_fields - new_fields),
        },
        "roster": {
            "baselineCount": len(old_ids), "candidateCount": len(new_ids),
            "addedIds": sorted(new_ids - old_ids), "removedIds": sorted(old_ids - new_ids),
            "sameIdSet": old_ids == new_ids, "sameDisplayOrder": before["order"] == after["order"],
            "baselineExcludedCounts": dict(sorted(Counter(before["excluded"].values()).items())),
            "candidateExcludedCounts": dict(sorted(Counter(after["excluded"].values()).items())),
        },
        "rawTopLevelChangedFields": sorted(
            field for field in baseline.keys() | candidate.keys()
            if field not in baseline or field not in candidate or baseline[field] != candidate[field]
        ),
        "differences": categories,
        "verificationScope": {
            "nativeSemanticsServerBuildId": fixed.SERVER_BUILD_ID,
            "newNativeInputFieldsDiscovered": False,
            "inputFieldScope": "fields consumed by the committed fixed-build species model only",
            "candidateNativeExecutableVerified": False,
            "candidateNativeFunctionInvoked": False,
            "inGameBreedingFarmEligibilityVerified": False,
            "inGameHatchesObserved": False,
            "promotesCandidateToNativeVerified": False,
        },
    }
    try:
        old_rows, new_rows = predicted_rows(before), predicted_rows(after)
    except ValueError as error:
        report["predictedResults"] = {"status": "not-comparable", "reason": str(error)}
    else:
        old_pairs = {fixed.pair_key(row[0], row[2]) for row in old_rows}
        new_pairs = {fixed.pair_key(row[0], row[2]) for row in new_rows}
        report["predictedResults"] = {
            "status": "matched" if old_rows == new_rows else "differ",
            "ruleSource": "committed fixed-build native semantics; current executable not evaluated",
            "baselinePairCount": len(old_pairs), "candidatePairCount": len(new_pairs),
            "baselineLogicalRowCount": len(old_rows), "candidateLogicalRowCount": len(new_rows),
            "matchingLogicalRowCount": len(old_rows & new_rows),
            "baselineOnlyRowCount": len(old_rows - new_rows), "candidateOnlyRowCount": len(new_rows - old_rows),
            "baselineRowsSha256": fixed.stable_digest(fixed.row_objects(old_rows)),
            "candidateRowsSha256": fixed.stable_digest(fixed.row_objects(new_rows)),
            "baselineOnlyRows": fixed.row_objects(old_rows - new_rows),
            "candidateOnlyRows": fixed.row_objects(new_rows - old_rows),
            "candidateResultsOutsideSelectedRoster": sorted({row[4] for row in new_rows} - new_ids),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="New JSON produced by the same RawPalDump extractor")
    parser.add_argument("--baseline", type=Path, default=fixed.RAW_ASSETS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.output.resolve() not in {args.baseline.resolve(), args.candidate.resolve()},
            "The report must not overwrite an extraction")
    before_bytes, after_bytes = args.baseline.read_bytes(), args.candidate.read_bytes()
    require(fixed.sha256(before_bytes) == fixed.RAW_ASSETS_SHA256, "Baseline extraction hash is not the verified fixed build")
    baseline, candidate = json.loads(before_bytes), json.loads(after_bytes)
    baseline_rows = predicted_rows(normalise(baseline))
    committed = json.loads((ROOT / "data/breeding.verified.json").read_text(encoding="utf-8"))
    require(baseline_rows == fixed.decode_compact(committed), "Comparator differs from the committed baseline offspring table")
    report = compare_assets(baseline, candidate)
    report["baseline"]["rawAssetExtractionSha256"] = fixed.sha256(before_bytes)
    report["candidate"]["rawAssetExtractionSha256"] = fixed.sha256(after_bytes)
    report["rawAssetFileHashesEqual"] = fixed.sha256(before_bytes) == fixed.sha256(after_bytes)
    report["baselineVerifiedExtractionHashMatched"] = True
    report["baselinePredictionsMatchCommittedTable"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "candidateBuildId": candidate["buildId"],
        "breedingInputsEqual": report["breedingInputs"]["equal"],
        "predictedResults": report["predictedResults"]["status"],
        "report": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
