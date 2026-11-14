from pathlib import Path
import unittest
from unittest.mock import patch
from skill_cooldown_phase5 import *

class FeedbackTests(unittest.TestCase):
    def setUp(self):self.f=FeedbackSimulator();self.r=self.f.issue('A',(1,1,0),0)
    def reply(self,state,seq=1,t=.01,rid=None,version=None):
        self.f.apply(Reply(rid or self.r,version or (1,1,0),seq,state,t),t)
    def test_accepted_not_success(self):
        self.reply(Feedback.ACCEPTED);self.assertEqual(self.f.confirmed,0);self.assertEqual(self.f.active,self.r)
    def test_normal_confirmation(self):
        self.reply(Feedback.ACCEPTED);self.reply(Feedback.CONFIRMED,2,.05)
        self.assertEqual(self.f.confirmed,1);self.assertIsNone(self.f.active)
    def test_delayed_confirmation(self):
        self.reply(Feedback.ACCEPTED);self.reply(Feedback.CONFIRMED,2,.35);self.assertEqual(self.f.confirmed,1)
    def test_lost_timeout(self):
        self.reply(Feedback.ACCEPTED);self.f.advance(.5);self.assertTrue(self.f.halted);self.assertEqual(self.f.confirmed,0)
    def test_late_confirmation_not_success(self):
        self.reply(Feedback.ACCEPTED);self.f.advance(.5);self.reply(Feedback.CONFIRMED,2,.8);self.assertEqual(self.f.confirmed,0)
    def test_old_timestamp_cannot_bypass_local_timeout(self):
        self.reply(Feedback.ACCEPTED)
        self.f.apply(Reply(self.r,(1,1,0),2,Feedback.CONFIRMED,.1),.8)
        self.assertEqual(self.f.confirmed,0);self.assertTrue(self.f.halted)
    def test_duplicate_confirmation(self):
        self.reply(Feedback.ACCEPTED);self.reply(Feedback.CONFIRMED,2,.05);self.reply(Feedback.CONFIRMED,2,.8)
        self.assertEqual(self.f.confirmed,1);self.assertEqual(self.f.duplicates,1);self.assertFalse(self.f.halted)
    def test_stale_accepted_after_confirmation(self):
        self.reply(Feedback.ACCEPTED);self.reply(Feedback.CONFIRMED,2,.05);self.reply(Feedback.ACCEPTED,1,.06)
        self.assertFalse(self.f.halted);self.assertEqual(self.f.confirmed,1)
    def test_reordered_confirmation(self):
        self.reply(Feedback.CONFIRMED,2);self.assertTrue(self.f.halted);self.assertEqual(self.f.confirmed,0)
    def test_wrong_id(self):
        self.reply(Feedback.CONFIRMED,2,rid='other');self.assertEqual(self.f.confirmed,0);self.assertEqual(self.f.active,self.r)
    def test_wrong_version(self):
        self.reply(Feedback.ACCEPTED,version=(2,2,0));self.assertTrue(self.f.halted)
    def test_conflicting_terminal(self):
        self.reply(Feedback.ACCEPTED);self.reply(Feedback.CONFIRMED,2,.05);self.reply(Feedback.REJECTED,3,.06)
        self.assertEqual(self.f.confirmed,1);self.assertEqual(self.f.invalidated,1);self.assertTrue(self.f.halted)
    def test_rejected(self):self.reply(Feedback.REJECTED);self.assertIsNone(self.f.active);self.assertEqual(self.f.confirmed,0)
    def test_unknown(self):self.reply(Feedback.UNKNOWN);self.assertTrue(self.f.halted)
    def test_after_stop_ignored(self):
        self.f.stop();self.reply(Feedback.CONFIRMED,2);self.assertEqual(self.f.confirmed,0)
    def test_unique_ids_and_bounded_history(self):
        ids={self.r};self.reply(Feedback.REJECTED)
        for i in range(100):
            rid=self.f.issue('A',(1,),i+1);self.assertNotIn(rid,ids);ids.add(rid)
            self.f.apply(Reply(rid,(1,),1,Feedback.REJECTED,i+1.01),i+1.01)
            self.f.notifications.clear()
        self.assertLessEqual(len(self.f.records),64)

