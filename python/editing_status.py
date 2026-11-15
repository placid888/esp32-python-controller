"""Session-only state labels. Simulation is never called real-game validation."""
import hashlib,json,time
import profile_store as store
from mark_opener import mark_settings
from skill_flow import modules

def fingerprint(rules):return hashlib.sha256(json.dumps(rules,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def record_simulation(app,identity,rules,result,source):
    app._last_skill_simulation={'identity':tuple(identity),'rules_hash':fingerprint(rules),'candidate':result.get('candidate'),
                               'source':source,'time':time.time()}

def clear_simulation(app,identity=None):
    record=getattr(app,'_last_skill_simulation',None)
    if record and (identity is None or record['identity']==tuple(identity)):app._last_skill_simulation=None

def editor_event(app,identity,window,dirty,valid):
    app._resource_editor_state={'identity':tuple(identity),'window':window,'dirty':bool(dirty),'valid':bool(valid)}

def status_lines(app):
    try:
        data=store.read(app.app_config_path);p=data['profiles'][data['last_used']];identity=(data['last_used'],p['selected_class'],p['selected_spec'])
        if identity[1:]!=(getattr(app,'selected_class',None),getattr(app,'selected_spec',None)) or identity[0]!=getattr(app,'active_profile_name',identity[0]):return ['角色／設定檔切換中，暫不顯示儲存或測試狀態。']
        module=modules(identity[1])[0];saved_identity,rules=module.load(app.app_config_path)
        if saved_identity!=identity:raise ValueError('context changed')
    except Exception:return ['儲存狀態：無法確認磁碟設定，請檢查設定檔。','實機技能測試：沒有已驗證紀錄，不標示完成。']
    dirty=[];invalid=False
    try:
        if app.edited_nodes()!=p['nodes'] or app.edited_combat_mode()!=p.get('combat_mode','auto') or app.edited_mark_settings()!=mark_settings(p):dirty.append('主頁採色／開戰設定')
    except Exception:invalid=True
    editor=getattr(app,'_resource_editor_state',None)
    try:
        if editor and editor['identity']==identity and editor['window'].winfo_exists():
            if editor['dirty']:dirty.append('資源條件編輯器')
            if not editor['valid']:invalid=True
    except Exception:pass
    wizard=getattr(app,'skill_wizard',None)
    try:
        if wizard and wizard.window.winfo_exists() and wizard.dirty:dirty.append('技能設定精靈')
    except Exception:pass
    pending=False
    try:
        window=getattr(app,'node_editor',None)
        pending=window is not None and window.winfo_exists()
    except Exception:pass
    if invalid:editing='編輯狀態：部分內容無效或尚未就緒；不能當成已儲存。'
    elif pending:editing='編輯狀態：進階採色編輯窗尚未關閉；未套用內容未納入儲存判斷。'
    elif dirty:editing='編輯狀態：有未儲存修改（'+'、'.join(dirty)+'）。'
    else:editing='編輯狀態：已與磁碟設定一致（已儲存，不代表測試通過）。'
    record=getattr(app,'_last_skill_simulation',None)
    if not record or record['identity']!=identity:simulation='手動模擬：本次開啟控制台後，尚無此設定的模擬結果。'
    elif record['source']=='demo':simulation='手動模擬：最近一次使用示範假資料，不算已儲存技能條件通過。'
    elif record['rules_hash']!=fingerprint(rules):simulation='手動模擬：設定已變更，舊結果不適用，請重新測試。'
    elif record['candidate']:simulation='手動模擬：最近一次有候選（按鍵'+record['candidate'][6:]+'）；只代表當時手動假條件。'
    else:simulation='手動模擬：最近一次被阻擋／無候選，不是整套功能測試通過。'
    if dirty:simulation+=' 未儲存修改不包含在此結果。'
    return [editing,simulation,'實機技能測試：沒有可核對的已驗證紀錄，維持待測；資源讀值驗證另外顯示。']
