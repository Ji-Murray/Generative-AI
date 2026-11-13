import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const root='/Users/murrayji/generative ai';
const build=path.join(root,'.codex-pptx-4min/build');
const source=path.join(root,'docs/LectureQA_CityU_中文版_Keynote兼容版.pptx');
const skill='/Users/murrayji/.codex/plugins/cache/openai-primary-runtime/presentations/26.1112.11217/skills/presentations';
const runtime='/Users/murrayji/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {finalizePresentation}=await import(path.join(skill,'container_tools/artifact_tool_utils.mjs'));
const p=await PresentationFile.importPptx(await FileBlob.load(source));
const originalIndices=[0,1,2,3,8,15,18];
const initialRecords=(await p.inspect({kind:'table,chart',maxChars:200000})).ndjson.trim().split('\n').map(l=>JSON.parse(l));
p.slides.keep(originalIndices);
const C={ink:'#242839',magenta:'#A71955',muted:'#687181',light:'#F5F2F5'};
const font='Hiragino Sans GB';
function text(s,name,value,x,y,w,h,size=27,color=C.ink,bold=false){
 const t=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:font,fontSize:size,color,bold,insets:0,autoFit:'none',verticalAlignment:'top',wrap:'square'};return t;
}
function frame(s,num,title,active){
 for(const a of [...s.shapes.items]) if(!['3','4','5','6','7','8','9','10'].includes(a.id)) a.delete();
 for(const a of [...s.images.items]) if(a.id!=='2') a.delete();
 const owned=initialRecords.filter(r=>r.slideIndex===originalIndices[num-1] && ['table','chart'].includes(r.kind)).map(r=>r.id);
 if(owned.length) p.delete(owned);
 const labels=['项目背景','核心方法','产品展示','评估结果','团队交付'];
 for(let j=0;j<5;j++){
 const t=s.shapes.items.find(t=>t.id===String(j+3));
 t.text=labels[j];t.fill=j===active?C.magenta:'none';
 t.text.style={typeface:font,fontSize:19,bold:j===active,color:j===active?'#FFFFFF':C.muted,insets:{left:10,top:4,right:4,bottom:0}};
 }
 const titleShape=s.shapes.items.find(t=>t.id==='8');titleShape.text=title;
 titleShape.text.style={typeface:font,fontSize:38,color:C.ink,bold:true,insets:0};
 s.shapes.items.find(t=>t.id==='10').text=String(num).padStart(2,'0');
}
function table(s,name,values,x,y,w,h,widths,size=25){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
 t.name=name;t.borders.assign({fill:'#DDD8DF',width:0.7,style:'solid'});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({textStyle:{typeface:font,fontSize:size,color:C.ink},margins:{left:16,right:12,top:10,bottom:8},anchor:'center'});
 for(let r=0;r<values.length;r++){
  t.rows[r].height=h/values.length;
  for(let c=0;c<values[0].length;c++){
   const cell=t.getCell(r,c);cell.fill=r===0?C.magenta:(r%2? '#FFFFFF':C.light);
   cell.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':C.ink,bold:r===0};
  }
 }
 return t;
}
function notes(s,timing,speaker,body,refs){s.speakerNotes.text=`建议用时：${timing}秒。建议讲者：${speaker}。\n\n${body}\n\n资料依据：\n${refs.join('\n')}`;}
const slides=p.slides.items;
// 1. Preserve the original cover artwork and typography.
const cover=slides[0];
cover.shapes.items.find(x=>x.id==='4').text='面向课程复习的\n来源感知学习助手';
cover.shapes.items.find(x=>x.id==='5').text='课程问答、页码核对与可溯源自测';
cover.shapes.items.find(x=>x.id==='6').text='DSC6021 Generative AI  /  Final Project';
notes(cover,15,'成员1','大家好，我们的项目是 LectureQA，面向按课程讲义复习的学生。它支持课程问答和自测，并保留页码出处，让学生能够回到讲义核对答案。',[source,path.join(root,'README.md')]);
// 2. Problem and novelty.
frame(slides[1],2,'项目定位与创新点',0);
text(slides[1],'audience','目标用户：需要查讲义、理解概念和考前自测的学生',60,198,1150,45,28,C.magenta,true);
text(slides[1],'pain-title','复习中的问题',60,280,490,42,30,C.ink,true);
text(slides[1],'pain','答案是否超出课程范围？\n知识点来自讲义哪一页？\n材料没覆盖时能否明确说明？',60,345,535,166,28);
text(slides[1],'novel-title','本项目的设计贡献',650,280,570,42,30,C.magenta,true);
text(slides[1],'novel','按页保留检索证据与引用\n证据不足时拒答，生成后再校验\n把问答和可溯源练习接入复习流程',650,345,570,166,28);
text(slides[1],'novel-limit','创新集中在来源约束与产品整合。当前没有通用模型优越性或学习收益的对照实证。',60,584,1150,65,23,C.muted);
notes(slides[1],40,'成员1','复习时，学生除了理解答案，还需要确认内容是否在课程范围内，以及出处在哪一页。我们把这两个需求放进同一个流程。设计贡献主要是按页保留证据，在生成前判断材料是否充分，生成后校验引用，再把这些能力用于自测和复习。项目采用现有模型，创新集中在来源约束与产品整合，目前还没有学习收益或优于通用聊天工具的对照实证。',[path.join(root,'docs/REPORT.md'),path.join(root,'src/lectureqa/service.py')]);
// 3. Reuse a recorded screenshot of the current four-lecture deployment.
frame(slides[2],3,'产品展示：回答旁边保留讲义出处',2);
const bytes=await fs.readFile('/private/tmp/live_lecture_only_covered.png');
slides[2].images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:'image/png',alt:'2026年11月13日公开网站自动测试截图：ICL问答与页码出处',fit:'contain',position:{left:52,top:190,width:810,height:430}});
text(slides[2],'demo-title','一次课程问答',900,200,310,43,28,C.magenta,true);
text(slides[2],'demo-body','提问：什么是 ICL？\n\n回答显示讲义页码，\n支持对照原文。\n\n另含单讲学习、\n练习与错题功能。',900,267,320,290,25);
text(slides[2],'demo-caption','2026-11-13 公开网站实测截图，当前部署含4份讲义。此例展示界面行为，未逐条核验答案。',60,630,1150,30,19,C.muted);
notes(slides[2],35,'成员2','这里是公开网站的一次实际交互截图。我们问什么是上下文学习，系统给出解释，并显示讲义页码，右侧提供课件预览。用户可以在回答和原文之间核对，减少手工翻找。产品还提供单讲学习、练习与错题。这张截图只说明交互与来源展示确实出现，不能单独证明答案完全正确。为控制四分钟时间，这里使用已有截图。',[path.join(root,'eval/AUTOMATED_SITE_TEST.md'),'/private/tmp/live_lecture_only_covered.png',path.join(root,'app/streamlit_app.py')]);
// 4. Plain editable text in the existing template.
frame(slides[3],4,'核心方法：证据与生成的约束',1);
const method=[['01  按页检索','PDF按页抽取并分块，保留文档ID与页码。\n结合语义检索和BM25，重排后选择证据。'],['02  证据门控','先判断证据是否足够，普通问答不足时拒答。'],['03  引用校验','生成后只保留本次证据中的引用。\nQuiz采用结构化输出并过滤无出处题目。']];
method.forEach(([a,b],i)=>{const y=205+i*131;text(slides[3],`method-heading-${i}`,a,60,y,290,43,29,C.magenta,true);text(slides[3],`method-body-${i}`,b,375,y,840,90,27);});
text(slides[3],'method-boundary','引用校验检查出处是否合法，尚不能证明每个论断都得到原文支持。',60,625,1150,33,22,C.muted);
notes(slides[3],35,'成员2','系统先按页抽取PDF并分块，保留文档和页码。检索结合语义相似和关键词匹配，再选择证据。普通问答在证据不足时拒答，生成后检查引用是否属于本次证据集合。练习题也采用结构化输出并过滤无出处题目。这里有一个边界：页码合法不等于语义正确，所以后续仍需检查答案是否真正得到原文支持。',[path.join(root,'docs/REPORT.md'),path.join(root,'src/lectureqa/retrieval/retriever.py'),path.join(root,'src/lectureqa/generation/citations.py')]);
// 5. Evidence and interpretation.
frame(slides[4],5,'评估：证据定位改善，仍有误拒答',3);
text(slides[4],'eval-scope','离线72题：62道可答、10道不可答，检索 k = 6',60,193,1150,42,27,C.magenta,true);
table(slides[4],'offline-evaluation',[
 ['指标','BM25','混合检索 + coverage'],['hit@6','0.677','0.919'],['引用精度','0.505','0.676'],['拒答准确率','0.653','0.847']
],52,256,780,267,[250,180,350],25);
text(slides[4],'eval-hit','+24.2 个百分点',875,253,345,55,33,C.magenta,true);
text(slides[4],'eval-hit-label','hit@6 相对BM25的变化',875,313,345,40,22,C.muted);
text(slides[4],'refusal','10 / 10',875,380,330,52,35,C.ink,true);
text(slides[4],'refusal-label','不可答题正确拒答\n但62道可答题中误拒答11道',875,440,340,85,23);
text(slides[4],'other-evidence','工程测试：91项通过。网站自动测试：10次均返回，等待中位数12.4秒。',60,552,1150,40,24);
text(slides[4],'eval-limits','离线数据含3份自制示例材料，沿用已存报告，与当前网站语料不同。\n引用精度按标准页匹配统计，未完成真人用户研究。',60,605,1150,57,20,C.muted);
notes(slides[4],55,'成员3','我们从离线效果、工程测试和网站交互三个层面验证。已保存的离线评估共七十二题，其中六十二题可答。主配置的前六条检索命中率从零点六七七提高到零点九一九，提升二十四点二个百分点，引用精度也提高。十道不可答题都正确拒答，但十一道可答题也被拒答，说明系统仍偏保守。工程方面，九十一项测试通过。网站十次自动交互均返回，等待中位数十二点四秒。离线语料含三份自制示例材料，与当前部署不同。自动测试不代表真人使用体验，我们尚未完成真人用户研究。',[path.join(root,'eval/reports/SUITE_RESULTS.md'),path.join(root,'docs/REPORT.md'),path.join(root,'eval/automated_site_test_results.csv'),path.join(root,'tests')]);
// 6. Explicitly unconfirmed names and contribution mapping.
frame(slides[5],6,'交付成果与团队分工',4);
text(slides[5],'deliverables','交付成果：LectureQA产品、源代码与技术报告',60,190,1150,43,28,C.magenta,true);
text(slides[5],'team-warning','成员姓名和实际贡献尚未提供，下表为待确认分工',60,248,1150,34,23,C.muted);
table(slides[5],'team-contribution',[
 ['成员','负责部分（待确认）','对应产物'],
 ['成员1：姓名待填','PDF解析、分块与检索','数据导入、混合检索'],
 ['成员2：姓名待填','问答提示、引用与练习','生成、校验与Quiz'],
 ['成员3：姓名待填','界面与系统集成','Streamlit、预览与服务'],
 ['成员4：姓名待填','评估与技术报告','测试集、实验与报告']
],52,306,1170,270,[260,465,445],25);
text(slides[5],'effort','投入证据：完整处理管线、3种配置比较、91项工程测试、10次网站交互。',60,605,1150,42,23);
notes(slides[5],40,'成员4','项目交付包括可运行的LectureQA产品、源代码和技术报告。团队投入覆盖数据处理、检索生成、界面集成和评估。具体分工由本页列出，每位成员负责的模块和对应产物一一对应。我们还完成了三种配置比较、九十一项工程测试以及十次网站自动交互。\n\n排练前必须将四处姓名待填替换为真实姓名，并按实际贡献调整职责。当前表格为建议映射，不能当作已核实分工。四位成员均需按课程要求出席最后两次课。',[path.join(root,'docs/PRESENTATION.md'),path.join(root,'docs/CHECKLIST.md'),path.join(root,'README.md')]);
// 7. Close on value and a concrete limit.
frame(slides[6],7,'结论与下一步',4);
text(slides[6],'conclusion','LectureQA 将课程回答与讲义出处放在一起',60,215,1150,75,37,C.magenta,true);
text(slides[6],'conclusion-body','检索结果支持更准确的证据定位。\n页码核对与自测服务课程复习流程。',60,329,1150,110,31);
text(slides[6],'next-step','下一步：减少可答题误拒答，招募真实学生完成复习任务测试。',60,490,1150,90,29);
const link=text(slides[6],'product-link','在线产品：点击打开 LectureQA',60,610,680,40,23,C.magenta,true);
link.hyperlink={uri:'https://generative-ai-edb2vsczy5zdjprebcdn8p.streamlit.app/',isExternal:true};
notes(slides[6],15,'成员4','LectureQA把课程回答和可核对的讲义出处放在一起。下一步，我们将降低误拒答，并邀请真实学生完成复习任务，验证实际帮助。谢谢。',['https://generative-ai-edb2vsczy5zdjprebcdn8p.streamlit.app/',path.join(root,'docs/USER_STUDY.md')]);
await fs.writeFile(path.join(build,'slides.ndjson'),(await p.inspect({kind:'slide,textbox,table,notes',maxChars:200000})).ndjson);
const candidate=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({
 workspaceDir:root,candidatePath:candidate,
 finalPath:path.join(root,'docs/4分钟答辩版/LectureQA_CityU_中文版_4分钟精简版.pptx'),
 pythonExecutable:path.join(runtime,'python/bin/python3'),
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','5','--require-native-table-slide','6'],
 requiredNativeTableOwnerSlides:[5,6],
 fontPolicy:{basis:'reference',families:[font],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')
});
console.log(JSON.stringify(result,null,2));
for(let i=0;i<slides.length;i++){
 const png=await slides[i].export({format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
