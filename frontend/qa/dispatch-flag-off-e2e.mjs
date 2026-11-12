import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.DISPATCH_PLAYWRIGHT_MODULE??'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.DISPATCH_CHROME??'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:1280,height:900}});
const base=process.env.DISPATCH_FLAG_OFF_URL??'http://localhost:5200';
try{
 await page.goto(`${base}/api/dev/login?as=pm&next=${encodeURIComponent('/#view=dispatch&tab=work')}`);
 await page.getByRole('heading',{name:'派工看板尚未開放',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'新增排班',exact:true}).count(),0);
 assert.equal(await page.locator('.dp-page').count(),0);
 const session=await(await page.request.get(`${base}/api/session`)).json();assert.notEqual(session.features.dispatch_write,true);assert.notEqual(session.features.dispatch_board,true);
 assert.equal((await page.request.get(`${base}/api/v2/dispatch/work`)).status(),404);
 for(const width of [1280,390]){await page.setViewportSize({width,height:width===390?844:900});await page.screenshot({path:new URL(`../../output/dispatch-publish-e2e/real-flag-off-${width}.png`,import.meta.url).pathname})}
 await fs.writeFile(new URL('../../output/dispatch-publish-e2e/real-flag-off.json',import.meta.url),JSON.stringify({features:session.features,workStatus:404,assignmentButtons:0},null,2));
 console.log('Real flag-off app hides dispatch navigation, work queue and assignment controls; API route is 404.');
}finally{await browser.close()}
