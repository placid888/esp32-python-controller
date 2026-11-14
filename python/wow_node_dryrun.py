"""Read-only dry run through actual vision/detector sample path; no worker/sender."""
import hashlib,json
from pathlib import Path
from detector import sample_node
from vision import GameVision
from wow_window import WindowError


def main():
    path=Path(__file__).with_name('config.json')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result={'monitor_started':False,'udp_sender_created':False,'nodes':{}}
    vision=GameVision()
    try:
        for name,x,y,rgb in [('Node_Target',32,277,(0,0,255)),('Node_Mark',110,276,(0,255,0))]:
            node=dict(enabled=True,x=x,y=y,coordinate_mode='wow_client',mode='color',
                      r=rgb[0],g=rgb[1],b=rgb[2],tolerance=20,sample_mode='single_pixel',match_ratio=.3)
            try:
                match,detail=sample_node(vision,node)
                result['nodes'][name]={'valid':True,'match':match,**detail}
            except Exception as exc:
                result['nodes'][name]={'valid':False,'match':None,'code':getattr(exc,'code',type(exc).__name__),'message':str(exc)}
    finally:vision.close()
    result['config_sha256_before']=before
    result['config_sha256_after']=hashlib.sha256(path.read_bytes()).hexdigest()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if all(n['valid'] for n in result['nodes'].values()) and before==result['config_sha256_after'] else 2


if __name__=='__main__':raise SystemExit(main())
