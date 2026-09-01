import unittest

from construction_rules import ColonisationCatalog, FacilityPrerequisite


class ConstructionPrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ColonisationCatalog()
        cls.extraction_settlement = FacilityPrerequisite(
            facility_type="Settlement",
            economy="Extraction",
        )

    def test_aerecura_has_verified_point_cost_and_reward(self):
        aerecura = self.catalog.facility("settlement_large_mining_aerecura")
        self.assertIsNotNone(aerecura)
        assert aerecura is not None
        self.assertEqual(aerecura.requires_tier_2, 1)
        self.assertEqual(aerecura.provides_tier_3, 2)
        self.assertTrue(
            self.catalog.facility_matches_prerequisite(
                aerecura,
                self.extraction_settlement,
            )
        )

    def test_tartarus_requires_extraction_settlement_by_type_and_economy(self):
        tartarus = self.catalog.facility("extraction_hub_tartarus")
        self.assertIsNotNone(tartarus)
        assert tartarus is not None
        self.assertEqual(len(tartarus.prerequisites), 1)
        prerequisite = tartarus.prerequisites[0]
        self.assertEqual(prerequisite.facility_type, "Settlement")
        self.assertEqual(prerequisite.economy, "Extraction")

    def test_large_mining_settlement_text_satisfies_generic_requirement(self):
        self.assertTrue(
            self.catalog.text_satisfies_prerequisite(
                "Large Mining Settlement / Aerecura",
                self.extraction_settlement,
            )
        )

    def test_generic_extraction_settlement_text_does_not_need_exact_name(self):
        self.assertTrue(
            self.catalog.text_satisfies_prerequisite(
                "Large Extraction Settlement / Some Other Layout",
                self.extraction_settlement,
            )
        )
        self.assertFalse(
            self.catalog.text_satisfies_prerequisite(
                "Large Industrial Settlement / Some Other Layout",
                self.extraction_settlement,
            )
        )


    def test_ourea_is_free_extraction_settlement_that_awards_one_t2(self):
        ourea = self.catalog.facility("settlement_small_mining_ourea")
        self.assertIsNotNone(ourea)
        assert ourea is not None
        self.assertEqual(ourea.requires_tier_2, 0)
        self.assertEqual(ourea.provides_tier_2, 1)
        self.assertEqual(ourea.provides_tier_3, 0)
        self.assertTrue(
            self.catalog.facility_matches_prerequisite(
                ourea,
                self.extraction_settlement,
            )
        )

    def test_best_buildable_prerequisite_uses_ourea_when_no_t2_exists(self):
        candidate = self.catalog.best_prerequisite_candidate(
            self.extraction_settlement,
            available_tier_2=0,
            available_tier_3=0,
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.id, "settlement_small_mining_ourea")

    def test_best_buildable_prerequisite_prefers_aerecura_with_one_t2(self):
        candidate = self.catalog.best_prerequisite_candidate(
            self.extraction_settlement,
            available_tier_2=1,
            available_tier_3=0,
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.id, "settlement_large_mining_aerecura")


if __name__ == "__main__":
    unittest.main()


class ComprehensiveFacilityRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ColonisationCatalog()

    def _find(self, name, category=None):
        matches = [f for f in self.catalog.facilities.values() if f.name == name]
        if category is not None:
            matches = [f for f in matches if f.category == category]
        self.assertTrue(matches, f"missing {name} / {category}")
        return matches[0]

    def test_catalog_contains_full_current_variant_set(self):
        # 100+ exact selectable layouts from the current v3.4.1 community list.
        self.assertGreaterEqual(len(self.catalog.facilities), 110)

    def test_user_observed_aerecura_net_points_are_zero_t2_two_t3_after_hephaestus(self):
        hephaestus = self.catalog.facility("planetary_outpost_hephaestus")
        aerecura = self.catalog.facility("settlement_large_mining_aerecura")
        assert hephaestus and aerecura
        t2 = hephaestus.provides_tier_2
        t3 = hephaestus.provides_tier_3
        t2 -= aerecura.requires_tier_2
        t3 -= aerecura.requires_tier_3
        t2 += aerecura.provides_tier_2
        t3 += aerecura.provides_tier_3
        self.assertEqual((t2, t3), (0, 2))

    def test_tourism_settlement_requires_satellite(self):
        aergia = self._find("Aergia")
        self.assertEqual(len(aergia.prerequisites), 1)
        self.assertEqual(aergia.prerequisites[0].facility_type, "Installation")
        self.assertEqual(aergia.prerequisites[0].category, "Satellite")

    def test_military_dependency_chain(self):
        vacuna = self._find("Vacuna")
        alala = self._find("Alala")
        self.assertEqual(vacuna.prerequisites[0].facility_type, "Settlement")
        self.assertEqual(vacuna.prerequisites[0].economy, "Military")
        self.assertEqual(alala.prerequisites[0].facility_type, "Installation")
        self.assertEqual(alala.prerequisites[0].category, "Military")

    def test_industrial_hub_requires_orbital_mining_outpost(self):
        molae = self._find("Molae")
        self.assertEqual(molae.prerequisites[0].facility_type, "Installation")
        self.assertEqual(molae.prerequisites[0].category, "Mining Outpost")

    def test_exploration_and_outpost_hub_dependencies(self):
        exploration = self._find("Tellus", "Exploration")
        outpost = self._find("Io")
        self.assertEqual(exploration.prerequisites[0].category, "Communication Station")
        self.assertEqual(outpost.prerequisites[0].category, "Space Farm")

    def test_security_research_and_tourist_installation_dependencies(self):
        security = self._find("Dicaeosyne")
        research = self._find("Astraeus")
        tourist = self._find("Hedone")
        self.assertEqual(security.prerequisites[0].category, "Relay Station")
        self.assertEqual(research.prerequisites[0].economy, "Research Bio")
        self.assertEqual(tourist.prerequisites[0].economy, "Tourism")

    def test_port_cost_curves(self):
        coriolis = self._find("No Truss", "Coriolis")
        zeus = self.catalog.facility("tier3_port_zeus")
        assert zeus
        self.assertEqual(self.catalog.point_cost(coriolis, previous_t2_ports=0), (3, 0))
        self.assertEqual(self.catalog.point_cost(coriolis, previous_t2_ports=1), (5, 0))
        self.assertEqual(self.catalog.point_cost(zeus, previous_t3_ports=0), (0, 6))
        self.assertEqual(self.catalog.point_cost(zeus, previous_t3_ports=1), (0, 12))

    def test_current_user_sequence_ends_at_zero_t2_three_t3(self):
        hephaestus = self.catalog.facility("planetary_outpost_hephaestus")
        aerecura = self.catalog.facility("settlement_large_mining_aerecura")
        euthenia = self.catalog.facility("installation_mining_outpost_euthenia")
        silenus = self.catalog.facility("hub_refinery_silenus")
        assert hephaestus and aerecura and euthenia and silenus
        t2 = t3 = 0
        for facility in (hephaestus, aerecura, euthenia, silenus):
            cost_t2, cost_t3 = self.catalog.point_cost(facility)
            t2 -= cost_t2
            t3 -= cost_t3
            t2 += facility.provides_tier_2
            t3 += facility.provides_tier_3
        self.assertEqual((t2, t3), (0, 3))

    def test_molae_is_blocked_at_zero_t2_three_t3(self):
        molae = self.catalog.facility("hub_industrial_molae")
        ourea = self.catalog.facility("settlement_small_mining_ourea")
        assert molae and ourea
        self.assertEqual(self.catalog.point_shortfall(molae, 0, 3), (1, 0))
        self.assertEqual(self.catalog.point_shortfall(ourea, 0, 3), (0, 0))


class WholeSystemGoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ColonisationCatalog()

    def test_primary_secondary_merge_includes_orbital_network_support(self):
        steps = self.catalog.combined_goal_steps(
            "Expansion Materials Hub",
            "Tritium Availability",
        )
        ids = [facility.id for facility, _reason in steps]
        self.assertIn("installation_mining_outpost_euthenia", ids)
        self.assertIn("hub_refinery_silenus", ids)
        self.assertLess(
            ids.index("installation_mining_outpost_euthenia"),
            ids.index("extraction_hub_tartarus"),
        )

    def test_cosmetic_layout_variants_share_functional_signature(self):
        aerecura = self.catalog.facility("settlement_large_mining_aerecura")
        erebus = self.catalog.facility("settlement_large_extraction_settlement_erebus")
        hephaestus = self.catalog.facility("planetary_outpost_hephaestus")
        opis = self.catalog.facility("planetary_outpost_opis")
        assert aerecura and erebus and hephaestus and opis
        self.assertEqual(
            self.catalog.functional_signature(aerecura),
            self.catalog.functional_signature(erebus),
        )
        self.assertEqual(
            self.catalog.functional_signature(hephaestus),
            self.catalog.functional_signature(opis),
        )

    def test_port_and_supporting_roles_match_update3_topology_classes(self):
        vulcan = self.catalog.facility("outpost_industrial_outpost_vulcan")
        euthenia = self.catalog.facility("installation_mining_outpost_euthenia")
        tartarus = self.catalog.facility("extraction_hub_tartarus")
        assert vulcan and euthenia and tartarus
        self.assertTrue(self.catalog.is_port(vulcan))
        self.assertFalse(self.catalog.is_supporting_facility(vulcan))
        self.assertTrue(self.catalog.is_supporting_facility(euthenia))
        self.assertTrue(self.catalog.is_supporting_facility(tartarus))

    def test_goal_economy_weights_use_both_dropdowns(self):
        weights = self.catalog.goal_economy_weights(
            "Expansion Materials Hub",
            "Tritium Availability",
        )
        self.assertGreater(weights.get("extraction", 0), 0)
        self.assertGreater(weights.get("industrial", 0), 0)
        self.assertGreater(weights.get("refinery", 0), 0)

class GoalCompletionAndBuildoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ColonisationCatalog()

    def test_goal_progress_counts_equivalent_layouts_and_multiplicity(self):
        # Industrial Hub asks for two equivalent Industrial Planetary Outposts.
        ponos = self.catalog.facility("planetary_outpost_ponos")
        bia = self.catalog.facility("planetary_outpost_bia")
        molae = self.catalog.facility("hub_industrial_molae")
        assert ponos and bia and molae
        partial = self.catalog.goal_progress(
            "Industrial Hub",
            [ponos],
            primary_port_complete=True,
        )
        self.assertEqual(partial["status"], "In progress")
        self.assertEqual((partial["satisfied"], partial["total"]), (1, 3))

        complete = self.catalog.goal_progress(
            "Industrial Hub",
            [ponos, bia, molae],
            primary_port_complete=True,
        )
        self.assertEqual(complete["status"], "Complete")
        self.assertEqual((complete["satisfied"], complete["total"]), (3, 3))

    def test_buildout_catalog_covers_far_more_than_short_goal_recipe(self):
        signatures = set()
        for stage in self.catalog.buildout_stages:
            for facility in self.catalog.stage_facilities(stage):
                signatures.add(self.catalog.functional_signature(facility))
        self.assertGreaterEqual(len(signatures), 30)
        names = {stage.get("name") for stage in self.catalog.buildout_stages}
        self.assertIn("Industrial & Commodity Network", names)
        self.assertIn("Security & Military Network", names)
        self.assertIn("Science & Research Network", names)

    def test_nearly_complete_goal_aligned_stage_ranks_high(self):
        industrial_stage = next(
            stage for stage in self.catalog.buildout_stages
            if stage.get("name") == "Industrial & Commodity Network"
        )
        refs = self.catalog.stage_facilities(industrial_stage)[:-1]
        ranked = self.catalog.ordered_buildout_stages(
            "Industrial Hub",
            "Commodity Profit",
            refs,
        )
        self.assertEqual(ranked[0]["name"], "Industrial & Commodity Network")
