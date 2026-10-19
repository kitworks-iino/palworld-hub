"""Regression checks against false current-build compatibility claims."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import compare_current_game_evidence as compare  # noqa: E402


class CurrentGameEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "evidence/build-24181105.assets.json").read_text())
        cls.committed = json.loads((ROOT / "data/breeding.verified.json").read_text())

    def candidate(self):
        return copy.deepcopy(self.baseline)

    def test_fixed_semantics_reproduce_every_committed_logical_result(self):
        rows = compare.predicted_rows(compare.normalise(self.baseline))
        self.assertEqual(rows, compare.fixed.decode_compact(self.committed))
        self.assertEqual(len(rows), 41617)

    def test_new_build_identity_does_not_grant_current_native_verification(self):
        candidate = self.candidate()
        candidate["buildId"] = "99999999"
        candidate["pakFiles"][0]["sha256"] = "a" * 64
        result = compare.compare_assets(self.baseline, candidate)
        self.assertTrue(result["allExtractedGameDataEqual"])
        self.assertTrue(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["status"], "matched")
        self.assertEqual(result["predictedResults"]["matchingLogicalRowCount"], 41617)
        self.assertNotEqual(result["baseline"]["pakFiles"], result["candidate"]["pakFiles"])
        self.assertFalse(result["verificationScope"]["candidateNativeExecutableVerified"])
        self.assertFalse(result["verificationScope"]["promotesCandidateToNativeVerified"])
        self.assertFalse(result["verificationScope"]["inGameBreedingFarmEligibilityVerified"])

    def test_localization_and_work_drift_are_not_breeding_drift(self):
        candidate = self.candidate()
        candidate["englishNames"]["PAL_NAME_SheepBall"] = "Updated name"
        row = next(row for row in candidate["pals"] if row["rowName"] == "SheepBall")
        row["workSuitability"]["Handcraft"] += 1
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["allExtractedGameDataEqual"])
        self.assertTrue(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["status"], "matched")
        changes = result["differences"]["publicPalMetadata"]["changed"]
        self.assertEqual(changes[0]["id"], "sheepball")
        self.assertEqual(changes[0]["changedFields"], ["en", "work"])

    def test_enum_spelling_drift_is_reported_separately_from_semantic_inputs(self):
        candidate = self.candidate()
        row = candidate["combinations"][0]
        row["parentTribeA"] = compare.fixed.enum_tail(row["parentTribeA"]).lower()
        row["parentGenderA"] = "WILDCARD"
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["allExtractedGameDataEqual"])
        self.assertTrue(result["breedingInputs"]["equal"])
        self.assertEqual(result["differences"]["specialRecipes"]["differenceCount"], 1)
        self.assertEqual(result["predictedResults"]["status"], "matched")

    def test_rank_change_changes_predictions(self):
        candidate = self.candidate()
        row = next(row for row in candidate["pals"] if row["rowName"] == "SheepBall")
        row["combiRank"] -= 100
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["status"], "differ")
        self.assertGreater(result["predictedResults"]["candidateOnlyRowCount"], 0)

    def test_duplicate_priority_and_row_enumeration_ties_are_observable(self):
        candidate = self.candidate()
        flower = next(row for row in candidate["pals"] if row["rowName"] == "PlantSlime_Flower")
        flower["combiDuplicatePriority"] += 1
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertIn("plantslime_flower", {row["child"] for row in result["predictedResults"]["candidateOnlyRows"]})
        candidate = self.candidate()
        rows = candidate["pals"]
        indices = [index for index, row in enumerate(rows) if row["rowName"] in {"PlantSlime", "PlantSlime_Flower"}]
        left, right = indices
        rows[left], rows[right] = rows[right], rows[left]
        for index in indices:
            rows[index]["sourceOrder"] = index
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertIn("plantslime_flower", {row["child"] for row in result["predictedResults"]["candidateOnlyRows"]})

    def test_gender_recipe_change_is_never_hidden_by_child_set_comparison(self):
        candidate = self.candidate()
        rows = [row for row in candidate["combinations"] if {
            compare.fixed.enum_tail(row["parentTribeA"]), compare.fixed.enum_tail(row["parentTribeB"])
        } == {"CatMage", "FoxMage"}]
        self.assertEqual(len(rows), 2)
        for row in rows:
            row["parentGenderA"], row["parentGenderB"] = row["parentGenderB"], row["parentGenderA"]
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["baselineOnlyRowCount"], 2)
        self.assertEqual(result["predictedResults"]["candidateOnlyRowCount"], 2)

    def test_unknown_item_adjustment_does_not_silently_use_old_formula(self):
        candidate = self.candidate()
        candidate["breedingItemEffects"][0]["combiRankBonus"] = 2
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["status"], "not-comparable")
        self.assertNotIn("matchingLogicalRowCount", result["predictedResults"])

    def test_same_tribe_gender_recipe_preserves_both_parent_orders(self):
        candidate = self.candidate()
        row = next(row for row in candidate["combinations"]
                   if compare.fixed.enum_tail(row["parentTribeA"]) == "NightLady"
                   and compare.fixed.enum_tail(row["parentTribeB"]) == "NightLady")
        row["parentGenderA"] = "EPalGenderType::Male"
        row["parentGenderB"] = "EPalGenderType::Female"
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["breedingInputs"]["equal"])
        self.assertEqual(result["predictedResults"]["status"], "matched")

    def test_new_capture_field_is_retained_and_not_assumed_verified(self):
        candidate = self.candidate()
        for row in candidate["pals"]:
            row["isUncapturable"] = row["rowName"] == "WorldTreeDragon"
            row["maleProbability"] = 50
        result = compare.compare_assets(self.baseline, candidate)
        self.assertFalse(result["allExtractedGameDataEqual"])
        self.assertEqual(result["palFieldCoverage"]["candidateOnlyFields"], ["isUncapturable", "maleProbability"])
        self.assertEqual(result["differences"]["rawPalRows"]["differenceCount"], 753)
        self.assertFalse(result["verificationScope"]["inGameBreedingFarmEligibilityVerified"])

    def test_malformed_enumeration_and_boolean_types_are_rejected(self):
        candidate = self.candidate()
        candidate["pals"][0]["sourceOrder"] = 1
        with self.assertRaisesRegex(ValueError, "enumeration order"):
            compare.normalise(candidate)
        candidate = self.candidate()
        candidate["pals"][0]["ignoreCombi"] = "false"
        with self.assertRaisesRegex(ValueError, "Invalid ignoreCombi"):
            compare.normalise(candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
