import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const css=await fs.readFile(new URL('./src/assistant/ProjectChatLauncher.css',import.meta.url),'utf8');
assert.match(css,/@container\s*\(max-width:750px\)/,'reserved chat column must use content width for stage layout');
assert.match(css,/\.project-detail\.project-detail-calm \.pf-diagram-compact \.pf-chain\s*\{[^}]*flex-wrap:wrap/);
assert.match(css,/\.project-detail\.project-detail-calm \.pf-diagram-compact \.pf-chain>li\s*\{[^}]*flex:0 0 calc\(100% \/ 3\)/);
assert.match(css,/\.project-detail\.project-detail-calm \.pf-diagram-compact \.pf-chain>li::after\s*\{display:none\}/);
console.log('Project chat narrow container stage layout passed.');
