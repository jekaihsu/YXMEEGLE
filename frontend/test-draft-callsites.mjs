// Every ActionForm/DraftForm call site must pass a draftId that varies with the record/period; omitted or constant ids fail.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const SINGLETON_IDS=new Set(['admin-settings','admin-calendar']);
const sites=[];
for(const f of fs.readdirSync('src').filter(f=>f.endsWith('.tsx')&&f!=='FormDraft.tsx')){
 const sf=ts.createSourceFile(f,fs.readFileSync(`src/${f}`,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const visit=n=>{
  if(ts.isJsxOpeningElement(n)||ts.isJsxSelfClosingElement(n)){
   const tag=n.tagName.getText(sf);
   if(tag==='ActionForm'||tag==='DraftForm'){
    const title=n.attributes.properties.find(a=>ts.isJsxAttribute(a)&&a.name.text==='title');
    const attr=n.attributes.properties.find(a=>ts.isJsxAttribute(a)&&a.name.text==='draftId');
    const submit=n.attributes.properties.find(a=>ts.isJsxAttribute(a)&&a.name.text==='onSubmit');
    const handler=submit?.initializer?.expression;
    assert.ok(handler&&ts.isArrowFunction(handler),`${f}: expected an explicit save callback`);
    assert.ok(!ts.isVoidExpression(handler.body),`${f}: save callback must return the promise`);
    if(ts.isBlock(handler.body))assert.ok(handler.body.statements.some(ts.isReturnStatement),`${f}: save callback must return its save result`);
    sites.push({where:`${f}:${sf.getLineAndCharacterOfPosition(n.getStart()).line+1}`,title:title?.initializer?.getText(sf),attr,sf});
   }
  }
  ts.forEachChild(n,visit);
 };
 visit(sf);
}
assert.ok(sites.length>=25,`expected to find the call sites, found ${sites.length}`);
const seen=new Map();
for(const {where,title,attr,sf} of sites){
 assert.ok(attr,`${where} ${title}: draftId omitted`);
 const init=attr.initializer;
 const expr=init&&ts.isJsxExpression(init)?init.expression:init;
 assert.ok(expr,`${where}: draftId has no value`);
 if(ts.isStringLiteral(expr)){
  assert.ok(SINGLETON_IDS.has(expr.text),`${where} ${title}: constant draftId "${expr.text}" is not an allowed singleton form`);
  continue;
 }
 assert.ok(ts.isTemplateExpression(expr)&&expr.templateSpans.length>0,`${where} ${title}: draftId must interpolate record/period identity`);
 const text=expr.getText(sf);
 assert.ok(!/revision\s*\|\|/.test(text),`${where}: draftId must not fall back on a constant revision`);
 const prefix=expr.head.text;
 assert.ok(prefix.length>1,`${where}: draftId needs an action prefix`);
 const key=`${prefix}`;
 if(seen.has(key))assert.equal(seen.get(key).title,title,`${where}: prefix ${prefix} shared by different forms (${seen.get(key).where})`);
 else seen.set(key,{where,title});
}
// Recurring execution is bound to its period, not a nonexistent revision field.
const recurring=sites.find(s=>s.attr?.initializer?.getText(s.sf).includes('`recurring:'));
assert.ok(recurring&&/due_date/.test(recurring.attr.initializer.getText(recurring.sf)),'recurring execution draftId must include the period due_date');
console.log(`draft call sites: ok (${sites.length})`);
