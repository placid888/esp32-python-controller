"""Data-only registry. Register a ClassDefinition to add GUI choices, not rotations."""
from dataclasses import dataclass,field
from typing import Any
@dataclass(frozen=True)
class SpecDefinition:
    id:str
    name:str
@dataclass(frozen=True)
class ClassDefinition:
    id:str
    name:str
    specs:tuple[SpecDefinition,...]
    default_spec:str
@dataclass(frozen=True)
class ActionDefinition:
    kind:str  # future target / ability / sequence; NOT executed in this release
    target:str|None=None
    ability:str|None=None
    sequence:tuple=()
    metadata:dict[str,Any]=field(default_factory=dict)
CLASSES={}
def register(definition):
    if definition.id in CLASSES:raise ValueError('Duplicate class ID')
    ids=[s.id for s in definition.specs]
    if not ids or len(ids)!=len(set(ids)) or definition.default_spec not in ids:raise ValueError('Invalid spec registry')
    CLASSES[definition.id]=definition
register(ClassDefinition('hunter','獵人',(SpecDefinition('beast_mastery','獸王'),SpecDefinition('marksmanship','射擊'),SpecDefinition('survival','生存')),'marksmanship'))
register(ClassDefinition('warrior','戰士',(SpecDefinition('arms','武器'),SpecDefinition('fury','狂怒'),SpecDefinition('protection','防護')),'arms'))
MIGRATION_CLASS='hunter'
MIGRATION_SPEC='marksmanship'
def definition(class_id):return CLASSES[class_id]
def spec_definition(class_id,spec_id):return next(s for s in definition(class_id).specs if s.id==spec_id)
