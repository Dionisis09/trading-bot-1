import tempfile
import unittest
from pathlib import Path

from check_freqtrade_process import matching_process_exists


class CheckFreqtradeProcessTests(unittest.TestCase):
    def write_process(self, root: Path, pid: str, tokens: list[str]) -> None:
        process_dir = root / pid
        process_dir.mkdir()
        (process_dir / "cmdline").write_bytes(b"\0".join(x.encode() for x in tokens) + b"\0")

    def test_matches_exact_trade_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_process(root, "10", ["freqtrade", "trade", "--strategy", "DualTrendFuturesV2R"])
            self.assertTrue(matching_process_exists(root, "DualTrendFuturesV2R"))

    def test_rejects_wrong_strategy_or_non_trade_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_process(root, "10", ["freqtrade", "backtesting", "--strategy", "DualTrendFuturesV2R"])
            self.write_process(root, "11", ["freqtrade", "trade", "--strategy", "OtherStrategy"])
            self.assertFalse(matching_process_exists(root, "DualTrendFuturesV2R"))


if __name__ == "__main__":
    unittest.main()
