import csv
import json
import tempfile
import unittest
from pathlib import Path

import extract_profile
import generate_orders


HEADERS = extract_profile.HEADERS


def profile(line_values=(1,), line_weights=(1,)):
    minutes = [0] * 1440
    minutes[7 * 60] = 1
    return {
        "profile": "test",
        "line_count": {"values": list(line_values), "weights": list(line_weights)},
        "quantity": {"values": [1], "weights": [1]},
        "sku_cumulative": [[0.0, 0.0], [1.0, 1.0]],
        "minute_weights": minutes,
        "abc_ratios": [0.21, 0.34, 0.45],
    }


def master(product_count=6):
    return {
        "zones": [{"zone_id": 1, "warehouse_id": 1, "facility_id": 1}],
        "stores": [{"store_id": 1, "zone_id": 1, "outbound_count": 10}],
        "racks": [{"rack_id": i, "zone_id": 1, "field": f"A{i}"}
                  for i in range(1, product_count + 1)],
        "products": [{"product_id": i, "store_id": 1, "rack_id": i}
                     for i in range(1, product_count + 1)],
    }


class OrderGeneratorTest(unittest.TestCase):
    def test_extract_cleaning_and_aggregation(self):
        rows = [
            ["C1", "O1", "1", "A", "", "1", "01/01/2023 07:00", "W1", "P1"],
            ["C1", "O1", "1", "A", "", "1", "01/01/2023 07:00", "W1", "P1"],
            ["C1", "O1", "1", "B", "9", "0", "01/01/2023 07:00", "W1", "P1"],
            ["C2", "O2", "1", "C", "9", "-1", "01/01/2023 08:00", "W1", "P1"],
            ["C3", "O3", "2", "X", "8", "2", "01/01/2023 09:00", "W2", "P2"],
            ["C3", "O3", "2", "X", "9", "3", "01/01/2023 09:00", "W2", "P2"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orders.csv"
            with open(path, "w", encoding="utf-8", newline="") as target:
                writer = csv.writer(target, delimiter=";")
                writer.writerow(HEADERS)
                writer.writerows(rows)
            result = extract_profile.extract_profile(path)
        self.assertEqual(result["stats"]["raw_rows"], 6)
        self.assertEqual(result["stats"]["valid_rows"], 3)
        self.assertEqual(result["stats"]["nonpositive_rows_removed"], 2)
        self.assertEqual(result["stats"]["duplicate_rows_removed"], 1)
        self.assertEqual(result["stats"]["orders_without_valid_lines"], 1)
        self.assertEqual(result["line_count"], {"values": [1], "weights": [2]})
        self.assertEqual(result["quantity"], {"values": [1, 5], "weights": [1, 1]})
        self.assertEqual(sum(result["minute_weights"]), 2)

    def test_capping_structure_and_determinism(self):
        source = profile((7,), (1,))
        first = generate_orders.generate(source, master(), 3, seed=42)
        second = generate_orders.generate(source, master(), 3, seed=42)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["meta"]["clipped_orders"], 3)
        self.assertEqual(first["meta"]["dropped_lines"], 3)
        self.assertEqual(first["meta"]["lines"], 18)
        self.assertEqual([len(first["meta"]["abc"][key]) for key in "ABC"], [1, 2, 3])
        self.assertTrue(all(7 * 3600 <= order["ordered_at_s"] < 7 * 3600 + 60
                            for order in first["outbound"]))
        self.assertEqual([order["order_id"] for order in first["outbound"]], [1, 2, 3])
        for order in first["outbound"]:
            self.assertEqual(len({line["product_id"] for line in order["lines"]}), 6)
            self.assertTrue(all(line["rack_id"] == f"A{line['product_id']}" for line in order["lines"]))

    def test_release_changes_only_times_and_order_ids(self):
        source = profile((1, 2), (1, 1))
        wave = generate_orders.generate(source, master(), 50, seed=7, release="wave")
        smooth = generate_orders.generate(source, master(), 50, seed=7, release="smooth")

        def contents(result):
            return sorted((order["store_id"], tuple((line["product_id"], line["rack_id"], line["qty"])
                                                     for line in order["lines"]))
                          for order in result["outbound"])

        self.assertEqual(contents(wave), contents(smooth))
        self.assertTrue(all(7 * 3600 <= order["ordered_at_s"] < 8 * 3600
                            for order in smooth["outbound"]))
        self.assertTrue(any(order["ordered_at_s"] >= 7 * 3600 + 60 for order in smooth["outbound"]))

    def test_empty_output_still_validates_master(self):
        result = generate_orders.generate(profile(), master(), 0)
        self.assertEqual(result["outbound"], [])
        self.assertEqual((result["meta"]["orders"], result["meta"]["lines"], result["meta"]["units"]), (0, 0, 0))
        broken = master()
        broken["products"][0]["rack_id"] = 999
        with self.assertRaisesRegex(ValueError, "product 참조 오류"):
            generate_orders.generate(profile(), broken, 0)

    def test_real_master_abc_counts(self):
        root = Path(__file__).parent
        source = generate_orders.load_json(root / "profiles" / "order_rules.json")
        sample = generate_orders.load_json(root / "master" / "santafactory_sample.json")
        result = generate_orders.generate(source, sample, 0)
        self.assertEqual([len(result["meta"]["abc"][key]) for key in "ABC"], [28, 45, 59])


if __name__ == "__main__":
    unittest.main()


class SliceOrdersTest(unittest.TestCase):
    def test_window_filter_and_shift(self):
        import slice_orders
        data = {"meta": {"seed": 1}, "outbound": [
            {"order_id": 1, "ordered_at_s": 6 * 3600 + 59 * 60, "lines": []},
            {"order_id": 2, "ordered_at_s": 7 * 3600, "lines": []},
            {"order_id": 3, "ordered_at_s": 8 * 3600 + 1800, "lines": []},
            {"order_id": 4, "ordered_at_s": 9 * 3600, "lines": []},
        ]}
        out = slice_orders.slice_orders(data, slice_orders.to_seconds("07:00"), slice_orders.to_seconds("09:00"))
        self.assertEqual([o["order_id"] for o in out["outbound"]], [2, 3])
        self.assertEqual([o["ordered_at_s"] for o in out["outbound"]], [0, 5400])
        self.assertEqual((out["meta"]["horizon_s"], out["meta"]["orders_in_window"], out["meta"]["orders_total"], out["meta"]["seed"]),
                         (7200, 2, 4, 1))
        with self.assertRaises(ValueError):
            slice_orders.slice_orders(data, 3600, 3600)

    def test_rescale_keeps_order_and_fills_window(self):
        import slice_orders
        data = {"meta": {}, "outbound": [{"order_id": i, "ordered_at_s": t, "lines": []}
                                         for i, t in enumerate([7 * 3600, 7 * 3600 + 1800, 15 * 3600 - 1], 1)]}
        out = slice_orders.rescale_orders(data, 13 * 3600, 18 * 3600)
        times = [o["ordered_at_s"] for o in out["outbound"]]
        self.assertEqual(times[0], 13 * 3600)                    # 첫 주문 = 창 시작
        self.assertLess(times[-1], 18 * 3600)                    # 마지막 주문 < 창 끝
        self.assertEqual(times, sorted(times))
        self.assertEqual(out["meta"]["rescaled_from_s"], [7 * 3600, 15 * 3600])
        self.assertEqual(slice_orders.rescale_orders({"outbound": []}, 0, 10)["outbound"], [])
        with self.assertRaises(ValueError):
            slice_orders.rescale_orders(data, 18 * 3600, 13 * 3600)
