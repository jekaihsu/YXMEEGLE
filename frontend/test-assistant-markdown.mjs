import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import Markdown from 'react-markdown';
import {JSDOM} from 'jsdom';
const bundle=await build({entryPoints:['src/assistant/markdown.ts'],bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
const path=new URL('./.assistant-markdown-test.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let plugins;try{plugins=(await import(path.href)).assistantRemarkPlugins}finally{await fs.unlink(path)}
const render=text=>new JSDOM(renderToStaticMarkup(React.createElement(Markdown,{remarkPlugins:plugins},text))).window.document;
const strong=[
 '- **缺卡、遲到、早退、出差、外出、補卡 / 修正：**目前都沒有人。',
 '- **請假：**劉耀云、林威仁。','- **尚無打卡紀錄：**58 人。',
 ...[...'：、。，）」'].map(p=>`**文字${p}**中文`),
 '| 狀態 |\n|---|\n| **請假：**劉耀云 |',
 '**外層 *內層：*中文**','**English bold**',
];
for(const text of strong){const doc=render(text);assert.ok(doc.querySelector('strong'),text);assert.ok(!doc.body.textContent.includes('*'),text)}
for(const text of ['*文字：*中文','_文字_','*English emphasis*'])assert.ok(render(text).querySelector('em'),text);
assert.ok(render('~~文字：~~中文').querySelector('del'));
assert.ok(render('**外層 *內層：*中文**').querySelector('strong em'));
for(const [text,expected] of [['\\*\\*文字\\*\\*','**文字**'],['`**文字：**中文`','**文字：**中文'],['3*4*5','3*4*5'],['中文_文字_中文','中文_文字_中文']]){
 const doc=render(text);assert.equal(doc.body.textContent,expected);assert.equal(doc.querySelector('strong,em,del'),null);
}
const link=render('[**請假：**劉耀云](https://example.com/a_b?q=3*4*5)').querySelector('a');
assert.equal(link.href,'https://example.com/a_b?q=3*4*5');assert.ok(link.querySelector('strong'));
console.log('Assistant markdown matrix passed.');
