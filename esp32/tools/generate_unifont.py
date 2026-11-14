from pathlib import Path
import gzip
root=Path(__file__).resolve().parents[1]
rows=[]
for line in gzip.decompress((root/'fonts/unifont-16.0.04.hex.gz').read_bytes()).decode().splitlines():
 cp,h=line.split(':');cp=int(cp,16)
 if 32<=cp<=126 or 0x3000<=cp<=0x303f or 0x3400<=cp<=0x9fff or 0xf900<=cp<=0xfaff or 0xff00<=cp<=0xffef or cp==0xfffd:
  b=bytes.fromhex(h);w=8 if len(b)==16 else 16
  if len(b) not in (16,32):continue
  if w==8:b=b''.join(bytes([v,0]) for v in b)
  rows.append((cp,w,b))
assert rows==sorted(rows)
with (root/'src/unifont_subset.h').open('w',encoding='utf-8') as f:
 f.write('// Generated from GNU Unifont 16.0.04; see fonts/ for source and licenses.\n#pragma once\n#include <Arduino.h>\nstruct LcdGlyph { uint16_t code; uint8_t width; uint8_t rows[32]; };\nstatic const LcdGlyph lcdGlyphs[] PROGMEM = {\n')
 for cp,w,b in rows:f.write('{%d,%d,{%s}},\n'%(cp,w,','.join(str(v) for v in b)))
 f.write('};\n')
print('Generated glyphs:',len(rows))
