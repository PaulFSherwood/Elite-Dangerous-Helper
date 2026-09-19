import unittest

from construction_rules import asteroid_location_available


class AsteroidPlacementTests(unittest.TestCase):
    def test_ring_does_not_imply_an_asteroid_slot(self):
        self.assertFalse(asteroid_location_available(
            has_environment=True,
            orbital_used=0,
            orbital_total=2,
            asteroid_used=0,
            asteroid_total=0,
        ))

    def test_asteroid_slot_also_requires_free_orbital_capacity(self):
        self.assertFalse(asteroid_location_available(
            has_environment=True,
            orbital_used=2,
            orbital_total=2,
            asteroid_used=0,
            asteroid_total=1,
        ))

    def test_both_capacities_free_is_valid(self):
        self.assertTrue(asteroid_location_available(
            has_environment=True,
            orbital_used=1,
            orbital_total=2,
            asteroid_used=0,
            asteroid_total=1,
        ))

    def test_non_ring_or_belt_environment_is_never_valid(self):
        self.assertFalse(asteroid_location_available(
            has_environment=False,
            orbital_used=0,
            orbital_total=2,
            asteroid_used=0,
            asteroid_total=1,
        ))

    def test_used_asteroid_capacity_blocks_another_base(self):
        self.assertFalse(asteroid_location_available(
            has_environment=True,
            orbital_used=0,
            orbital_total=3,
            asteroid_used=1,
            asteroid_total=1,
        ))

    def test_second_asteroid_slot_remains_available(self):
        self.assertTrue(asteroid_location_available(
            has_environment=True,
            orbital_used=1,
            orbital_total=3,
            asteroid_used=1,
            asteroid_total=2,
        ))


if __name__ == "__main__":
    unittest.main()
