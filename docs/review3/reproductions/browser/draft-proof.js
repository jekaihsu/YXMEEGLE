async (page) => {
  await page.goto('http://127.0.0.1:8794/?mode=draft');
  const a=page.locator('[data-record="RECORD_A"]');
  const b=page.locator('[data-record="RECORD_B"]');
  await a.locator('summary').click();
  await a.locator('input').fill('A_PRIVATE_DRAFT');
  await b.locator('summary').click();
  await b.locator('input').fill('B_DIFFERENT_DRAFT');
  const keys=await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.includes(':form:')).map(k=>({key:k,value:JSON.parse(sessionStorage.getItem(k))})));
  await page.getByRole('button',{name:'Toggle forms'}).click();
  await page.getByRole('button',{name:'Toggle forms'}).click();
  await a.locator('summary').click();
  await a.getByRole('button',{name:'恢復暫存文字'}).click();
  const restored=await a.locator('input').inputValue();
  if(restored!=='B_DIFFERENT_DRAFT')throw Error('collision not reproduced '+restored);
  await a.getByRole('button',{name:'儲存',exact:true}).click();
  await page.screenshot({path:'output/playwright/review3-draft-collision.png',fullPage:true});
  return {proof:'DraftForm cross-record collision',keys,restored,submitted:await page.evaluate(()=>window.review3.submitted)};
}
