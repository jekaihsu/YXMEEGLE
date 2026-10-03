async(page)=>{
 await page.goto('http://127.0.0.1:8794/?mode=app#view=project&project=pA&node=nA&task=tA&tab=flow');
 await page.getByRole('button',{name:'開始作業',exact:true}).click();
 await page.waitForFunction(()=>window.review3.actionPending);
 await page.getByRole('button',{name:'關閉任務',exact:true}).click();
 await page.evaluate(()=>window.review3.switchActor());
 await page.getByRole('button',{name:'重新整理資料',exact:true}).click();
 await page.locator('.user-button strong').filter({hasText:'ACTOR_B'}).waitFor();
 const before=await page.getByRole('heading',{name:'PRIVATE_CASE_A',exact:true}).count();
 await page.evaluate(()=>window.review3.releaseAction());
 await page.getByRole('heading',{name:'PRIVATE_CASE_A',exact:true}).waitFor();
 const result={proof:'old mutation accepted after session epoch change',actor:await page.locator('.user-button strong').innerText(),oldCaseHiddenBeforeRelease:before===0,oldCaseVisibleAfterRelease:await page.getByRole('heading',{name:'PRIVATE_CASE_A',exact:true}).innerText(),toast:await page.getByRole('status').last().innerText()};
 if(result.actor!=='ACTOR_B'||!result.oldCaseHiddenBeforeRelease)throw Error(JSON.stringify(result));
 await page.screenshot({path:'output/playwright/review3-session-race.png',fullPage:true});
 return result;
}
