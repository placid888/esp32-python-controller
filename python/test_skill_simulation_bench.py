"""All engine decisions are simulated. Guard installed before test discovery."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skill_simulation_bench import Bench,SimClock,SimStopEvent,states,main
from decision import DecisionEngine
from output_guard import install_process_output_guard
from skill_model import SKILL_PRIORITY
import profile_store

GUARD=install_process_output_guard()

class BenchTests(unittest.TestCase):
    def setUp(self):self.profile=profile_store.active(Path(__file__).with_name('config.json'))
    def run_case(self,name,fn,duration=1,**kw):
        b=Bench(self.profile,name,duration,fn,**kw);r=b.run()
        self.assertFalse(r['errors']);self.assertEqual(r['unexpected_output_count'],0)
        self.assertEqual(r['socket_attempts'],0);self.assertEqual(r['residual_pending_count'],0)
        self.assertIsNone(r['inflight_after_stop']);self.assertFalse(r['inflight_leaked'])
        self.assertEqual(r['decision_count'],r['blocked_output_count']);return b,r
    def test_all_gates_false(self):
        _,r=self.run_case('false',lambda t:states(Node_Target=False,Node_Mark=False,Node_Combat=False))
        self.assertEqual(r['decision_count'],0)
    def test_opener_retry(self):
        _,r=self.run_case('opener',lambda t:states(Node_Mark=False),duration=3)
        self.assertEqual(r['per_skill_count']['Opener_Mark'],6)
        self.assertGreaterEqual(r['minimum_interval_ms']['Opener_Mark'],500-1e-6)
    def test_opener_success_cancels(self):
        _,r=self.run_case('mark_success',lambda t:states(Node_Mark=t>=.2))
        self.assertEqual(r['per_skill_count']['Opener_Mark'],1)
        self.assertGreaterEqual(r['cancelled_pending_count'],1)
    def test_combat_gate(self):
        _,r=self.run_case('combat',lambda t:states(Node_Combat=False,Skill_4=True))
        self.assertEqual(r['decision_count'],0)
    def test_repeat(self):
        _,r=self.run_case('repeat',lambda t:states(Skill_4=True))
        self.assertGreater(r['decision_count'],20)
        self.assertGreaterEqual(r['minimum_interval_ms']['Skill_4'],40-1e-6)
        self.assertEqual(r['maximum_pending_count'],1)
    def test_no_edge_only_debounce(self):
        _,r=self.run_case('not_edge_only',lambda t:states(Skill_4=True),duration=.15)
        self.assertEqual(r['decision_count'],3)
    def test_rearm_fresh_delay(self):
        b,_=self.run_case('rearm',lambda t:states(Skill_4=t<.02 or t>=.2),duration=.3)
        self.assertTrue(b.recent);self.assertGreaterEqual(b.recent[0]['simulated_time'],.24-1e-9)
    def test_gate_pending_cancel(self):
        _,r=self.run_case('cancel',lambda t:states(Skill_4=True,Node_Target=t<.02))
        self.assertEqual(r['decision_count'],0);self.assertGreaterEqual(r['cancelled_pending_count'],1)
    def test_skill_pending_cancel(self):
        _,r=self.run_case('skill_cancel',lambda t:states(Skill_4=t<.02))
        self.assertEqual(r['decision_count'],0)
    def test_priority(self):
        _,r=self.run_case('priority',lambda t:states(Skill_4=True,Skill_5=True),enabled=('Skill_4','Skill_5'))
        self.assertGreater(r['per_skill_count']['Skill_4'],0);self.assertEqual(r['per_skill_count']['Skill_5'],0)
    def test_all_alternating(self):
        _,r=self.run_case('alternating',lambda t:states(**{n:i==int(t/.2)%len(SKILL_PRIORITY) for i,n in enumerate(SKILL_PRIORITY)}),duration=7,enabled=SKILL_PRIORITY)
        self.assertTrue(all(r['per_skill_count'][n]>0 for n in SKILL_PRIORITY))
    def test_target_unknown(self):self.check_unknown('Node_Target')
    def test_mark_unknown(self):self.check_unknown('Node_Mark')
    def test_skill_unknown(self):self.check_unknown('Skill_4')
    def check_unknown(self,node):
        b,r=self.run_case('unknown_'+node,lambda t:states(**{'Skill_4':True,node:'unknown' if t>=.02 else True}))
        self.assertEqual(r['unknown_count'],1);self.assertEqual(r['decision_count'],0)
        self.assertLess(r['simulated_duration'],.04);self.assertIsNone(b.conditions)
    def test_window_invalid(self):
        _,r=self.run_case('window',lambda t:dict(states(Skill_4=True),window_error=t>=.02))
        self.assertEqual(r['stop_reason'],'not_found');self.assertEqual(r['decision_count'],0)
    def test_stop_and_restart(self):
        counts=[]
        for i in range(3):
            b,r=self.run_case('restart'+str(i),lambda t:states(Skill_4=True),duration=.15)
            counts.append(r['decision_count'])
            with self.assertRaises(RuntimeError):b.run()
            with self.assertRaises(AssertionError):b.send({'action':'tap','key':'4'},source_node='Skill_4',schedule={})
            self.assertEqual(sum(b.counts.values()),r['decision_count'])
        self.assertEqual(counts,[3,3,3])
    def test_simulated_wait(self):
        c=SimClock();s=SimStopEvent(c,1);s.wait(.04);self.assertAlmostEqual(c(),.04)
        s.wait(2);self.assertEqual(c(),1);self.assertTrue(s.is_set())
        with self.assertRaises(ValueError):c.advance(-1)
    def test_fixed_deadline_semantics(self):
        c=SimClock();b=DecisionEngine(clock=c);nodes=copy.deepcopy(self.profile['nodes'])
        for n in nodes:nodes[n]['enabled']=n in ('Node_Target','Node_Combat','Skill_4')
        nodes['Skill_4'].update(min_delay=40,max_delay=40)
        conditions=states(Skill_4=True);b.observe(conditions,nodes,'manual_first_hit')
        c.advance(.039);self.assertFalse(b.poll());c.advance(.001);self.assertEqual(len(b.poll()),1)
        self.assertFalse(b.poll());b.observe(conditions,nodes,'manual_first_hit');self.assertFalse(b.pending)
        b.complete_dispatch('Skill_4');self.assertEqual(len(b.pending),1)
    def test_random_delay_reproducible(self):
        results=[]
        for _ in range(2):
            _,r=self.run_case('rng',lambda t:states(Skill_4=True),min_delay=25,max_delay=60)
            results.append(r)
        self.assertEqual(results[0],results[1]);self.assertGreaterEqual(results[0]['minimum_interval_ms']['Skill_4'],25-1e-6)
    def test_profile_deepcopy(self):
        original=copy.deepcopy(self.profile);Bench(self.profile,'copy',1,lambda t:states())
        self.assertEqual(self.profile,original)
    def test_no_transport_or_vision(self):
        with patch('socket.socket.__init__',side_effect=AssertionError('socket construction forbidden')):
            _,r=self.run_case('no_sockets',lambda t:states(Skill_4=True))
        self.assertGreater(r['blocked_output_count'],0)
    def test_long_durations(self):
        for duration in (30,300,1800):
            _,r=self.run_case('long_'+str(duration),lambda t:states(Skill_4=True),duration=duration)
            self.assertEqual(r['simulated_duration'],duration)
            self.assertGreater(r['decision_count'],duration*20)
            self.assertGreaterEqual(r['minimum_interval_ms']['Skill_4'],40-1e-6)
            self.assertLessEqual(r['maximum_interval_ms']['Skill_4'],40+1e-4)
    def test_clock_repeat_same_results(self):
        _,a=self.run_case('same',lambda t:states(Skill_4=True));_,b=self.run_case('same',lambda t:states(Skill_4=True))
        self.assertEqual(a,b)

if __name__=='__main__':unittest.main(verbosity=2)
