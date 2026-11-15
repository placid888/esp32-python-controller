"""Read-only saved-setting hints, not proof of live calibration."""
from skill_model import SKILL_PRIORITY
import profile_store as store
from resource_calibration_ui import status_text

def warnings_for(app):
    character=getattr(app,'selected_class',None)
    resource={'warrior':'怒氣','hunter':'集中值'}.get(character,'資源')
    try:
        data=store.read(app.app_config_path);profile=data['profiles'][data['last_used']]
        if (profile['selected_class'],profile['selected_spec'])!=(character,getattr(app,'selected_spec',None)):return ['角色切換中，請等待重新載入設定。']
        if data['last_used']!=getattr(app,'active_profile_name',data['last_used']):return ['設定檔切換中，請等待重新載入。']
        if character=='warrior':from rage_rules import load
        elif character=='hunter':from focus_rules import load
        else:return ['此職業尚未支援資源提示。']
        identity,rules=load(app.app_config_path)
    except Exception:return ['已儲存設定或資源條件無法通過檢查，請開啟設定確認（例如技能名稱或資源範圍）。']
    messages=[];nodes=profile['nodes']
    heading,_=status_text(character,identity=identity,config_path=app.app_config_path)
    if '滿值已核對' in heading:messages.append('集中值滿值已核對；中低值、下降及恢復仍待驗證，尚未完成完整校準。')
    elif '已完成' not in heading:messages.append(resource+'讀值尚未驗證完成，請勿把模擬通過視為實機校準完成。')
    for n in ('Node_Target','Node_Combat')+SKILL_PRIORITY:
        node=nodes.get(n,{})
        if node.get('enabled') and node.get('x')==0 and node.get('y')==0:
            label={'Node_Target':'目標','Node_Combat':'戰鬥'}.get(n,'按鍵'+n[6:])
            messages.append(label+'採色座標為(0,0)，可能尚未設定；若是刻意設定請自行確認。')
    enabled=[n for n in SKILL_PRIORITY if rules[n]['enabled']]
    if not enabled:messages.append('尚未啟用'+resource+'提示條件；目前沒有技能也可保持停用。')
    for n in enabled:
        node=nodes.get(n,{})
        if not node.get('enabled'):messages.append('按鍵'+n[6:]+'資源提示已啟用，但採色停用；真實整合判斷會因缺少採色訊號而阻擋。')
    if any(nodes[n].get('enabled') for n in SKILL_PRIORITY) and not enabled:
        messages.append('技能採色與資源提示是兩套設定；採色啟用不會自動啟用資源提示。')
    return messages or ['未發現上述設定缺漏；仍不代表遊戲內校準或技能測試已通過。']
