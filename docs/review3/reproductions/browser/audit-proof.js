async(page)=>{
 await page.goto('http://127.0.0.1:8794/?mode=audit');
 await page.getByText('PRIVATE_AUDIT_A',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Switch to B audit'}).click();
 await page.getByText('synthetic B failed',{exact:true}).waitFor();
 const stale=await page.getByText('PRIVATE_AUDIT_A',{exact:true}).count();
 if(stale!==1)throw Error('old audit not reproduced');
 await page.screenshot({path:'output/playwright/review3-audit-stale.png',fullPage:true});
 return {proof:'AuditTrail stale record under different project',currentProject:await page.locator('h1').innerText(),error:await page.getByRole('alert').innerText(),visibleOldRecord:await page.locator('article').innerText()};
}
