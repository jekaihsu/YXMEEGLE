async (page) => {
 const cloud=page.context().pages().find(p=>p.url().startsWith('https://yongxiang-projects-20260925.zeabur.app/'));
 if (!cloud) throw new Error('Authorized cloud application tab unavailable');
 return await cloud.evaluate(async()=>{
  return await Promise.all(['/api/workspace','/api/sources'].map(async path=>{
   const started=performance.now();
   try {
    const response=await fetch(path,{credentials:'same-origin',signal:AbortSignal.timeout(60000)});
    const data=await response.json();
    const entry=performance.getEntriesByName(location.origin+path).at(-1);
    return {path,status:response.status,encoding:response.headers.get('content-encoding'),milliseconds:Math.round(performance.now()-started),transfer_bytes:entry?.transferSize,decoded_bytes:entry?.decodedBodySize,...(path==='/api/workspace'?{projects:data.projects?.length}:{source_status:data.status,tables:data.tables?.length,records:data.records?.length,mapping:data.mapping})};
   }catch(error){return {path,error:error.name,milliseconds:Math.round(performance.now()-started)}}
  }));
 });
}