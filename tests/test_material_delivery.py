import unittest

try:
    import PyQt6  # noqa: F401
except ModuleNotFoundError:
    PyQt6 = None

if PyQt6 is not None:
    from construction_ui import MaterialData
else:
    MaterialData = None


@unittest.skipIf(MaterialData is None, "PyQt6 is not installed in this test environment")
class MaterialDeliverySemanticsTests(unittest.TestCase):
    def test_owned_stock_does_not_make_depot_delivery_complete(self):
        row = MaterialData(
            commodity="Polymers", required=672, delivered=495, ship=0, carrier=177
        )
        self.assertEqual(row.still_needed, 177)
        self.assertEqual(row.delivery_remaining, 177)
        self.assertEqual(row.on_hand_for_build, 177)
        self.assertEqual(row.acquisition_needed, 0)

    def test_extra_stock_is_capped_to_current_build_shortfall(self):
        row = MaterialData(
            commodity="Polymers", required=672, delivered=495, ship=20, carrier=300
        )
        self.assertEqual(row.delivery_remaining, 177)
        self.assertEqual(row.on_hand_for_build, 177)
        self.assertEqual(row.acquisition_needed, 0)

    def test_only_unowned_part_is_acquisition_shortage(self):
        row = MaterialData(
            commodity="Polymers", required=672, delivered=495, ship=20, carrier=100
        )
        self.assertEqual(row.delivery_remaining, 177)
        self.assertEqual(row.on_hand_for_build, 120)
        self.assertEqual(row.acquisition_needed, 57)

    def test_completed_delivery_stays_complete_with_surplus_stock(self):
        row = MaterialData(
            commodity="Polymers", required=672, delivered=672, ship=50, carrier=300
        )
        self.assertEqual(row.still_needed, 0)
        self.assertEqual(row.on_hand_for_build, 0)
        self.assertEqual(row.acquisition_needed, 0)


if __name__ == "__main__":
    unittest.main()
