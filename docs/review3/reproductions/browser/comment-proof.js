async(page)=>{
 await page.goto('http://127.0.0.1:8794/?mode=comment#view=project&project=pA&node=nA&tab=flow');
 await page.getByRole('textbox',{name:'新增評論',exact:true}).fill('PRIVATE_A_COMMENT');
 await page.evaluate(()=>{location.hash='view=project&project=pB&node=nB&tab=flow'});
 await page.getByRole('heading',{name:'CASE_B',exact:true}).waitFor();
 const carried=await page.getByRole('textbox',{name:'新增評論',exact:true}).inputValue();
 await page.getByRole('button',{name:'送出',exact:true}).click();
 const submitted=await page.evaluate(()=>window.review3.commentSubmitted);
 if(carried!=='PRIVATE_A_COMMENT'||submitted.project_id!=='pB')throw Error('not reproduced');
 return {proof:'additional impact of known #41 draft identity bug',carried,submitted};
}
