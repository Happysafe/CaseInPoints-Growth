"""
Tests for pipeline.university_category — REF trajectory classification.

Runs with stdlib unittest (no pytest dependency):
    python3 -m unittest tests.test_university_category

`get_university_profile` is mocked so these tests never touch the Excel/JSON data.
"""
from __future__ import annotations

import unittest
from unittest import mock

from pipeline import university_category as uc


def _profile(f4, f3, f2, f1, uncl):
    """Build the {<PROFILE>: {...}} shape that get_university_profile returns."""
    return {uc.PROFILE: {"4star": f4, "3star": f3, "2star": f2, "1star": f1, "unclassified": uncl}}


def _patch_profiles(by_year):
    """
    Patch get_university_profile so it returns by_year[year] regardless of name.
    by_year maps {2021: profile_or_None, 2014: profile_or_None}.
    """
    def fake(_university, year=2021, profile=uc.PROFILE):
        return by_year.get(year)
    return mock.patch.object(uc, "get_university_profile", side_effect=fake)


class ClassifyUniversityTests(unittest.TestCase):
    def setUp(self):
        uc._clear_cache()

    def _classify(self, p2021, p2014):
        with _patch_profiles({2021: p2021, 2014: p2014}):
            return uc.classify_university("Test University")

    def test_leaders_at_threshold(self):
        cat, _ = self._classify(_profile(50, 30, 15, 5, 0), _profile(10, 40, 30, 20, 0))
        self.assertEqual(cat, "Leaders")

    def test_just_below_leaders_is_not_leaders(self):
        cat, _ = self._classify(_profile(49.9, 40, 10, 0.1, 0), _profile(45, 40, 10, 5, 0))
        self.assertNotEqual(cat, "Leaders")

    def test_at_risk(self):
        cat, _ = self._classify(_profile(15, 50, 20, 15, 0), _profile(12, 50, 23, 15, 0))
        self.assertEqual(cat, "At Risk")  # f21=15<35, tail=35>20

    def test_low_4star_but_low_tail_is_not_at_risk(self):
        # f21=15<35 but tail (2*+1*+uncl) <= 20, so it's not At Risk
        cat, _ = self._classify(_profile(15, 70, 12, 3, 0), _profile(14, 71, 12, 3, 0))
        self.assertNotEqual(cat, "At Risk")  # tail = 15, not > 20

    def test_improvers(self):
        # Δ4* = 22-10 = +12 >= 10; not Leaders, not At Risk (f21=22 >= 20)
        cat, m = self._classify(_profile(22, 60, 18, 0, 0), _profile(10, 60, 25, 5, 0))
        self.assertEqual(cat, "Improvers")
        self.assertAlmostEqual(m["delta_4star"], 12.0)

    def test_small_increase_is_stagnant(self):
        # Δ4* = +5 < 10
        cat, _ = self._classify(_profile(22, 60, 18, 0, 0), _profile(17, 60, 23, 0, 0))
        self.assertEqual(cat, "Stagnant")

    def test_precedence_strength_beats_momentum(self):
        # f21=55 (Leaders) AND huge jump from 10 → still Leaders
        cat, _ = self._classify(_profile(55, 30, 10, 5, 0), _profile(10, 40, 30, 20, 0))
        self.assertEqual(cat, "Leaders")

    def test_precedence_risk_beats_momentum(self):
        # f21=15<35, tail=35>20 (At Risk) AND Δ4* = +13 (>=10) → At Risk wins
        cat, _ = self._classify(_profile(15, 50, 20, 15, 0), _profile(2, 50, 33, 15, 0))
        self.assertEqual(cat, "At Risk")

    def test_missing_2014_blank_deltas_classified_from_2021(self):
        cat, m = self._classify(_profile(55, 30, 10, 5, 0), None)
        self.assertEqual(cat, "Leaders")
        self.assertIsNone(m["delta_4star"])
        self.assertIsNone(m["delta_3star_plus"])

    def test_missing_2014_skips_improvers(self):
        # f21=22 would be Improvers only with a 2014 baseline; without it → Stagnant
        cat, m = self._classify(_profile(22, 60, 18, 0, 0), None)
        self.assertEqual(cat, "Stagnant")
        self.assertIsNone(m["delta_4star"])

    def test_unmatched_2021_returns_none(self):
        cat, m = self._classify(None, None)
        self.assertIsNone(cat)
        self.assertEqual(m, {})

    def test_delta_3star_plus_computed(self):
        # (2021 4*+3*) - (2014 4*+3*) = (22+60) - (10+60) = 12
        _, m = self._classify(_profile(22, 60, 18, 0, 0), _profile(10, 60, 25, 5, 0))
        self.assertAlmostEqual(m["delta_3star_plus"], 12.0)


class CategoriseLeadsTests(unittest.TestCase):
    def setUp(self):
        uc._clear_cache()

    def test_adds_fields_in_place(self):
        leads = [{"university": "Test University", "contact_name": "Dr A"}]
        with _patch_profiles({2021: _profile(55, 30, 10, 5, 0), 2014: _profile(10, 40, 30, 20, 0)}):
            uc.categorise_leads(leads)
        self.assertEqual(leads[0]["university_category"], "Leaders")
        self.assertIn("change_in_4star", leads[0])
        self.assertIn("change_in_3star_plus", leads[0])


if __name__ == "__main__":
    unittest.main()
