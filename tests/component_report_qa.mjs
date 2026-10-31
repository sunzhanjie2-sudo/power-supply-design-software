// Read-only visual QA of the application's XLSX output using bundled tooling.
import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const root=process.cwd();
const out=root+'/artifacts/qa/component-management';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(out+'/component-report-qa.xlsx'));
const info=await wb.inspect({kind:'sheet',include:'id,name',maxChars:2500});
console.log(info.ndjson);
const sheet=wb.worksheets.getItem('14 关键器件BOM与降额');
const cells=sheet.getUsedRange().values;
console.log((await wb.inspect({kind:'region',sheetId:sheet.name,range:'A4:Q12',maxChars:1800,tableMaxRows:9,tableMaxCols:17})).ndjson);
const headers=cells.map((row,i)=>[i+1,row]).filter(([,row])=>row.some(c=>String(c).includes('位号 / 检查项'))).map(([i])=>i);
console.log('Detail headers',headers);
for(const [label,start,end] of [['identity',1,28],['checks',headers[0]||45,(headers[0]||45)+22],['sources',headers[1]||110,(headers[1]||110)+15]]) {
 const picture=await wb.render({sheetName:sheet.name,range:`A${start}:Q${end}`,scale:1,format:'png'});
 await fs.writeFile(out+'/excel-bom-'+label+'.png',new Uint8Array(await picture.arrayBuffer()));
}
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
