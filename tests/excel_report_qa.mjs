// Visual QA through the bundled Artifact Tool public API, not app dependencies.
import fs from 'node:fs/promises';
import path from 'node:path';
const {FileBlob,SpreadsheetFile}=globalThis.artifactAPI;
const root=process.cwd();
const input=path.join(root,'reports/Excel模块对照/三路反激_Vinmin_Vinmax_模块设计报告.xlsx');
const out=path.join(root,'_tmp_excel_report_qa');
const workbook=await SpreadsheetFile.importXlsx(await FileBlob.load(input));
workbook.recalculate();
const sheetInfo=(await workbook.inspect({kind:'sheet',include:'id,name',maxChars:6000})).ndjson;
console.log(sheetInfo);
const records=sheetInfo.split('\n').filter(Boolean).map(line=>JSON.parse(line)).filter(item=>item.kind==='sheet');
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',
    options:{useRegex:true,maxResults:20},maxChars:1500})).ndjson);
const summary=await workbook.inspect({kind:'region',sheetId:workbook.worksheets.getItemAt(0).name,
    range:'A4:Q10',maxChars:1500,tableMaxRows:7,tableMaxCols:17});
console.log(summary.ndjson);
await fs.mkdir(out,{recursive:true});
// Every module's initial table and the following graph areas are reviewed.
const names=['01 需求与工况总览','02 拓扑与多路输出','03 功率级与开关波形','04 功率器件与损耗',
    '05 电容纹波','06 磁件与绕制','07 环路与补偿电路','08 钳位与复位','09 损耗与效率',
    '11 模型与评审','12 输入参数快照'];
for(let index=0;index<names.length;index++){
    const sheet=workbook.worksheets.getItem(names[index]);
    const lastRow=Number(records[index].range.match(/\d+$/)[0]);
    const limit=process.argv.includes('--full') ? lastRow : 35;
    for(let row=1;row<=limit;row+=35){
        const image=await workbook.render({sheetName:sheet.name,range:`A${row}:Q${Math.min(row+34,limit)}`,scale:1,format:'png'});
        await fs.writeFile(path.join(out,`module-${index+1}-${row}.png`),new Uint8Array(await image.arrayBuffer()));
    }
    console.log(`Rendered ${sheet.name}`);
}
