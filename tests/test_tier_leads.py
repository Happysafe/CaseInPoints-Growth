"""
Tests for pipeline.tier_leads — outreach tier from cached REF 2021 impact data,
with a university-wide fallback for leads that have no inferred UoA.

Run: python3 -m unittest tests.test_tier_leads

get_profile / get_university_profile are mocked so tests never touch the Excel/JSON data.
"""
from __future__ import annotations

import unittest
from unittest import mock

from pipeline import tier_leads as tl


def _impact(f4, f3, f2, f1, uncl=0.0):
    return {"4star": f4, "3star": f3, "2star": f2, "1star": f1, "unclassified": uncl}


class TierLookupTests(unittest.TestCase):
    def test_uoa_known_uses_get_profile(self):
        # impact mean = (4*20 + 3*60 + 2*20)/100 = 3.00 → Tier 1 (<=3.10)
        with mock.patch.object(tl, "get_profile", return_value={"impact": _impact(20, 60, 20, 0)}) as gp, \
             mock.patch.object(tl, "get_university_profile") as gup:
            tier, mean = tl.get_tier_for_lead({"university": "X", "uoa_code": "UoA 17"})
        self.assertEqual(tier, "1")
        self.assertAlmostEqual(mean, 3.00)
        gp.assert_called_once()
        gup.assert_not_called()  # UoA hit → no fallback

    def test_uoa_known_but_no_submission_falls_back_to_university(self):
        # get_profile finds the institution but not that UoA → fall back to university-wide
        with mock.patch.object(tl, "get_profile", return_value=None), \
             mock.patch.object(tl, "get_university_profile",
                               return_value={"impact": _impact(60, 40, 0, 0)}) as gup:
            tier, mean = tl.get_tier_for_lead({"university": "X", "uoa_code": "UoA 99"})
        # mean = (4*60 + 3*40)/100 = 3.60 → Tier 3
        self.assertEqual(tier, "3")
        self.assertAlmostEqual(mean, 3.60)
        gup.assert_called_once()

    def test_no_uoa_uses_university_wide(self):
        with mock.patch.object(tl, "get_profile") as gp, \
             mock.patch.object(tl, "get_university_profile",
                               return_value={"impact": _impact(30, 50, 20, 0)}) as gup:
            tier, mean = tl.get_tier_for_lead({"university": "X"})  # no uoa_code
        # mean = (4*30 + 3*50 + 2*20)/100 = 3.10 → Tier 1 (boundary, <=3.10)
        self.assertEqual(tier, "1")
        self.assertAlmostEqual(mean, 3.10)
        gp.assert_not_called()  # no UoA → skip per-UoA lookup entirely
        gup.assert_called_once()

    def test_unmatched_institution_returns_question_mark(self):
        with mock.patch.object(tl, "get_profile", return_value=None), \
             mock.patch.object(tl, "get_university_profile", return_value=None):
            tier, mean = tl.get_tier_for_lead({"university": "Nowhere", "uoa_code": "UoA 1"})
        self.assertEqual(tier, "?")
        self.assertIsNone(mean)

    def test_tier_thresholds(self):
        # 3.10 → "1", 3.55 → "2", above → "3"
        self.assertEqual(tl._assign_tier(3.10), "1")
        self.assertEqual(tl._assign_tier(3.11), "2")
        self.assertEqual(tl._assign_tier(3.55), "2")
        self.assertEqual(tl._assign_tier(3.56), "3")


class TierLeadsBatchTests(unittest.TestCase):
    def test_adds_fields_in_place(self):
        leads = [
            {"university": "X", "uoa_code": "UoA 17", "contact_name": "A"},
            {"university": "Y", "contact_name": "B"},  # no UoA → university-wide
        ]
        def fake_profile(_u, _uoa, _y=2021):
            return {"impact": _impact(70, 30, 0, 0)}  # mean 3.70 → "3"
        def fake_uni(_u, _y=2021):
            return {"impact": _impact(10, 40, 30, 20)}  # mean 2.40 → "1"
        with mock.patch.object(tl, "get_profile", side_effect=fake_profile), \
             mock.patch.object(tl, "get_university_profile", side_effect=fake_uni):
            tl.tier_leads(leads)
        self.assertEqual(leads[0]["outreach_tier"], "3")
        self.assertEqual(leads[1]["outreach_tier"], "1")
        self.assertIn("uoa_mean_score", leads[0])
        self.assertIsNotNone(leads[1]["uoa_mean_score"])


if __name__ == "__main__":
    unittest.main()
