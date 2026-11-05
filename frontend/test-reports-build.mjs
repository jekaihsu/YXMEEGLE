import {build} from 'vite';
import {gzipSync} from 'node:zlib';
const result=await build({build:{write:false,rollupOptions:{input:'src/reports/preview.html'}}});
for(const item of result.output||[])if(item.type==='chunk')console.log(`${item.fileName} ${(Buffer.byteLength(item.code)/1000).toFixed(2)} kB gzip ${(gzipSync(item.code).length/1000).toFixed(2)} kB`);
