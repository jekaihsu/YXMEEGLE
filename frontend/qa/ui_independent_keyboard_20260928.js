async page=>{
 const checks={}; await page.goto('http://127.0.0.1:8794/#view=project&project=p1&node=p1-control&tab=flow'); await page.locator('.task-table').waitFor();
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.setViewportSize({width:390,height:900});
 await page.evaluate(()=>document.documentElement.style.fontSize='200%');
 checks.pageNoOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
 checks.taskCardFits=await page.locator('.task-table').evaluate(el=>el.getBoundingClientRect().width<innerWidth);
 checks.taskTitleReadable=await page.locator('.task-title>div').first().evaluate(el=>el.getBoundingClientRect().width>=150);
 await page.getByRole('button',{name:'控制點平差計算',exact:true}).focus();
 await page.keyboard.press('Enter');
 const dialog=page.getByRole('dialog').last();await dialog.waitFor();
 checks.taskKeyboardOpens=await dialog.isVisible();
 checks.dialogNoOverflow=await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1);
 checks.dialogReducedMotion=await dialog.evaluate(el=>getComputedStyle(el).animationName==='none'&&getComputedStyle(el).transitionDuration==='0s');
 await page.screenshot({path:'output/playwright/independent-cross-task-200percent-20260928.png',animations:'disabled'});
 for(let i=0;i<18;i++)await page.keyboard.press('Tab');
 checks.focusStayedInDialog=await dialog.evaluate(el=>el.contains(document.activeElement));
 await page.keyboard.press('Escape');
 checks.escapeCloses=await page.getByRole('dialog').count()===0;
 checks.focusReturned=await page.getByRole('button',{name:'控制點平差計算',exact:true}).evaluate(el=>el===document.activeElement);
 await page.getByRole('button',{name:'開啟導覽',exact:true}).click();
 checks.mobileMenuOpens=await page.getByRole('dialog',{name:'工作區導覽'}).isVisible();
 await page.keyboard.press('Shift+Tab');
 checks.menuTrapsFocus=await page.getByRole('dialog',{name:'工作區導覽'}).evaluate(el=>el.contains(document.activeElement));
 await page.keyboard.press('Escape');
 checks.menuEscape=await page.getByRole('dialog').count()===0;
 return {evidence:'independent local demo browser, no mutations or API fixtures',checks};
}

