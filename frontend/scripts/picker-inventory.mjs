import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const root=path.resolve(import.meta.dirname,'..');
const entries=[];
const components=new Set(['Picker','AssigneePicker','OwnerSelect','TaskPersonPicker','WeekPicker','HomePreviewPicker','Select','FormSelect','ComboInput','MentionComposer','DetailsMenu']);
function scan(dir){for(const file of fs.readdirSync(dir,{withFileTypes:true})){const full=path.join(dir,file.name);if(file.isDirectory())scan(full);else if(file.name.endsWith('.tsx')){
 const text=fs.readFileSync(full,'utf8'),source=ts.createSourceFile(full,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 function visit(node){if(ts.isJsxOpeningElement(node)||ts.isJsxSelfClosingElement(node)){
  const tag=node.tagName.getText(source),attrs=node.attributes.getText(source),date=tag==='input'&&/type=['"](?:date|datetime-local|month|week|time)['"]/.test(attrs);
  const attr=name=>node.attributes.properties.find(p=>ts.isJsxAttribute(p)&&p.name.getText(source)===name)?.initializer;
  const role=attr('role'),classes=attr('className');
  const menu=tag==='details'&&classes&&ts.isStringLiteral(classes)&&/menu|pds-more/.test(classes.text)||role&&ts.isStringLiteral(role)&&role.text==='menu';
  const suggestions=tag==='input'&&!!attr('list');
  if(components.has(tag)||tag==='select'||date||menu||suggestions)entries.push({file:path.relative(root,full),line:source.getLineAndCharacterOfPosition(node.getStart()).line+1,kind:suggestions?'suggestions':date?'date':menu?'menu':tag,props:attrs.replace(/\s+/g,' ').slice(0,240)});
 }ts.forEachChild(node,visit)}visit(source);
}}}
scan(path.join(root,'src'));
if(process.argv.includes('--json'))console.log(JSON.stringify(entries,null,2));else console.log(['| Usage | Type | Before | After |','|---|---|---|---|',...entries.map(e=>`| ${e.file}:${e.line} | ${e.kind} | Not individually verified | See browser coverage report |`)].join('\n'));
