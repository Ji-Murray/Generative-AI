import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('/Users/murrayji/generative ai/docs/LectureQA_CityU_中文版_Keynote兼容版.pptx'));
await fs.writeFile('/Users/murrayji/generative ai/.codex-pptx-4min/build/inspection.ndjson',(await p.inspect({kind:'slide,textbox,shape,image,table,chart,layout',maxChars:500000})).ndjson);
console.log('SLIDES',p.slides.items.length,'SIZE',p.slides.items[0].size);
for (const i of [0,1,2,3,8,15]) {
 const s=p.slides.items[i];
 console.log('SLIDE',i+1, 'SHAPES',s.shapes.items.map(x=>({id:x.id,name:x.name,text:x.text?.toString(),pos:x.position})), 'IMAGES',s.images.items.map(x=>({id:x.id,position:x.position})), 'TABLES',s.tables.items.length);
}
await fs.writeFile('/Users/murrayji/generative ai/.codex-pptx-4min/build/source-slide-2.png',new Uint8Array(await (await p.slides.items[1].export({format:'png',scale:1})).arrayBuffer()));
