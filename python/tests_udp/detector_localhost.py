import sys,socket,tempfile,time,json,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from detector import DetectorWorker
from transport import ESP32Controller
from profile_store import default_nodes
class Pixels:
    def get_region_rgb(self,*a):return [(255,255,255)]
    def close(self):pass
nodes=default_nodes()
for n in nodes.values():n.update(min_delay=50,max_delay=50)
nodes['Skill_4']['enabled']=True
with tempfile.TemporaryDirectory() as temp, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
    sock.bind(('127.0.0.1',0));sock.settimeout(.3)
    c=ESP32Controller('127.0.0.1',sock.getsockname()[1]);c.evidence_path=Path(temp)/'tx.jsonl'
    original=c._write_evidence
    def slow_log(record):time.sleep(.03);original(record)
    c._write_evidence=slow_log
    assert c.connect()
    w=DetectorWorker(nodes,c.send_command,Pixels);w.start();time.sleep(1.5);w.stop()
    received=[]
    try:
        while True:received.append(json.loads(sock.recvfrom(1024)[0]))
    except socket.timeout:pass
    c.disconnect();c._thread.join(10)
    assert not c._thread.is_alive() and not c._evidence_thread.is_alive()
    rows=[json.loads(l) for l in c.evidence_path.read_text().splitlines()]
    tx=[r for r in rows if r['event']=='UDP_TX' and r['source_node']=='Skill_4']
    errors=[r['scheduling_error_ms'] for r in tx]
    assert len(errors)>=20 and all(r=={'action':'tap','key':'4'} for r in received)
    assert max(errors)<500
    result={'status':'PASS','test':'localhost UDP only; fake pixels; GUI not pumped; evidence writer sleeps 30ms per record',
        'packets':len(received),'average_sendto_error_ms':statistics.mean(errors),'maximum_sendto_error_ms':max(errors),'errors_ms':errors}
    out=Path(__file__).resolve().parents[1]/'backups/detector-worker-20261101'
    (out/'localhost-result.json').write_text(json.dumps(result,indent=2));(out/'localhost-tx.jsonl').write_text(chr(10).join(json.dumps(r) for r in rows))
print(result)

