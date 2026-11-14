import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sys,time,json
from detector import DetectorWorker
from vision import GameVision
from profile_store import default_nodes
nodes=default_nodes()
for i,n in enumerate(nodes.values()):n.update(enabled=True,x=100+10*i,y=100,mode='color',tolerance=255,min_delay=50,max_delay=50)
w=DetectorWorker(nodes,lambda *a,**k:True,GameVision);w.start();time.sleep(1.6);w.stop()
print(json.dumps({'scan_hz':w.scan_count/(time.monotonic()-w.started),'scan_count':w.scan_count,'test':'auto; real MSS; fake sender; all Skill ROIs near each other'}))
