// Real Edge, isolated profile: editable OR network, loads and report delivery.
const {chromium}=require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1025-760-0_26.1025.760.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const out=path.resolve('output/playwright/system-network');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1780,height:1150},acceptDownloads:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const snapshot=()=>page.evaluate(()=>window.PowerSystemWorkspace.snapshot());
 const node=(kind,id)=>page.locator(`[data-graph-node="${kind}:${id}"]`);
 const wire=async(kind,source,target)=>{await page.locator(`[data-port-output="${kind}:${source}"][data-output="1"]`).click();await page.locator(`[data-port-input="${target}"]`).click();};
 const settled=async text=>{await page.waitForFunction(s=>document.querySelector('.system-note')?.textContent.includes(s),text);await page.locator('.system-board svg').waitFor();};
 try{
  await page.goto(process.argv[2]||'http://127.0.0.1:8790');await page.waitForFunction(()=>window.PowerSystemWorkspace);
  await page.locator('input[type="file"]').setInputFiles(path.resolve('examples/SYSTEM_AUX_ORING.json'));await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().sources.length===2);await page.locator('.system-board svg').waitFor();
  let p=await snapshot();assert.equal(p.sources.length,2);assert.equal(p.junctions.length,1);assert.equal(p.loads.length,3);assert.equal(p.connections.length,6);
  assert.equal(await page.locator('[data-diode-symbol]').count(),2);
  await page.getByLabel('架构界面字号',{exact:true}).selectOption('18');
  assert.equal(await page.evaluate(()=>localStorage.getItem('power-system-font-size')),'18');
  await page.getByRole('button',{name:'增加负载',exact:true}).click();await page.waitForFunction(()=>window.PowerSystemWorkspace.snapshot().loads.length===4);await settled('架构已更新');
  await page.getByLabel('名称',{exact:true}).fill('隔离驱动与通信');await page.getByLabel('负载功耗 / W',{exact:true}).fill('1.5');
  assert.ok((await page.locator('.system-inspector-save').innerText()).includes('未保存'));
  assert.ok(await page.getByRole('button',{name:'保存节点修改',exact:true}).isVisible());
  await page.getByRole('button',{name:'保存节点修改',exact:true}).click();await settled('节点信息已保存');
  p=await snapshot();const load=p.loads.find(l=>l.name==='隔离驱动与通信');assert.ok(load);
  await wire('junction','OR-01',load.id);await settled('已新增供电连接');
  await wire('bus','BUS-02',load.id);await settled('已新增二极管 OR 分支');
  p=await snapshot();const edges=p.connections.filter(e=>e.target===load.id);assert.equal(edges.length,2);assert.ok(edges.every(e=>e.mode==='diode'));
  await page.locator(`[data-diode-drag="${edges[1].id}"]`).click();
  await page.getByLabel('二极管正向压降 Vf / V',{exact:true}).fill('0.6');await page.getByRole('button',{name:'保存支路修改',exact:true}).click();await settled('节点信息已保存');
  assert.equal((await snapshot()).connections.find(e=>e.id===edges[1].id).vf,.6);
  // Screen pixels are converted to world coordinates at every zoom level.
  let calculationRequests=0;page.on('request',r=>{if(/workspace\/validate|\/jobs/.test(r.url()))calculationRequests++;});
  const drag=async(locator,point={x:.4,y:.25})=>{
    await locator.scrollIntoViewIfNeeded();const b=await locator.boundingBox();
    const scale=await page.locator('.system-board svg').evaluate(el=>el.getBoundingClientRect().width/el.viewBox.baseVal.width);
    const x=b.x+b.width*point.x,y=b.y+b.height*point.y;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+42*scale,y+25*scale,{steps:10});await page.mouse.up();
  };
  const beforeCalc=calculationRequests;
  for(let z=0;z<2;z++){
    for(const [kind,id] of [['load',load.id],['junction','OR-01']]){
      const key=kind+':'+id,old=(await snapshot()).layout.nodes[key];
      await drag(node(kind,id).locator('rect').first());
      const moved=(await snapshot()).layout.nodes[key];assert.ok(Math.abs(moved.x-old.x-42)<1);assert.ok(Math.abs(moved.y-old.y-25)<1);
    }
    const diode=page.locator(`[data-diode-drag="${edges[1].id}"]`);
    await diode.scrollIntoViewIfNeeded();
    const old=await diode.evaluate(el=>({x:el.transform.baseVal.getItem(0).matrix.e,y:el.transform.baseVal.getItem(0).matrix.f}));
    await drag(diode,{x:.5,y:.5});const moved=(await snapshot()).layout.diodes[edges[1].id];
    assert.ok(Math.abs(moved.x-old.x-42)<1);assert.ok(Math.abs(moved.y-old.y-25)<1);
    await page.getByRole('button',{name:'放大画布',exact:true}).click();
  }
  assert.equal(calculationRequests,beforeCalc,'drag/zoom must not recalculate the power network');
  const layoutBefore=JSON.stringify((await snapshot()).layout);
  const board=page.locator('.system-board');await board.evaluate(el=>{el.scrollLeft=200;el.scrollTop=100;});
  const bb=await board.boundingBox();await page.mouse.move(bb.x+bb.width-30,bb.y+bb.height-45);await page.mouse.down();await page.mouse.move(bb.x+bb.width-90,bb.y+bb.height-80,{steps:8});await page.mouse.up();
  assert.equal(JSON.stringify((await snapshot()).layout),layoutBefore,'canvas pan must not move nodes');
  await page.getByRole('button',{name:'适应画布',exact:true}).click();
  // Delete just one competing source, then undo restores original fan-in.
  await page.locator('[data-node-delete="bus:BUS-02"]').click();await settled('节点已删除');assert.equal((await snapshot()).connections.filter(e=>e.target==='OR-01').length,1);
  await page.getByRole('button',{name:'撤销删除',exact:true}).click();await settled('已撤销删除');assert.equal((await snapshot()).connections.filter(e=>e.target==='OR-01').length,2);
  // Dropping the main source changes the evaluated supply routes.
  await node('bus','BUS-01').locator('rect').first().click({position:{x:100,y:50}});
  await page.getByLabel('节点状态',{exact:true}).selectOption({label:'停用 / 掉电'});await page.getByRole('button',{name:'保存节点修改',exact:true}).click();await settled('节点信息已保存');
  assert.equal((await snapshot()).sources.find(s=>s.id==='BUS-01').enabled,false);
  assert.ok((await page.getByLabel('供电工况').textContent()).includes('全部输入源'));
  const dl=page.waitForEvent('download');await page.getByRole('button',{name:'保存系统工程',exact:true}).click();await (await dl).saveAs(path.join(out,'可编辑多源辅源工程.json'));
  p=await snapshot();await page.reload();await page.waitForSelector('.system-board svg');assert.deepEqual(await snapshot(),p);
  assert.equal(await page.getByLabel('架构界面字号',{exact:true}).inputValue(),'18');
  await page.screenshot({path:path.join(out,'network.png'),fullPage:true});
  if(process.env.NETWORK_REPORT_QA==='1'){
    const dl=page.waitForEvent('download',{timeout:180000});
    const failed=page.locator('.system-error').waitFor({state:'visible',timeout:180000}).then(async()=>{throw Error(await page.locator('.system-error').innerText());});
    await page.getByRole('button',{name:'生成系统报告包',exact:true}).click();
    const report=await Promise.race([dl,failed]);await report.saveAs(path.join(out,'多源辅源报告.zip'));
  }
  assert.deepEqual(errors,[]);console.log('PASS network UI: named load, fan-out/fan-in, per-edge Vf, drag, partial delete/undo, source outage, save/reload'+(process.env.NETWORK_REPORT_QA?' and actual reports':''));
 }catch(e){console.error('STATE',await page.locator('.system-error').allTextContents(),errors);await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
