"""Simulation only; sockets guarded by the shared benchmark process guard."""
from pathlib import Path
import unittest
from unittest.mock import patch
from skill_cooldown_adapter import StrategyBench,SyntheticGame,STRATEGIES
import profile_store

class CooldownTests(unittest.TestCase):
    def setUp(self):self.profile=profile_store.active(Path(__file__).with_name('config.json'))
    def run_case(self,strategy='cooldown_aware',scenario='single_available',duration=8):
        b=StrategyBench(self.profile,strategy,duration,scenario);r=b.run()
        self.assertFalse(r['errors']);self.assertFalse(r['socket_attempts'])
        self.assertIsNone(r['inflight_after_stop']);self.assertEqual(r['residual_pending_count'],0)
        self.assertEqual(r['total_decisions'],r['accepted_decisions']+r['suppressed_decisions'])
        return b,r
    def test_gcd_exact(self):
        g=SyntheticGame();g.accept('Skill_4',0)
        self.assertIn('gcd',g.unavailable('Skill_4',1.499));self.assertFalse(g.unavailable('Skill_4',1.5))
    def test_individual_cooldown(self):
        g=SyntheticGame();g.accept('Skill_5',0)
        self.assertIn('individual_cooldown',g.unavailable('Skill_5',5.999));self.assertFalse(g.unavailable('Skill_5',6))
    def test_resource(self):
        g=SyntheticGame();self.assertIn('resource',g.unavailable('Skill_6',0))
        self.assertFalse(g.unavailable('Skill_6',2));g.accept('Skill_6',2)
        self.assertAlmostEqual(g.resource,0);self.assertIn('resource',g.unavailable('Skill_6',3.5))
        self.assertFalse(g.unavailable('Skill_6',6))
    def test_cast_overlaps_gcd(self):
        g=SyntheticGame();g.accept('Skill_7',0)
        self.assertIn('casting',g.unavailable('Skill_4',1.5));self.assertFalse(g.unavailable('Skill_4',2))
    def test_fixed_intervals(self):
        for strategy,delay in [('fixed_40',40),('fixed_100',100),('fixed_250',250),('fixed_500',500)]:
            _,r=self.run_case(strategy)
            self.assertGreater(r['suppressed_decisions'],0)
            self.assertGreaterEqual(r['minimum_interval_ms']['Skill_4'],delay-1e-6)
    def test_cooldown_filters_before_engine(self):
        _,r=self.run_case();self.assertEqual(r['suppressed_decisions'],0)
        self.assertGreater(r['accepted_decisions'],3)
    def test_b_independent_cd_spacing(self):
        b,_=self.run_case(scenario='cooldown_completion',duration=20)
        t=[e['simulated_time'] for e in b.candidate_log if e['accepted_by_synthetic_model']]
        self.assertGreater(len(t),2);self.assertTrue(all(y-x>=6 for x,y in zip(t,t[1:])))
    def test_gcd_readiness_latency(self):
        b,r=self.run_case(scenario='gcd_becomes_available',duration=2)
        self.assertGreaterEqual(b.candidate_log[0]['simulated_time'],1.04-1e-8)
        self.assertGreaterEqual(r['earliest_available_to_decision_latency_ms']['mean'],40-1e-5)
    def test_resource_recovery(self):
        b,r=self.run_case(scenario='resource_recovery');self.assertGreater(r['accepted_decisions'],0)
        self.assertGreaterEqual(b.candidate_log[0]['simulated_time'],2.04-1e-8)
    def test_casting_blocks_candidates(self):
        b,r=self.run_case(scenario='casting')
        t=[e['simulated_time'] for e in b.candidate_log]
        self.assertGreaterEqual(t[0],1.04-1e-8);self.assertTrue(all(y-x>=2 for x,y in zip(t,t[1:])))
    def test_state_transition_stops_persistent(self):
        _,a=self.run_case('fixed_40','persistent_available')
        _,c=self.run_case('state_transition','persistent_available')
        self.assertGreater(a['total_decisions'],100);self.assertEqual(c['total_decisions'],1)
    def test_state_transition_rearms(self):
        _,r=self.run_case('state_transition','single_available')
        self.assertGreater(r['accepted_decisions'],3);self.assertEqual(r['suppressed_decisions'],0)
    def test_gate_false(self):
        for strategy in STRATEGIES:
            _,r=self.run_case(strategy,'gate_false');self.assertEqual(r['total_decisions'],0)
    def test_unknown(self):
        for strategy in STRATEGIES:
            _,r=self.run_case(strategy,'unknown');self.assertEqual(r['total_decisions'],0)
            self.assertEqual(r['unknown_count'],1);self.assertEqual(r['simulated_duration'],.02)
    def test_priority(self):
        for strategy in STRATEGIES:
            _,r=self.run_case(strategy,'multiple_priority')
            self.assertEqual(sum(v for n,v in r['per_skill_count'].items() if n!='Skill_A'),0)
    def test_two_skills_starvation_visible(self):
        _,r=self.run_case('cooldown_aware','two_available')
        self.assertEqual(r['per_skill_accepted']['Skill_B'],0);self.assertGreater(r['missed_opportunities'],0)
    def test_short_window_missed_not_claimed_success(self):
        for strategy in STRATEGIES:
            _,r=self.run_case(strategy,'short_window',duration=1)
            self.assertEqual(r['accepted_decisions'],0);self.assertEqual(r['missed_opportunities'],1)
    def test_restart_fresh_state(self):
        for strategy in STRATEGIES:
            results=[]
            for _ in range(2):
                b,r=self.run_case(strategy,'persistent_available',duration=.3);results.append(r)
                with self.assertRaises(RuntimeError):b.run()
            self.assertEqual(results[0],results[1])
    def test_never_construct_socket(self):
        with patch('socket.socket.__init__',side_effect=AssertionError('No sockets')):self.run_case()
    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):StrategyBench(self.profile,'invalid',1)

if __name__=='__main__':unittest.main(verbosity=2)
