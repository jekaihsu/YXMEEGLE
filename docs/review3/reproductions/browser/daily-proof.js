async(page)=>{
 await page.goto('http://127.0.0.1:8794/?mode=daily-status');
 await page.locator('.daily-cards article').first().waitFor();
 const statuses=await page.locator('.daily-cards article').allInnerTexts();
 if(statuses.length!==3||!statuses.every(s=>s.includes('原日報檢核待查證')))throw Error('status mismatch not reproduced');
 await page.goto('http://127.0.0.1:8794/?mode=daily-paging');
 await page.getByRole('status').filter({hasText:'61'}).waitFor();
 await page.getByRole('button',{name:'下一頁',exact:true}).click();
 await page.getByRole('status').filter({hasText:'第 2'}).waitFor();
 await page.getByRole('button',{name:'下一頁',exact:true}).click();
 await page.getByRole('status').filter({hasText:'第 3'}).waitFor();
 await page.getByRole('button',{name:'Switch to B daily'}).click();
 await page.getByRole('status').filter({hasText:'共 1 筆'}).waitFor();
 const paging={project:await page.locator('h1').innerText(),status:await page.getByRole('status').innerText(),cards:await page.locator('.daily-cards article').count(),previousDisabled:await page.getByRole('button',{name:'上一頁',exact:true}).isDisabled(),nextDisabled:await page.getByRole('button',{name:'下一頁',exact:true}).isDisabled()};
 if(paging.cards!==0||!paging.previousDisabled||!paging.nextDisabled)throw Error('paging not reproduced '+JSON.stringify(paging));
 return {statusContractProof:statuses,pagingProof:paging};
}
