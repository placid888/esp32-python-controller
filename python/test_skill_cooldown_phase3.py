import unittest
from pathlib import Path
from unittest.mock import patch
from skill_cooldown_phase3 import RobustBench,Distribution
import profile_store

class Phase3Tests(unittest.TestCase):
    def setUp(self):self.p=profile_store.active(Path(__file__).with_name('config.json'))
    def bench(self,strategy='cooldown_aware',case='long',duration=4,**kw):
        b=RobustBench(self.p,strategy,case,duration,**kw);r=b.run()
        self.assertFalse(r['errors']);self.assertEqual(r['socket_attempts'],0)
        self.assertEqual(r['residual_pending_count'],0);self.assertIsNone(r['inflight_after_stop'])
        self.assertEqual(r['adapter_tickets_after_stop'],0);return b,r
    def test_short_windows(self):
        for s in ('cooldown_aware','state_transition'):
            for width in (10,20,25):
                _,r=self.bench(s,'window',4,width_ms=width)
                self.assertEqual(r['accepted'],0);self.assertEqual(r['decision_rate'],0)
    def test_longer_windows(self):
        for s in ('cooldown_aware','state_transition'):
            for width in (60,100):
                _,r=self.bench(s,'window',4,width_ms=width,phase_ms=5)
                self.assertEqual(r['accepted'],2)
                self.assertGreaterEqual(r['window_latency_ms']['min'],40-1e-6)
    def test_boundary_window_rechecked(self):
        _,r=self.bench(case='window',duration=4,width_ms=40)
        self.assertEqual(r['accepted'],0)
    def test_jitter_cancels(self):
        _,r=self.bench(case='jitter',jitter_ms=20)
        self.assertEqual(r['accepted'],0);self.assertGreater(r['cancelled_pending_count'],0)
    def test_held_ready_repeats_vs_edges(self):
        _,b=self.bench(case='jitter',jitter_ms=100)
        _,c=self.bench('state_transition','jitter',jitter_ms=100)
        self.assertGreater(b['accepted'],c['accepted'])
    def test_early_info_recovery(self):
        _,b=self.bench(case='error',duration=4,error_ms=-200)
        _,c=self.bench('state_transition','error',4,error_ms=-200)
        self.assertGreater(b['accepted'],0);self.assertGreater(b['suppressed'],0)
        self.assertEqual(c['accepted'],0);self.assertEqual(c['suppressed'],1)
    def test_late_info_latency(self):
        _,r=self.bench(case='error',error_ms=200)
        self.assertGreaterEqual(r['latency_ms']['min'],240-1e-6)
    def test_stale_edge_stalls(self):
        _,b=self.bench(case='stale_available')
        _,c=self.bench('state_transition','stale_available')
        self.assertGreater(b['accepted'],0);self.assertEqual(c['accepted'],0)
    def test_expired_unknown(self):
        for s in ('cooldown_aware','state_transition'):
            _,r=self.bench(s,'expired_unknown');self.assertEqual(r['unknown_count'],1)
            self.assertEqual(r['accepted'],0)
    def test_strict_priority_starvation(self):
        for s in ('cooldown_aware','state_transition'):
            _,r=self.bench(s,'starvation',8)
            self.assertEqual(r['starvation']['Skill_5']['service_rate'],0)
            self.assertEqual(r['starvation']['Skill_5']['longest_wall_wait_seconds'],8)
    def test_gate_false(self):
        _,r=self.bench(case='gate_false');self.assertEqual(r['accepted'],0)
    def test_unknown(self):
        _,r=self.bench(case='unknown');self.assertEqual(r['unknown_count'],1)
    def test_acceleration_differential(self):
        for s in ('cooldown_aware','state_transition'):
            a,x=self.bench(s,duration=60,accelerate=False)
            b,y=self.bench(s,duration=60,accelerate=True)
            self.assertEqual(x['accepted'],y['accepted']);self.assertGreater(y['skipped_quiescent_polls'],0)
            for p,q in zip(a.trace,b.trace):self.assertLessEqual(abs(p['simulated_time']-q['simulated_time']),.011)
            self.assertGreaterEqual(y['latency_ms']['min'],40-1e-6)
    def test_acceleration_never_skips_active_delay(self):
        _,r=self.bench(case='jitter',jitter_ms=100,accelerate=True)
        self.assertEqual(r['skipped_quiescent_polls'],0)
    def test_bounded_histogram(self):
        d=Distribution()
        for i in range(1000):d.add(i*.01)
        self.assertEqual(d.result()['count'],1000);self.assertLess(len(d.hist),102)
    def test_stop_restart(self):
        for s in ('cooldown_aware','state_transition'):
            b,x=self.bench(s);_,y=self.bench(s)
            self.assertEqual(x['accepted'],y['accepted'])
            with self.assertRaises(RuntimeError):b.run()
    def test_no_socket_construction(self):
        with patch('socket.socket.__init__',side_effect=AssertionError('No socket')):self.bench()
if __name__=='__main__':unittest.main(verbosity=2)
