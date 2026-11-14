"""Priority-selected repeat, one in-flight event, freshly timed after each dispatch."""
import random
import time
from skill_model import SKILL_PRIORITY, skill_command

class DecisionEngine:
    def __init__(self,clock=time.monotonic,randint=random.randint):
        self.clock=clock;self.randint=randint;self.reset()
    def reset(self):
        self.states={};self.latched={};self.pending={};self.chosen_skill=None;self.arbitration={}
        self._inflight=None;self._bounds={}
    def _arm(self,name):
        low,high=self._bounds[name]
        if low<1 or high<low:
            raise ValueError('重複模式需要 1 <= Min Delay <= Max Delay，避免零延遲 HID spam')
        delay=self.randint(low,high)
        self.pending[name]=(self.clock()+delay/1000.0,skill_command(name),delay)
    def observe(self,conditions,nodes,combat_mode='auto'):
        gate=bool(nodes.get('Node_Target',{}).get('enabled',False) and conditions.get('Node_Target',False))
        self.states['Node_Target']=gate
        combat=bool(nodes.get('Node_Combat',{}).get('enabled',False) and conditions.get('Node_Combat',False))
        self.states['Node_Combat']=combat
        gate=bool(gate and (combat_mode=='auto' or (combat_mode=='manual_first_hit' and combat)))
        self.states['Skill_Gate']=gate
        eligible=[]
        for name in SKILL_PRIORITY:
            n=nodes.get(name,{})
            active=bool(gate and n.get('enabled',False) and conditions.get(name,False))
            self.states[name]=active
            self._bounds[name]=(n.get('min_delay',25),n.get('max_delay',60))
            if active:eligible.append(name)  # No consumed/latch exclusion in repeat mode.
        chosen=eligible[0] if eligible else None
        if set(self.pending)!=(set([chosen]) if chosen else set()):self.pending.clear()
        self.chosen_skill=chosen
        if chosen and chosen not in self.pending and self._inflight is None:self._arm(chosen)
        self.arbitration={name:(('blocked_by_Target' if not self.states['Node_Target'] else 'waiting_for_combat') if not gate else
            'disabled' if not nodes.get(name,{}).get('enabled',False) else
            'own_condition_false' if not conditions.get(name,False) else
            'selected_wait_delay' if name==chosen else 'blocked_by_priority='+str(chosen)) for name in SKILL_PRIORITY}
    def is_due(self):
        return bool(self.pending and self.clock()>=next(iter(self.pending.values()))[0])
    def poll(self):
        if self._inflight is not None or not self.is_due():return []
        name,(deadline,command,delay)=next(iter(self.pending.items()))
        self.pending.clear()
        if not self.states.get('Skill_Gate',False) or not self.states.get(name,False) or name!=self.chosen_skill:return []
        self._inflight=name
        return [{'node':name,'command':skill_command(name),'delay_ms':delay}]
    def complete_dispatch(self,name):
        # Called after local queue accepts/rejects: next interval starts here, not at prior scan.
        if self._inflight!=name:return
        self._inflight=None
        if self.states.get('Skill_Gate',False) and self.chosen_skill==name and self.states.get(name,False):self._arm(name)

def node_matches(rgb,node):
    r,g,b=(int(v) for v in rgb)
    if not node['enabled']:return False
    if node['mode']=='color':return all(abs(a-node[k])<=node['tolerance'] for a,k in zip((r,g,b),('r','g','b')))
    value=r if node['mode']=='red' else (r+g+b)/3
    return value>node['threshold']
