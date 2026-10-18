import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const fixture=JSON.parse(await fs.readFile(new URL('../fixtures/dispatchBoardSample.json',import.meta.url),'utf8'));
let state='loaded',delay=0;
const user={id:'synthetic-dispatcher',name:'合成資料驗證',role:'pm',department:'測試'};
const addDays=(day,n)=>new Date(Date.parse(day+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
const server=await createServer({root,configFile:false,plugins:[react(),{
 name:'dispatch-contract-fixture',configureServer(server){server.middlewares.use(async(req,res,next)=>{
  const url=new URL(req.url,'http://localhost');
  const send=(body,status=200)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify(body))};
  if(url.pathname==='/__dispatch-test/state'){
   if(req.method==='POST'){let body='';for await(const chunk of req)body+=chunk;const next=JSON.parse(body);state=next.state;delay=next.delay??0}
   return send({state,delay,label:fixture.label});
  }
  if(url.pathname==='/api/session')return send({workspace_id:'dispatch-fixture',user,users:[user],mode:'demo',environment:'test',auth_configured:false,features:{workspace_shell:true,dispatch_board:state!=='flag_off',node_assignment:false}});
  if(url.pathname==='/api/workspace')return send({scope:'shell',workspace_id:'dispatch-fixture',version:1,as_of:'2026-10-18T02:00:00Z',users:[user],projects:[],approvals:[],events:[],calendar:{holidays:[],workdays:[]},source_status:{status:'ready',last_sync:'2026-10-18T02:00:00Z',message:fixture.label}});
  if(url.pathname==='/api/v2/dispatch/board'){
   const requestedState=state;
   if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
   if(requestedState==='http_failed')return send({detail:'合成讀取失敗'},500);
   if(requestedState==='http_forbidden')return send({detail:'合成權限不足'},403);
   const body=structuredClone(fixture.variants[requestedState]??fixture.variants.loaded);
   const from=url.searchParams.get('from'),to=url.searchParams.get('to');
   const offset=(Date.parse(from)-Date.parse(body.window.from))/86400000;
   for(const slot of body.slots)for(const key of ['start','end'])slot.interval[key]=addDays(slot.interval[key].slice(0,10),offset)+slot.interval[key].slice(10);
   for(const p of body.capacity.people)p.days=Object.fromEntries(Object.entries(p.days).map(([day,value])=>[addDays(day,offset),value]));
   body.window={from,to,tz:'Asia/Taipei'};
   if(body.slots.length&&to>body.source.latest_booking_date)body.source.latest_booking_date=to;
   return send(body);
  }
  if(url.pathname.startsWith('/api/'))return send({detail:'此合成驗證未提供該端點'},404);
  next();
 })}
}],server:{host:'127.0.0.1',port:Number(process.env.DISPATCH_TEST_PORT||5198),strictPort:true}});
await server.listen();server.printUrls();
