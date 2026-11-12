import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';

const homeGraph=await build({entryPoints:['src/HomeDispatchCard.tsx'],absWorkingDir:import.meta.dirname,bundle:true,write:false,metafile:true,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const staticReach=new Set(),queue=['src/HomeDispatchCard.tsx'];
for(let file;(file=queue.pop())!==undefined;){if(staticReach.has(file))continue;staticReach.add(file);for(const edge of homeGraph.metafile.inputs[file]?.imports??[])if(edge.kind!=='dynamic-import')queue.push(edge.path)}
assert.equal([...staticReach].some(file=>file.endsWith('/DispatchBoard.tsx')||file.endsWith('/DispatchBoard.css')),false,'home must not pull in the board UI or CSS');
await import('./test-fe2-load-once.mjs');
