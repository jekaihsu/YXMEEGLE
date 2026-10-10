// Drive all browser and global timers without waiting or contacting a service.
export function fakeClock(window,initial=Date.now()){
 const originals={setTimeout,clearTimeout,setInterval,clearInterval,now:Date.now,windowTimeout:window.setTimeout,windowClear:window.clearTimeout,windowInterval:window.setInterval,windowClearInterval:window.clearInterval};
 let now=initial,id=0,intervals=0;const timers=new Map();
 const schedule=(fn,ms=0,args=[],repeat=0)=>{timers.set(++id,{fn,due:now+ms,args,repeat});return id};
 globalThis.setTimeout=window.setTimeout=(fn,ms,...args)=>schedule(fn,ms,args);
 globalThis.setInterval=window.setInterval=(fn,ms,...args)=>{intervals++;return schedule(fn,ms,args,ms)};
 globalThis.clearTimeout=globalThis.clearInterval=window.clearTimeout=window.clearInterval=id=>timers.delete(id);
 Date.now=()=>now;
 return {timers,get intervals(){return intervals},realTimeout:originals.setTimeout,async advance(ms){const end=now+ms;let runs=0;while(true){const next=[...timers].filter(([,t])=>t.due<=end).sort((a,b)=>a[1].due-b[1].due)[0];if(!next)break;if(++runs>10000)throw Error('Timer loop');const [key,t]=next;now=t.due;timers.delete(key);if(t.repeat)timers.set(key,{...t,due:now+t.repeat});await t.fn(...t.args)}now=end},restore(){Object.assign(globalThis,{setTimeout:originals.setTimeout,clearTimeout:originals.clearTimeout,setInterval:originals.setInterval,clearInterval:originals.clearInterval});Date.now=originals.now;Object.assign(window,{setTimeout:originals.windowTimeout,clearTimeout:originals.windowClear,setInterval:originals.windowInterval,clearInterval:originals.windowClearInterval})}};
}
