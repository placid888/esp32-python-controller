"""Single source of truth for visual-skill priority and fixed HID keys."""
SKILL_PRIORITY = ('Skill_4','Skill_5','Skill_6','Skill_7','Skill_8','Skill_9','Skill_0')
SKILL_KEYS = {name: name.removeprefix('Skill_') for name in SKILL_PRIORITY}
GATE_NAMES = ('Node_Target','Node_Combat','Node_Mark')
NODE_NAMES = ('Node_Target',) + SKILL_PRIORITY + ('Node_Combat','Node_Mark')

def skill_command(name):
    return {'action':'tap','key':SKILL_KEYS[name]}

