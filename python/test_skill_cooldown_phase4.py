from pathlib import Path
import unittest
from unittest.mock import patch
from skill_cooldown_phase4 import State,Datum,Trust,Retry,ResearchBench
import profile_store

class Phase4Tests(unittest.TestCase):
    def setUp(self):self.p=profile_store.active(Path(__file__).with_name('config.json'))
    def run_case(self,**kw):
        b=ResearchBench(self.p,**kw);r=b.run()
        self.assertFalse(r['errors']);self.assertEqual(r['socket_attempts'],0)
        self.assertEqual(r['residual_pending_count'],0);self.assertIsNone(r['inflight_after_stop'])
        self.assertLessEqual(r['max_failure_streak'],4);return b,r
    def test_three_states(self):
        for value in State:self.assertEqual(Trust().read('A',Datum(value,0,1,0),.1),value)
    def test_missing(self):self.assertEqual(Trust().read('A',None,0),State.UNKNOWN)
    def test_expired(self):self.assertEqual(Trust().read('A',Datum(State.READY,0,.1,0),.1),State.UNKNOWN)
    def test_future(self):self.assertEqual(Trust().read('A',Datum(State.READY,1,2,1),0),State.UNKNOWN)
    def test_contradictory(self):self.assertEqual(Trust().read('A',Datum(State.READY,0,1,1,True),0),State.UNKNOWN)
    def test_version_conflict(self):
        t=Trust();t.read('A',Datum(State.READY,0,1,1),0)
        self.assertEqual(t.read('A',Datum(State.NOT_READY,0,1,1),.1),State.UNKNOWN)
    def test_reordered(self):
        t=Trust();t.read('A',Datum(State.READY,.1,1,2),.1)
        self.assertEqual(t.read('A',Datum(State.READY,0,1,1),.2),State.UNKNOWN)
    def test_nonfinite(self):self.assertEqual(Trust().read('A',Datum(State.READY,float('nan'),1,1),0),State.UNKNOWN)
    def test_all_retries_bounded(self):
        for mode in ('fixed','exponential','resync'):
            _,r=self.run_case(retry=mode,scenario='permanent_lie')
            self.assertEqual(r['suppressed'],4);self.assertEqual(r['accepted'],0)
            self.assertEqual(r['retry_count'],3)
    def test_resync_requires_new_version(self):
        r=Retry('resync');r.attempted(0,1,False)
        self.assertFalse(r.allowed(1,1));self.assertTrue(r.allowed(.01,2))
    def test_exponential_delay(self):
        r=Retry('exponential');r.attempted(0,1,False);self.assertAlmostEqual(r.until,.1)
        r.attempted(.1,2,False);self.assertAlmostEqual(r.until,.3)
    def test_fresh_ready_cannot_reset_budget(self):
        r=Retry('resync')
        for i in range(4):r.attempted(i*.1,i,False)
        self.assertFalse(r.allowed(100,9999))
    def test_success_resets_failure_streak(self):
        r=Retry('fixed');r.attempted(0,0,False);r.attempted(.2,1,True)
        self.assertEqual(r.failures,0);self.assertTrue(r.allowed(.2,1))
    def test_unknown_stops(self):
        for case in ('missing','contradictory','stale'):
            _,r=self.run_case(scenario=case)
            self.assertEqual(r['unknown_count'],1);self.assertEqual(r['accepted'],0)
    def test_fairness_without_changing_engine(self):
        _,strict=self.run_case(scenario='fairness',duration=30)
        self.assertEqual(strict['per_skill_accepted'].get('Skill_5',0),0)
        for mode in ('round_robin','aging'):
            _,r=self.run_case(scenario='fairness',fairness=mode,duration=30)
            self.assertTrue(all(r['per_skill_accepted'].get(n,0)>0 for n in ('Skill_4','Skill_5','Skill_6','Skill_7')))
    def test_restart_is_explicit_reset(self):
        _,old=self.run_case(scenario='permanent_lie');_,new=self.run_case(scenario='normal')
        self.assertEqual(old['accepted'],0);self.assertGreater(new['accepted'],0)
    def test_idle_acceleration_differential(self):
        _,a=self.run_case(scenario='long_fairness',fairness='round_robin',duration=60)
        _,b=self.run_case(scenario='long_fairness',fairness='round_robin',duration=60,accelerate=True)
        self.assertEqual(a['accepted'],b['accepted'])
    def test_acceleration_preserves_retry_wakeups(self):
        for mode in ('fixed','exponential','resync'):
            _,slow=self.run_case(retry=mode,scenario='permanent_lie')
            _,fast=self.run_case(retry=mode,scenario='permanent_lie',accelerate=True)
            self.assertEqual(fast['suppressed'],4);self.assertEqual(slow['retry_count'],fast['retry_count'])
    def test_no_socket(self):
        with patch('socket.socket.__init__',side_effect=AssertionError('No sockets')):self.run_case()
if __name__=='__main__':unittest.main(verbosity=2)
