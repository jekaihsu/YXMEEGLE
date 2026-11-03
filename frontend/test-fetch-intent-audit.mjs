import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {relative,join} from 'node:path';
import ts from 'typescript';

// These whole-file digests freeze the audited legacy sites, including indirect
// callbacks. Migrations remove entries; changed survivors require a fresh audit.
// I8 merge: preserve both branches' legacy-site removals. Re-audit only merged
// App/AppShell presentation hooks and the unchanged I8 API/usage/submit guards.
const legacy={
 // C: migrated dispatch retry site has no exemption. These surviving sites
 // only restore scroll/pins or handle history keyboard/media UI; neither reads data.
 'ProjectsList.tsx': 'e5196eba2eebcd2c92b7fd52ad40fef24ba3d89edeee01c9822a972f3a90790e',
 'assistant/ConversationHistory.tsx': 'de8172efc6d813dbeb0eda69dc298c286342f61352255088f05d858da1917e24',
 // Newly inventoried: rAF focus/scroll (shell, flow, mentions, SOP),
 // explicit assignment notification and feedback patch microtasks,
 // presentation-only pointer/key listeners (menus, modality, picker, help),
 // user history query changes (ProgressTab), and owner cleanup microtask.
 // I1: MRU, DOM focus observer and keyboard/pointer modality listeners are presentation-only; no data reads.
 'AppShell.tsx': 'fb4a146d240f5853612b6e49ddbf85f267158b64e898cf1561231e972eb12072',
 // I3 round 1: explicit route-entry forms/focus only; existing rAF callbacks unchanged and no data read added.
 'FlowActions.tsx': '2d818daf7d733c63818d677ce8324829ea1d65d846599a2749cf2e1bb6e32fa1',
 'LocalNodeActions.tsx': '76b206ae2c41b4517b0b37b8688e20fd2809992e00d38d6fcd56024609f8fd02',
 'MentionComposer.tsx': 'be14d7eb8360e3059b8838009b94c78bfaaed9f6ac4243a7e6d2080e6b6a791c',
 'ProjectFlow.tsx': '4a760b5a26bd449969f8e4f28116ed6148d001af549f0e76984aea5c523eef40',
 'SopTasks.tsx': 'af500bcf4a7a87c91d89c13f628db7dcef76b2aa994181101369ab85aaaa3982',
 'assignRequests.ts': 'd75db3129c4e508d0cf9d68442372edbeec7d28a7611a1c8f7195f605dd148e6',
 'assistant/ModelSelector.tsx': 'b319065f8a628d109fa6b87f406f09ba3bc5e4fe393f4ab555b52be807c2ca09',
 'assistant/feedback.tsx': '4cd1a98c53d93890b93faf8cf5025bd9dadebd528908030a0f8cd43ff6ec5bbb',
 'assistant/useInputModality.ts': '822efb5b2e63069ef075c0a0bef50d0d5f3045dc34fb1a8422dc72fb85e11bf9',
 'design/PickerPopover.tsx': 'c9573b531f847dddeff291b4823f403f16688d4f75531339853f7d516c260ca8',
 // I1: DataState export; existing picker presentation listeners unchanged.
 'design/index.tsx': '6c92e3c17b2bfd8203e93dff156d6d512116ccd6fbf35713efe277d230a30115',
 'homeHelp.tsx': 'f887c49a97ee6485a61693d54e83b7af4ca585d9648c0372b3d6e06addd1bc55',
 'pageData.ts': '1bfb68b728abee62479f560fa761651fe1fd3ecb94453a52c65d6f0b3190e74d',
 'reports/ProgressTab.tsx': '52c0dd698d7e5308bd0ec41759435aa2545a9194d7f1587d7fb0ec4f790866b6',
 "AssigneePicker.tsx": "2f3f8a6e8081097da460588d7957851de7e4b7bc84091a76da4af69569b16489",
 "App.tsx": "30d42b898276f0ab7a186ed74ddec808ff9b8079dd01c89123d493199e2a284f",
 "CompletionCelebration.tsx": "f73bd9143729b0934efc35be418bb0b8d01ae4b7291389d022a5342af0adde7d",
 "inputRecovery.ts": "ea9bc500bbebb5a28a1755e834a9c3e352dbe7694eecc8f2e6766dbcb9810287",
 "LarkPilotPanel.tsx": "3173adde587f4ff70711675906c92f21db2701d87fd76be7ce6de8a7467f0326",
 "StageFixture.tsx": "9dfb8e14c631b01a1acd9a1adc88c5d094164b94945dadc2553c998504f52df8",
 "P2Pages.tsx": "fdb8dea1c8a5150331d91d5b435e4836df88dbe7e7eff261c308a880bdb075dc",
 "api.ts": "c137f0d6d6ca1cb933862bbee4334175778a858b68eed17af12718b0aa84f5ec",
 "DispatchWork.tsx": "d599c99649e1b0c1725137efae7dcd024b87ff2ac74dafc2720c341fdeaf6328",
 "DispatchBoard.tsx": "4e13a8d6874044479c7d32b60e9c25a044cce96766d132499e51bb0cb4af6514",
 "refreshSources.ts": "41162fecd19aacd07713c0bb5decc4eb91e456cbdee31ed8a2ab144da77b42ca",
 "TokenDashboard.tsx": "2c88afe1aaf09048eac6a07a87b8579ace337a1ca380bdcf71392a270208cceb",
 "HomeDispatchCard.tsx": "3cd4ce3f0572cd34767e44489432b04e43d3cc974f83aa00e3fe9ccc3bd29aee",
 "useDialogFocus.ts": "b636c3476c8855862349e384da2886332caf2b28740e59a8eb69299b3be767ff",
 "DispatchPublishDialog.tsx": "28bc218ce2feb8aed4316350a97726aa6136a30210acda644ed03d7824479655",
 "routeLoader.ts": "2412d01648b511548c49d2ff8f99493a059e52f5db723143bc93a322f98640a9",
 "TaskTimeline.tsx": "216aa59335a7c7c17cdf7a8b9681a40d00798b493b5f53ef1125a27743a26c71",
 "reloadGuard.ts": "1983950556280811e13d243bfcba34e97ce91814745e222e234e34f458750f0e",
 "assistant/ProjectChatLauncher.tsx": "df78000709295f98a73c8dc2f1f2a3dd078910e9cb830671fb0243e1151dcfde",
 "reports/ContactsTab.tsx": "f9669894e96f21adbecaa3dbd3b2ee64c53c6186722e601e9d4ccda4ebd839bc",
 "reports/useReport.ts": "5ca30dd6b109559a87001ab9decf6d18173a8fa055d92f18249fd45c9ac7c6ad"
};
export function triggers(source){
 const tree=ts.createSourceFile('source.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const found=[];
 const apis=/^(setTimeout|setInterval|requestAnimationFrame|requestIdleCallback|queueMicrotask|postTask|EventSource|WebSocket|BroadcastChannel|Worker|SharedWorker|sleep|refetchInterval|refetchOnWindowFocus|revalidateOnFocus|refreshInterval|addListener)$/;
 const events=/^(focus|focusin|focusout|visibilitychange|online|offline|pageshow|popstate|storage|pointerdown|pointermove|mousemove|keydown|keyup|wheel|message|change|yx:mutation-state)$/;
 function constant(node){
  if(node&&ts.isStringLiteralLike(node))return node.text;
  if(node&&ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.PlusToken){const a=constant(node.left),b=constant(node.right);if(a!==undefined&&b!==undefined)return a+b}
 }
 function visit(node){
  if(ts.isIdentifier(node)&&apis.test(node.text))found.push(node.text);
  const text=constant(node);if(text&&apis.test(text))found.push(text);
  if(ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.EqualsToken){
   const left=node.left,name=ts.isPropertyAccessExpression(left)?left.name.text:ts.isElementAccessExpression(left)?constant(left.argumentExpression):ts.isIdentifier(left)?left.text:'';
   if(/^on/.test(name||''))found.push('event property');
  }
  if(ts.isCallExpression(node)){
   const expr=node.expression,name=ts.isPropertyAccessExpression(expr)?expr.name.text:ts.isElementAccessExpression(expr)?constant(expr.argumentExpression):'';
   if(name==='addEventListener'){
    const event=constant(node.arguments[0]);if(!event||events.test(event))found.push('event listener');
   }
   if(name==='timeout'&&expr.getText(tree).includes('AbortSignal'))found.push('timeout signal');
  }
  if((ts.isImportDeclaration(node)||ts.isCallExpression(node))&&/['"](?:@tanstack\/react-query|react-query|swr)(?:['"/])/.test(node.getText(tree)))found.push('data library defaults require explicit audit');
  ts.forEachChild(node,visit);
 }
 visit(tree);return found;
}
const digest=source=>createHash('sha256').update(source).digest('hex');
function files(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(join(dir,entry.name)):!/^(test[.-]|.*\.test\.)/.test(entry.name)&&/\.[cm]?[jt]sx?$/.test(entry.name)?[join(dir,entry.name)]:[])}
const violations=[];
for(const path of ['src','public'].flatMap(root=>{try{return files(new URL('./'+root,import.meta.url).pathname)}catch(error){if(error.code==='ENOENT')return [];throw error}})){
 const source=readFileSync(path,'utf8'),name=relative(new URL('./src',import.meta.url).pathname,path);
 if(triggers(source).length&&legacy[name]!==digest(source))violations.push(name);
}
assert.deepEqual(violations,[],'Unaudited timer/event site: remove automatic fetching or explicitly review and fingerprint a harmless presentation/deadline/debounce site');
for(const source of [
 "setInterval(()=>api('/data'),1000)",
 "window.setTimeout(()=>reload(),1000)",
 "window.addEventListener('focus',resume); function resume(){fetch('/data')}",
 "document.addEventListener('visibilitychange',()=>store.read(resource,{reason:'explicit_refresh',id:Date.now()},load))",
 "window.addEventListener('online',refresh)",
 "const later=globalThis['setTimeout']; later(read,1000)",
 "window.addEventListener(eventName,read)",
 "window.onfocus=read",
 "requestAnimationFrame(tick)", "requestIdleCallback(tick)", "queueMicrotask(tick)",
 "await new Promise(r=>setTimeout(r,1))", "await sleep(10)", "AbortSignal.timeout(10)",
 "scheduler.postTask(read,{delay:100})", "new EventSource('/api').onmessage=read",
 "new WebSocket('/api').onclose=reconnect", "new BroadcastChannel('tick').onmessage=read",
 "window.addEventListener('storage',read)", "window.addEventListener('pageshow',read)",
 "window.onpageshow=read", "window.onoffline=read", "window.addEventListener('popstate',read)",
 "window.addEventListener('pointerdown',read)", "window.addEventListener('keydown',read)",
 "window.addEventListener('wheel',read)", "matchMedia('x').addListener(read)",
 "navigator.connection.onchange=read", "window.addEventListener('yx:mutation-state',read)",
 "Reflect.get(globalThis,'setInterval')(read,100)", "globalThis['set'+'Interval'](read,100)",
 "const later=setInterval; later(read,1)", "new Worker('ticker.js')", "worker.onmessage=read",
 "import {useQuery} from '@tanstack/react-query'", "import useSWR from 'swr'",
 "const opts={refetchOnWindowFocus:true,refetchInterval:1000}",
])assert(triggers(source).length,source);
assert.equal(triggers("read(resource,{reason:'initial_open'},loader)").length,0);
console.log('Fetch-intent audit: production trigger inventory matches reviewed legacy sites; forbidden-source fixtures detected');

// Keep the safety net on the default local gate, with Chrome separately opt-in.
const pkg=JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8'));
for(const name of ['test-fetch-intent.mjs','test-fetch-intent-react.mjs','test-fetch-intent-audit.mjs'])assert(pkg.scripts['test:fetch-intent'].includes(name));
assert(pkg.scripts['test:fetch-intent:browser'].includes('test-fetch-intent-browser.mjs'));
const ci=readFileSync(new URL('../scripts/local_ci.sh',import.meta.url),'utf8');assert(ci.includes('npm run test:fetch-intent\n'));assert(ci.includes('npm run test:fetch-intent:browser'));
