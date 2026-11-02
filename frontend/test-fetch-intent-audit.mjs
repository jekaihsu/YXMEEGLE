import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {relative,join} from 'node:path';
import ts from 'typescript';

// These whole-file digests freeze the audited legacy sites, including indirect
// callbacks. Migrations remove entries; changed survivors require a fresh audit.
const legacy={
 // C: migrated dispatch retry site has no exemption. These surviving sites
 // only restore scroll/pins or handle history keyboard/media UI; neither reads data.
 'ProjectsList.tsx': 'd2c97b8ef41d35fcfbb462967052a432dad4a69d8b28bc83a7ae8d7b3df145fb',
 'assistant/ConversationHistory.tsx': '2eea0214d33ef7dc6479b6a1fe8865eb9c5fe065ff3aaae5212d8ff978a8fcfb',
 // Newly inventoried: rAF focus/scroll (shell, flow, mentions, SOP),
 // explicit assignment notification and feedback patch microtasks,
 // presentation-only pointer/key listeners (menus, modality, picker, help),
 // user history query changes (ProgressTab), and owner cleanup microtask.
 'AppShell.tsx': '08c909c3a490826bc80f82ec07750800bf72070032d55d2bcfaf23a6445cba1f',
 'FlowActions.tsx': 'e378074c175118a65937a2206244be7754ecdc8b43c96698e0d42f5796f2687e',
 'LocalNodeActions.tsx': '84a571293507aa087f92ab7f56562ff1bce7c31201cec73c99dae041e64e4369',
 'MentionComposer.tsx': 'be14d7eb8360e3059b8838009b94c78bfaaed9f6ac4243a7e6d2080e6b6a791c',
 'ProjectFlow.tsx': '1558d1f95739dc2e8c944b253550bfb76f067ee9d051d4699b48dfa5dd8271c6',
 'SopTasks.tsx': 'b94bd8c37440073d840f8e8a013d6a67c7e750da73b2cde3656d62959d42a712',
 'assignRequests.ts': 'd75db3129c4e508d0cf9d68442372edbeec7d28a7611a1c8f7195f605dd148e6',
 'assistant/ModelSelector.tsx': 'b319065f8a628d109fa6b87f406f09ba3bc5e4fe393f4ab555b52be807c2ca09',
 'assistant/feedback.tsx': '4cd1a98c53d93890b93faf8cf5025bd9dadebd528908030a0f8cd43ff6ec5bbb',
 'assistant/useInputModality.ts': '822efb5b2e63069ef075c0a0bef50d0d5f3045dc34fb1a8422dc72fb85e11bf9',
 'design/PickerPopover.tsx': 'c9573b531f847dddeff291b4823f403f16688d4f75531339853f7d516c260ca8',
 'design/index.tsx': '0d15d44f66c4d3d7828a09a27d27137b97d20fae59243a2cbf9bd161a8210578',
 'homeHelp.tsx': 'f887c49a97ee6485a61693d54e83b7af4ca585d9648c0372b3d6e06addd1bc55',
 'pageData.ts': '1ea9ce7f21dc6d857980f948500c32c4f01fe550df11a7734d6ff966710e91d4',
 'reports/ProgressTab.tsx': '5279cd42916dda306ef7a9a5f7d76183a96558f37f98e4658d85099306c8376a',
 "AssigneePicker.tsx": "2f3f8a6e8081097da460588d7957851de7e4b7bc84091a76da4af69569b16489",
 "App.tsx": "5bc89a2fd0f97dc04834c71d1870ed9ba0302a2910ff93c9518a1b157644192a",
 "CompletionCelebration.tsx": "f73bd9143729b0934efc35be418bb0b8d01ae4b7291389d022a5342af0adde7d",
 "inputRecovery.ts": "ea9bc500bbebb5a28a1755e834a9c3e352dbe7694eecc8f2e6766dbcb9810287",
 "LarkPilotPanel.tsx": "56440e752c8deefd1cf4aab42e5a95aa24c02246cb59ead49452e37a2814fbf9",
 "StageFixture.tsx": "9dfb8e14c631b01a1acd9a1adc88c5d094164b94945dadc2553c998504f52df8",
 "P2Pages.tsx": "e43860fe8bd3e7b811b594e63a6949854ecf344903541c34351562261ae593e7",
 "api.ts": "a63a733f181926716e31fde9dbc649da20d0ce978a2b70196d1d48b1a07b93f5",
 "DispatchWork.tsx": "79ef8fd4ede9917b3f5fc6d2797a31953812242d397b25e67de3d65b7121fe7f",
 "DispatchBoard.tsx": "e68312a0f6c6fdaa91cdf232ee5e2cae5c1dbdb1b5726263f3991cee9257c880",
 "refreshSources.ts": "41162fecd19aacd07713c0bb5decc4eb91e456cbdee31ed8a2ab144da77b42ca",
 "TokenDashboard.tsx": "a01af58e64d817f35890b11339b712e2283fc9558c0b3c78e8571ca5af3942bb",
 "HomeDispatchCard.tsx": "74d8f6cff0919960f17c37dbd8dbc5ddc0b4089e4558ab3904421686c7a185b0",
 "useDialogFocus.ts": "b636c3476c8855862349e384da2886332caf2b28740e59a8eb69299b3be767ff",
 "DispatchPublishDialog.tsx": "28bc218ce2feb8aed4316350a97726aa6136a30210acda644ed03d7824479655",
 "routeLoader.ts": "5bff6b1339b36475ea28d559deb6190be55eba60970a08bbee5194543b10ce36",
 "TaskTimeline.tsx": "216aa59335a7c7c17cdf7a8b9681a40d00798b493b5f53ef1125a27743a26c71",
 "reloadGuard.ts": "1983950556280811e13d243bfcba34e97ce91814745e222e234e34f458750f0e",
 "assistant/ProjectChatLauncher.tsx": "df78000709295f98a73c8dc2f1f2a3dd078910e9cb830671fb0243e1151dcfde",
 "reports/ContactsTab.tsx": "9a7d005c955c51c0492c185a51c77e23237661c5dc582ead8717debdd3d800ff",
 "reports/useReport.ts": "5eb0692208f2e474609abc0a2e64ef2120ae08c928a6dc97aa917254220ab6c8"
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
