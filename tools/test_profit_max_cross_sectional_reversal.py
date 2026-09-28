import sys, unittest
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'user_data/strategies'))
from ProfitMaxCrossSectionalReversal import ProfitMaxCrossReversalLong8h,ProfitMaxCrossReversalShort8h
class Tests(unittest.TestCase):
 def test_contract_and_sides(self):
  frame=pd.DataFrame({'volume':[1,1,1,1],'rank_count':[50]*4,'cross_rank':[1,2,49,50]})
  long=ProfitMaxCrossReversalLong8h.__new__(ProfitMaxCrossReversalLong8h);short=ProfitMaxCrossReversalShort8h.__new__(ProfitMaxCrossReversalShort8h)
  a=long.populate_entry_trend(frame.copy(),{});b=short.populate_entry_trend(frame.copy(),{})
  self.assertEqual(a['enter_long'].fillna(0).tolist(),[1,1,0,0]);self.assertEqual(b['enter_short'].fillna(0).tolist(),[0,0,1,1])
  self.assertEqual((long.momentum_candles,long.hold_hours,long.stoploss),(180,8,-.08))
if __name__=='__main__':unittest.main()