class TrustResetTests(unittest.TestCase):
    def packets(self,v=State.READY,t=0,seq=1):return {s:(Datum(v,t,t+.3,seq),0) for s in ('ui','audit')}
    def test_consensus(self):self.assertEqual(Consensus().read('A',self.packets(),0)[0],State.READY)
    def test_conflict(self):
        p=self.packets();p['audit']=(Datum(State.NOT_READY,0,.3,1),0)
        self.assertEqual(Consensus().read('A',p,0)[0],State.UNKNOWN)
    def test_expired(self):self.assertEqual(Consensus().read('A',self.packets(),.3)[0],State.UNKNOWN)
    def test_missing_and_recovery(self):
        c=Consensus();self.assertEqual(c.read('A',{},0)[0],State.UNKNOWN)
        self.assertEqual(c.read('A',self.packets(t=.1,seq=2),.1)[0],State.READY)
    def test_reordered_source(self):
        c=Consensus();c.read('A',self.packets(t=.1,seq=2),.1)
        self.assertEqual(c.read('A',self.packets(),.2)[0],State.UNKNOWN)
    def test_epoch_conflict(self):
        p=self.packets();p['audit']=(p['audit'][0],1)
        self.assertEqual(Consensus().read('A',p,0)[0],State.UNKNOWN)
    def budget(self,mode):
        b=SafeBudget('A',mode)
        for i in range(4):b.issue(i,0)
        return b
    def test_four_attempts(self):
        b=self.budget('manual')
        with self.assertRaises(RuntimeError):b.issue(100,99)
        b.result(Feedback.ACCEPTED,100);self.assertEqual(b.used,4)
    def test_confirmed_only_resets(self):
        b=self.budget('health');b.result(Feedback.CONFIRMED,5);self.assertEqual(b.used,0)
    def test_reset_cap_and_replay(self):
        b=self.budget('manual')
        for i in (1,2):
            p=ResetProof('manual','A',i,10*i,10*i+1,str(i),authorized=True)
            self.assertTrue(b.reset(p,10*i));self.assertFalse(b.reset(p,10*i))
            for j in range(4):b.issue(10*i+j/10,i)
        self.assertFalse(b.reset(ResetProof('manual','A',3,40,41,'3',authorized=True),40))
    def test_invalid_reset_proofs(self):
        b=self.budget('manual')
        for proof in (ResetProof('manual','A',1,5,6,'x'),ResetProof('manual','B',1,5,6,'x',authorized=True),ResetProof('manual','A',1,4,5,'x',authorized=True)):
            self.assertFalse(b.reset(proof,5))
        self.assertFalse(b.reset(ResetProof('manual','A',1,5,6,'x',authorized=True),5,pending=True))
    def test_state_cycle_not_just_ready(self):
        b=self.budget('state_cycle');p=ResetProof('state_cycle','A',1,5,6,'c')
        self.assertFalse(b.reset(p,5));self.assertTrue(b.reset(ResetProof('state_cycle','A',1,5,6,'c',stable_cycle=True),5))
    def test_health_independent_passes(self):
        b=self.budget('health');self.assertFalse(b.reset(ResetProof('health','A',1,5,6,'h',independent_health_passes=1),5))
        self.assertTrue(b.reset(ResetProof('health','A',1,5,6,'h',independent_health_passes=2),5))

class IntegrationTests(unittest.TestCase):
    def setUp(self):self.p=profile_store.active(Path(__file__).with_name('config.json'))
    def run_case(self,**kw):
        b=FeedbackBench(self.p,**kw);r=b.run();self.assertFalse(r['errors']);self.assertEqual(r['socket_attempts'],0)
        self.assertLessEqual(r['combined_pending_max'],1);self.assertEqual(r['feedback_pending_after_stop'],0)
        self.assertEqual(r['feedback_jobs_after_stop'],0);self.assertIsNone(r['inflight_after_stop']);return b,r
    def test_normal_and_duplicate(self):
        for case in ('normal','duplicate'):
            _,r=self.run_case(case=case);self.assertGreater(r['trusted_confirmations'],0)
            self.assertEqual(r['feedback_confirmed'],r['accepted'])
    def test_unknown_feedback_stops(self):
        for case in ('lost','timeout','reordered','contradictory'):
            _,r=self.run_case(case=case);self.assertEqual(r['unknown_count'],1)
            self.assertEqual(r['trusted_confirmations'],0)
    def test_sources_unknown_stop(self):
        for case in ('source_conflict','source_expired','source_missing','source_reordered'):
            _,r=self.run_case(case=case);self.assertEqual(r['unknown_count'],1)
    def test_health_no_reset_in_permanent_fault(self):
        _,r=self.run_case(case='permanent',policy='health',duration=12)
        self.assertEqual(r['decision_count'],4);self.assertFalse(r['resets'])
    def test_repeated_manual_reset_bounded(self):
        _,r=self.run_case(case='permanent',policy='manual',duration=12)
        self.assertEqual(r['decision_count'],12);self.assertEqual(len(r['resets']),2)
    def test_round_robin_service(self):
        _,a=self.run_case(case='fairness',fairness='strict',duration=20)
        _,b=self.run_case(case='fairness',fairness='round_robin',duration=20)
        self.assertEqual(a['confirmed_per_node'].get('Skill_5',0),0)
        self.assertTrue(all(b['confirmed_per_node'].get(n,0)>0 for n in NAMES))
    def test_clock_differential(self):
        _,a=self.run_case(case='long',duration=60)
        _,b=self.run_case(case='long',duration=60,long_mode=True)
        self.assertEqual(a['feedback_confirmed'],b['feedback_confirmed'])
    def test_slow_feedback_head_of_line(self):
        _,fast=self.run_case(case='fairness',fairness='round_robin',duration=20)
        _,slow=self.run_case(case='fairness_slow',fairness='round_robin',duration=20)
        self.assertLess(slow['feedback_confirmed'],fast['feedback_confirmed'])
        self.assertGreaterEqual(slow['request_confirmation_latency_ms']['min'],2000-1e-6)
    def test_stop_pending_feedback_cleanup(self):
        _,r=self.run_case(case='delayed',duration=.1)
        self.assertEqual(r['unresolved_at_stop'],1);self.assertEqual(r['trusted_confirmations'],0)
    def test_float_timestamp_collision_not_version_collision(self):
        a=17963.5600012955;b=17963.5600012965
        self.assertEqual(round(a*1e9),round(b*1e9))
        bench=FeedbackBench(self.p,'long')
        bench.frame(a);old=bench.consensus.readers['ui'].latest['Skill_4'].sequence
        bench.frame(b);new=bench.consensus.readers['ui'].latest['Skill_4'].sequence
        self.assertGreater(new,old);self.assertEqual(bench.consensus.reason,'all_sources_agree')
    def test_reset_policies_receive_same_source_trace(self):
        for policy in ('manual','state_cycle','health'):
            bench=FeedbackBench(self.p,'temporary',policy)
            self.assertFalse(bench.frame(1.2)['Skill_4'])
    def test_no_socket(self):
        with patch('socket.socket.__init__',side_effect=AssertionError('No socket')):self.run_case()

if __name__=='__main__':unittest.main(verbosity=2)
