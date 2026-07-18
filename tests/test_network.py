from pathlib import Path
import unittest

from evflex.network import configure_core, load_legacy_core, validate_feeder_tree


class NetworkTest(unittest.TestCase):
    def test_feeder_dependencies_exist(self):
        ieee = validate_feeder_tree(Path("data/feeders/ieee13"), "IEEE13Nodeckt.dss")
        lv = validate_feeder_tree(Path("data/feeders/lv906_core"), "MasterStaticAudit.dss")
        self.assertEqual({path.name for path in ieee}, {"IEEE13Nodeckt.dss", "IEEELineCodes.dss"})
        self.assertEqual(
            {path.name for path in lv},
            {"MasterStaticAudit.dss", "LineCode.txt", "Lines.txt", "Transformers.txt", "LoadsStaticAudit.txt"},
        )

    def test_legacy_core_loads(self):
        core = load_legacy_core(Path("legacy/d5_v1_2/network_core_v1_2.py"))
        self.assertTrue(hasattr(core, "Network"))
        self.assertTrue(hasattr(core, "EV"))

    def test_legacy_core_uses_verified_feeders(self):
        repo = Path.cwd()
        core = load_legacy_core(repo / "legacy/d5_v1_2/network_core_v1_2.py")
        configure_core(core, repo)
        self.assertEqual(
            core.FEEDERS["ieee13"]["master"],
            (repo / "data/feeders/ieee13/IEEE13Nodeckt.dss").resolve(),
        )
        self.assertEqual(
            core.FEEDERS["lv906"]["master"],
            (repo / "data/feeders/lv906_core/MasterStaticAudit.dss").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
