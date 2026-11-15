"""Per-scope MANUAL field-test notes, separate from config and automated validation."""
import copy,hashlib,json,os,tempfile
from pathlib import Path
from datetime import datetime
import profile_store as store
STATUSES=('待測','手動回報通過','手動回報未通過','手動標記不適用')

def cases(character):
    resource='怒氣' if character=='warrior' else '集中值'
    result=[
      ('layout','版面與解析度','確認對應Clean版面、1920×1080遊戲視窗、資源條位置沒有移動。','版面與取樣假設一致；改動後需重新核對。'),
      ('resource',resource+'讀值對照','在安全的遊戲情境觀察0、中間與較高數值，對照遊戲條與唯讀監控。','記錄實際值、估計值與差距；目前原型假設最大值100，不適用時不要標通過。'),
      ('target','目標色塊','手動選取及取消目標，觀察既有目標色塊。','色塊按選取狀態切換；不代表敵對判斷已整合。'),
      ('combat','戰鬥色塊','自行進入及退出戰鬥，觀察既有戰鬥色塊。','色塊與戰鬥狀態對得上，切換時記錄延遲。'),
      ('skills','已學技能格採色','只逐格核對已學到且已配置的技能；空格保持停用。','記錄格號與亮暗對照，未學技能不假裝測完。'),
      ('advisory','資源提示與阻擋','觀察資源條件提示與未知證據的阻擋，不啟動自動按鍵。','資源足夠不等於可施放；冷卻／距離／可用性未整合時仍應阻擋。'),
      ('foreground','失焦與遮擋','在方便時手動切走魔獸前景或遮擋資源條，再恢復。','顯示無法讀取／未知，不把舊值當新值。'),
      ('party','組隊／團隊位置','使用遊戲預覽或實際組隊核對框架位置，記錄使用哪種方式。','不遮擋資源條與主要技能；預覽不代表已完成實際團隊測試。'),
      ('hotkeys','F8／F9／F10原生熱鍵','確認沒有其他程式占用後，依現有採色與校準說明自行測試。','記錄是否能註冊與對應操作；目前註冊問題仍需另測。'),
      ('stop','Dry Run與停止','先確認Dry Run且未連線，檢查停止監控按鈕；不要為此啟動硬體。','停止後不繼續讀值；此項不保證ESP32裝置已釋放按鍵。')]
    if character=='warrior':result.append(('stance','可用姿態切換','解鎖並確認可用姿態後，自行切換核對位置；未解鎖可先保持待測並註記。','姿態切換不破壞資源條、技能格與取樣位置。'))
    if character=='hunter':result.append(('pet','寵物框與傷害範圍','確認寵物框、寵物技能列與人物集中值互不遮擋。','目前不以DPS做自動優化；寵物框位置只作人工核對。'))
    return [{'id':key,'title':title,'steps':steps,'expected':expected} for key,title,steps,expected in result]

def digest(raw):return hashlib.sha256(raw).hexdigest()
def scope(path):
    data=store.read(path);p=data['profiles'][data['last_used']];identity=(data['last_used'],p['selected_class'],p['selected_spec'])
    payload={'global':p['global'],'shared':p['classes'][identity[1]]['shared'],'spec':p['classes'][identity[1]]['specs'][identity[2]]}
    return identity,digest(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode())
def key(identity):return json.dumps(list(identity),ensure_ascii=False,separators=(',',':'))
def notes_path(config):return Path(config).with_name('manual_test_checklist.json')
def load(config):
    path=notes_path(config)
    if not path.exists():return {'format':'manual-test-checklist-v1','scopes':{}},None
    raw=path.read_bytes()
    if len(raw)>8*1024*1024:raise ValueError('實測紀錄超過8MB')
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or data.get('format')!='manual-test-checklist-v1' or not isinstance(data.get('scopes'),dict):raise ValueError('實測紀錄格式不符；未覆寫')
    for records in data['scopes'].values():
        if not isinstance(records,dict):raise ValueError('實測紀錄損壞')
        for record in records.values():
            if not isinstance(record,dict) or record.get('status') not in STATUSES or not isinstance(record.get('note'),str) or len(record['note'])>1000 or not isinstance(record.get('fingerprint'),str):raise ValueError('實測項目格式不符；未覆寫')
    return data,digest(raw)
def rows(config):
    identity,fingerprint=scope(config);data,_=load(config);saved=data['scopes'].get(key(identity),{});result=[]
    for case in cases(identity[1]):
        record=saved.get(case['id']);stale=bool(record and record['fingerprint']!=fingerprint)
        status='待測' if record is None else ('設定已變更，需重測' if stale else record['status'])
        result.append(dict(case,status=status,record=copy.deepcopy(record),stale=stale))
    return identity,fingerprint,result

def save(config,identity,fingerprint,case_id,status,note,expected_record):
    if status not in STATUSES or not isinstance(note,str) or len(note)>1000 or '\x00' in note:raise ValueError('狀態不符或備註超過1000字')
    if case_id not in {c['id'] for c in cases(identity[1])}:raise ValueError('未知實測項目')
    if scope(config)!=(tuple(identity),fingerprint):raise ValueError('角色或設定已變更，請重新載入清單')
    data,old_hash=load(config);records=data['scopes'].setdefault(key(identity),{})
    if records.get(case_id)!=expected_record:raise ValueError('此項紀錄已被修改，請重新載入，避免覆寫')
    previous=records.get(case_id);history=copy.deepcopy(previous.get('history',[])) if previous else []
    if previous:history.append({k:v for k,v in previous.items() if k!='history'})
    records[case_id]={'status':status,'note':note,'fingerprint':fingerprint,'updated_at':datetime.now().astimezone().isoformat(),'source':'manual_user_report','history':history[-20:]}
    path=notes_path(config);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='checklist-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        current=digest(path.read_bytes()) if path.exists() else None
        if current!=old_hash or scope(config)!=(tuple(identity),fingerprint):raise ValueError('紀錄或設定已變更，未寫入；請重載')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return copy.deepcopy(records[case_id])

def export_report(config):
    identity,_,items=rows(config);lines=['# 待實測清單（手動紀錄，不是程式驗證）','', '設定：'+'／'.join(identity),'', '手動回報不會解除校準限制、變更技能開關或標示程式驗證完成。','']
    for item in items:
        lines.extend(['## '+item['title'],'狀態：'+item['status'],'操作：'+item['steps'],'預期：'+item['expected']])
        record=item['record']
        if record:lines.extend(['備註：'+record['note'],'回報時間：'+record.get('updated_at',''),'原手動狀態：'+record['status']])
        lines.append('')
    folder=Path(config).parent/'diagnostics'/'checklists';folder.mkdir(parents=True,exist_ok=True);path=folder/('manual-checklist-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.md')
    with path.open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    return path
