// Real browser acceptance using the same Playwright harness as PCS QA.
const {chromium}=require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1025-760-0_26.1025.760.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const out=path.resolve('output/playwright/system-workspace');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1680,height:1100},acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.argv[2]||'http://127.0.0.1:8789');
  await page.waitForFunction(()=>window.PowerSystemWorkspace?.snapshot()?.units.length===1);
  const snapshot=()=>page.evaluate(()=>window.PowerSystemWorkspace.snapshot());
  const card=id=>page.locator(`[data-graph-node="unit:${id}"]`);
  assert.equal(await page.locator('.application').count(),0);
  await page.getByRole('button',{name:'增加电源模块',exact:true}).click();
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units.length===2);
  await page.locator('[data-port-output="bus:BUS-01"][data-output="1"]').click();
  await page.locator('[data-port-input="PSU-02"]').click();
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().connections.some(e=>e.target==='PSU-02'&&e.source.kind==='bus'));
  // Change the upstream voltage and copy the range into the second converter.
  await page.locator('[data-graph-node="bus:BUS-01"]').locator('rect').first().click({position:{x:90,y:50}});
  await page.getByLabel('最小电压 / V',{exact:true}).fill('20');
  await page.getByRole('button',{name:'保存节点修改',exact:true}).click();
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().sources[0].min===20);
  await card('PSU-02').locator('rect').first().click({position:{x:90,y:50}});
  await page.getByRole('button',{name:'沿用上游电压',exact:true}).click();
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units[1].spec.V_in_min===20);
  await page.waitForFunction(()=>document.querySelector('.system-note')?.textContent.includes('输入范围已更新'));
  await page.locator('.system-board svg').waitFor();
  const rect=card('PSU-02').locator('rect').first();await rect.scrollIntoViewIfNeeded();
  const box=await rect.boundingBox(),before=(await snapshot()).layout.nodes['unit:PSU-02'];
  await page.mouse.move(box.x+90,box.y+50);await page.mouse.down();await page.mouse.move(box.x+175,box.y+80,{steps:10});await page.mouse.up();
  assert.equal((await snapshot()).layout.nodes['unit:PSU-02'].x,before.x+85);
  await page.locator('[data-node-open="PSU-01"]').click();
  await page.waitForSelector('.application');
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units[0].spec.P_out===40);
  await page.getByRole('button',{name:'← 返回系统架构',exact:true}).click();
  await page.waitForSelector('.system-board svg');
  // Verify independent configs via importing a full project with a Buck child.
  let p=await snapshot();
  const raw=JSON.parse(fs.readFileSync('examples/24W_BUCK_VM_TPS40200.json','utf8'));
  p.units[1].spec=raw;p.units[1].name='24W Buck';
  await page.locator('input[type=file]').setInputFiles({name:'系统工程.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(p))});
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units[1].spec.topology==='BUCK');
  await page.locator('[data-node-open="PSU-02"]').click();
  await page.waitForSelector('.application');
  await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units[1].spec.P_out===24);
  await page.getByRole('button',{name:'← 返回系统架构',exact:true}).click();await page.waitForSelector('.system-board svg');
  assert.equal((await snapshot()).units[0].spec.P_out,40);
  await page.locator('[data-node-delete="unit:PSU-02"]').click();await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units.length===1);
  await page.getByRole('button',{name:'撤销删除',exact:true}).click();await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().units.length===2);
  const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'保存系统工程',exact:true}).click();
  const saved=await downloading;await saved.saveAs(path.join(out,'系统工程.json'));
  p=await snapshot();await page.reload();await page.waitForSelector('.system-board svg');assert.deepEqual(await snapshot(),p);
  await page.screenshot({path:path.join(out,'architecture.png'),fullPage:true});
  if(process.env.SYSTEM_REPORT_QA==='1'){
    const dl=page.waitForEvent('download',{timeout:240000});await page.getByRole('button',{name:'生成系统报告包',exact:true}).click();
    const report=await dl;await report.saveAs(path.join(out,'系统报告包.zip'));
  }
  assert.deepEqual(errors,[]);console.log('PASS startup diagram, wire, drag, voltage sync, independent full calculators, delete/undo, save/reload'+(process.env.SYSTEM_REPORT_QA?' and system report':''));
 }catch(e){console.error('BROWSER STATE',await page.locator('.system-error').allTextContents(),errors);await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
