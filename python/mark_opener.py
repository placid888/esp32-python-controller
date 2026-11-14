"""Independent opener retry timer; visual Node_Mark is the sole success signal."""
MARK_DEFAULTS={'hunter_mark_mode':'off','hunter_mark_key':'3','hunter_mark_retry_ms':500}
MARK_SPELL_ID=257284  # Documentation/diagnostics only. No game API access.

def mark_settings(profile):
    values={key:profile.get(key,value) for key,value in MARK_DEFAULTS.items()}
    if values['hunter_mark_mode'] not in ('off','pre_combat','post_combat'):raise ValueError('Unknown Hunter Mark mode')
    key=values['hunter_mark_key']
    if not isinstance(key,str) or len(key)!=1 or not 33<=ord(key)<=126:
        raise ValueError('Hunter Mark Key must be one printable ASCII key (for example 3)')
    retry=values['hunter_mark_retry_ms']
    if type(retry) is not int or not 1<=retry<=60000:raise ValueError('Retry Delay must be 1..60000 ms')
    return values

class OpenerMark:
    def __init__(self,key='3',retry_ms=500):
        self.key=key;self.retry_ms=retry_ms;self.pending=None
    def cancel(self):
        had=self.pending is not None;self.pending=None;return had
    def observe(self,allowed,now):
        if not allowed:return self.cancel()
        if self.pending is None:self.pending=now  # First try immediately, after current fresh scan.
        return False
    def is_due(self,now):return self.pending is not None and now>=self.pending
    def attempted(self,now):self.pending=now+self.retry_ms/1000
    def command(self):return {'action':'tap','key':self.key}
