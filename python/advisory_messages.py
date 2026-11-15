"""Chinese explanations only. Never changes decision results or sends input."""
from skill_model import SKILL_PRIORITY
LABELS={'target':'目標','enemy':'目標是否敵對','combat':'戰鬥狀態','visual_match':'採色訊號','cooldown_ready':'冷卻狀態','in_range':'距離','usable':'技能可用性'}
FALSE={'target':'沒有符合的目標','enemy':'目標不符合敵對條件','combat':'目前不符合戰鬥條件','visual_match':'採色訊號不符合','cooldown_ready':'冷卻尚未完成','in_range':'不在技能距離內','usable':'技能目前不可用'}

def reason_text(reason,resource='資源',rule=None,value=None):
    if reason=='snapshot_stale_or_invalid':return '讀值已過期或時間無效，請等待重新讀取'
    if reason=='profile_changed_or_missing':return '角色或設定檔已變更，請重新開啟監控'
    if reason=='focus_calibration_unknown':return '集中值尚未通過實機校準'
    if reason=='rule_disabled':return '此格的資源提示未啟用'
    if reason in ('rage_unknown','focus_unknown'):return resource+'讀取失敗或數值無效'
    if reason in ('rage_outside_interval','focus_outside_interval'):
        key='rage' if reason.startswith('rage') else 'focus'
        if rule is not None and type(value) is int:
            if value<rule['min_'+key]:return f"{resource}不足：目前{value}，設定最低{rule['min_'+key]}"
            if value>rule['max_'+key]:return f"{resource}超過設定上限：目前{value}，上限{rule['max_'+key]}"
        return resource+'不在設定區間內（可能不足或超過上限）'
    for key,label in LABELS.items():
        if reason==key+'_unknown':return label+'未知，暫不判定可施放'
        if reason==key+'_false':return FALSE[key]
    return '條件未確認，暫不判定可施放'

def explain(result,resource='資源',rules=None,value=None):
    candidate=result.get('candidate')
    if candidate:return '僅提示候選：按鍵'+candidate[6:]+'；已知條件符合，不送按鍵。'
    if result.get('reason'):return reason_text(result['reason'],resource)+'；不送按鍵。'
    blocked=result.get('blocked',{})
    if not blocked:return '沒有有效判斷資料；不送按鍵。'
    enabled=[n for n in SKILL_PRIORITY if n in blocked and 'rule_disabled' not in blocked[n]]
    if not enabled:return '尚未啟用任何'+resource+'提示技能，請先開啟條件設定；不送按鍵。'
    node=enabled[0]
    reasons=list(dict.fromkeys(reason_text(code,resource,(rules or {}).get(node),value) for code in blocked[node]))
    return '沒有完整符合的技能。按鍵'+node[6:]+'未通過：'+'；'.join(reasons)+'。不送按鍵。'
