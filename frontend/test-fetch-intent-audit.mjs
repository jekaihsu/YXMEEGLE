import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {relative,join} from 'node:path';
import ts from 'typescript';

// These whole-file digests freeze the audited legacy sites, including indirect
// callbacks. Migrations remove entries; changed survivors require a fresh audit.
const legacy={
 "UnifiedHome.tsx": "4d5cf0321336c4b5588f607c664632afe62b9a2a53ed2bb3af4b13dc409f1894",
 "AssigneePicker.tsx": "2f3f8a6e8081097da460588d7957851de7e4b7bc84091a76da4af69569b16489",
 "App.tsx": "5bc89a2fd0f97dc04834c71d1870ed9ba0302a2910ff93c9518a1b157644192a",
 "CompletionCelebration.tsx": "f73bd9143729b0934efc35be418bb0b8d01ae4b7291389d022a5342af0adde7d",
 "inputRecovery.ts": "ea9bc500bbebb5a28a1755e834a9c3e352dbe7694eecc8f2e6766dbcb9810287",
 "LarkPilotPanel.tsx": "56440e752c8deefd1cf4aab42e5a95aa24c02246cb59ead49452e37a2814fbf9",
 "StageFixture.tsx": "9dfb8e14c631b01a1acd9a1adc88c5d094164b94945dadc2553c998504f52df8",
 "P2Pages.tsx": "e43860fe8bd3e7b811b594e63a6949854ecf344903541c34351562261ae593e7",
 "api.ts": "a63a733f181926716e31fde9dbc649da20d0ce978a2b70196d1d48b1a07b93f5",
 "ProjectsList.tsx": "4e04e846b5d132318070e7e3c74dc9a7a0761b3f60071a437477287107333501",
 "dispatchBoardRead.ts": "723c1765649ee9fa877267d754aa8d93fef8d66ee3f0166836b19abdf43a6163",
 "DispatchWork.tsx": "79ef8fd4ede9917b3f5fc6d2797a31953812242d397b25e67de3d65b7121fe7f",
 "useHomeReports.ts": "6fdd24349550a913ec1bae463d04167fc6ee2234752815ab3d01c345d4c7dd05",
 "DispatchBoard.tsx": "e68312a0f6c6fdaa91cdf232ee5e2cae5c1dbdb1b5726263f3991cee9257c880",
 "refreshSources.ts": "55675cabe14c1c03d37dfb62c528284b91c38ad4b3ed1e4b0cc34bf28ff61c0b",
 "TokenDashboard.tsx": "a01af58e64d817f35890b11339b712e2283fc9558c0b3c78e8571ca5af3942bb",
 "HomeDispatchCard.tsx": "74d8f6cff0919960f17c37dbd8dbc5ddc0b4089e4558ab3904421686c7a185b0",
 "useDialogFocus.ts": "b636c3476c8855862349e384da2886332caf2b28740e59a8eb69299b3be767ff",
 "useHomePanels.ts": "5aa68d997d7539e3a8ac708e3f4761bb27722152d578937fc7f8e4edfb7d0227",
 "DispatchPublishDialog.tsx": "28bc218ce2feb8aed4316350a97726aa6136a30210acda644ed03d7824479655",
 "routeLoader.ts": "5bff6b1339b36475ea28d559deb6190be55eba60970a08bbee5194543b10ce36",
 "TaskTimeline.tsx": "216aa59335a7c7c17cdf7a8b9681a40d00798b493b5f53ef1125a27743a26c71",
 "reloadGuard.ts": "1983950556280811e13d243bfcba34e97ce91814745e222e234e34f458750f0e",
 "assistant/ConversationHistory.tsx": "4efd01796fd357429ea8a7676f488d68ce94a743407bb8c76544ac51bd10fed6",
 "assistant/ProjectChatLauncher.tsx": "df78000709295f98a73c8dc2f1f2a3dd078910e9cb830671fb0243e1151dcfde",
 "reports/ContactsTab.tsx": "9a7d005c955c51c0492c185a51c77e23237661c5dc582ead8717debdd3d800ff",
 "reports/useReport.ts": "4946e4c6c0117cc0cf19b1de8ea7cf2b812d3825c5fc8586a06883fa3a4e0c1f"
};
export function triggers(source){
 const tree=ts.createSourceFile('source.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const found=[];
 function visit(node){
  if(ts.isIdentifier(node)&&['setTimeout','setInterval','onfocus','ononline','onvisibilitychange'].includes(node.text))found.push(node.text);
  if(ts.isElementAccessExpression(node)&&ts.isStringLiteral(node.argumentExpression)&&['setTimeout','setInterval','onfocus','ononline','onvisibilitychange'].includes(node.argumentExpression.text))found.push(node.argumentExpression.text);
  if(ts.isCallExpression(node)){
   const name=ts.isPropertyAccessExpression(node.expression)?node.expression.name.text:ts.isElementAccessExpression(node.expression)&&ts.isStringLiteral(node.expression.argumentExpression)?node.expression.argumentExpression.text:'';
   if(name==='addEventListener'){
    const event=node.arguments[0];
    if(!event||!ts.isStringLiteral(event)||/^(focus|focusin|focusout|visibilitychange|online)$/.test(event.text))found.push('event listener');
   }
  }
  ts.forEachChild(node,visit);
 }
 visit(tree);return found;
}
const digest=source=>createHash('sha256').update(source).digest('hex');
function files(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(join(dir,entry.name)):!/^(test[.-]|.*\.test\.)/.test(entry.name)&&/\.[cm]?[jt]sx?$/.test(entry.name)?[join(dir,entry.name)]:[])}
const violations=[];
for(const path of files(new URL('./src',import.meta.url).pathname)){
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
])assert(triggers(source).length,source);
assert.equal(triggers("read(resource,{reason:'initial_open'},loader)").length,0);
console.log('Fetch-intent audit: production trigger inventory matches reviewed legacy sites; forbidden-source fixtures detected');
