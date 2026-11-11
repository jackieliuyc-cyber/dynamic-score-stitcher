import {planPages} from './engine.js';
import {validCrop, videoProblem} from './input.js';
import {fileProblem, mediaBlob, mediaMessage, waitForMedia} from './media.js';
const $=id=>document.getElementById(id),show=(id,on=true)=>$(id).hidden=!on;
const video=$('video'),overlay=$('overlay'),scratch=document.createElement('canvas');
const capture=scratch.getContext('2d',{willReadFrequently:true});
let importController=null,mediaKind='local';
let source=null,objectURL=null,crop=[0,0,1,1],drag=null,running=false,paused=false,cancelled=false,loading=false,exporting=false,unsaved=false;
let worker=null,rpcId=0,requests=new Map(),wake=null,result=null,rows=[],chosen=new Set(),exports=[],previewURLs=[];
const stamp=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${Math.floor(t%60).toString().padStart(2,'0')}`;
function error(message){$('error').textContent=message;show('error');}
function notice(message){$('notice').textContent=message;show('notice',!!message);}
function lock(on){for(const id of ['file','file-other','demo','url','generate','reset','seek','title','start','end','quality','interval','crop-left','crop-top','crop-right','crop-bottom'])$(id).disabled=on;document.querySelector('#url-form button').disabled=on;}
function clearExports(){exports.forEach(p=>URL.revokeObjectURL(p.url));previewURLs.forEach(URL.revokeObjectURL);exports=[];previewURLs=[];}
async function seekTo(time){
  const t=Math.max(.001,Math.min(video.duration-.06,time));
  if(Math.abs(video.currentTime-t)>.015||video.readyState<2){
    await waitForMedia(video,{kind:mediaKind,signal:importController?.signal,timeoutMs:20000,
      start:()=>{video.currentTime=t;},
      condition:()=>!video.seeking&&video.readyState>=2&&Math.abs(video.currentTime-t)<.2});
  }
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
}
function releaseVideo(){
  video.pause();video.removeAttribute('src');video.load();
  if(objectURL)URL.revokeObjectURL(objectURL);objectURL=null;
}
async function loadVideo(url,title,kind){
  if(running||loading||exporting){if(kind==='local')URL.revokeObjectURL(url);return;}
  loading=true;importController=new AbortController();mediaKind=kind;lock(true);show('error',false);show('setup',false);show('import-panel');$('import-panel').insertBefore($('video-wrap'),$('import-status'));show('resume-import',false);$('import-status').textContent='正在读取 '+title;notice('正在确认视频能否解码…');
  try{
    clearExports();$('images').replaceChildren();$('rows').replaceChildren();show('result',false);result=null;rows=[];unsaved=false;
    releaseVideo();objectURL=kind==='local'?url:null;
    video.muted=true;video.playsInline=true;video.preload='auto';
    await waitForMedia(video,{kind,signal:importController.signal,
      start:()=>{if(kind==='local')video.removeAttribute('crossorigin');else video.crossOrigin='anonymous';video.src=url;video.load();},
      onWaiting:state=>{show('resume-import',state>=1);if(state>=1)$('import-status').textContent='已读到视频信息，正在等待画面。若停在这里，可点击继续读取。';}});
    video.pause();
    const problem=videoProblem(video.duration,video.videoWidth,video.videoHeight);if(problem)throw new Error(problem);
    source={title,kind};$('title').value=title;$('start').value=0;$('end').value=Math.floor(video.duration*10)/10;
    $('seek').max=Math.max(0,video.duration-.1);$('seek').value=0;$('time').textContent='00:00';
    $('video-meta').textContent=`${stamp(video.duration)} · ${video.videoWidth}×${video.videoHeight}`;
    crop=[0,0,1,1];overlay.width=video.videoWidth;overlay.height=video.videoHeight;
    show('setup');await seekTo(.02);drawCrop();notice('');
    $('setup').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){source=null;releaseVideo();show('setup',false);if(e.name==='AbortError'){notice(e.message);}else{notice('');error(e.message);}}
  finally{video.pause();$('setup').insertBefore($('video-wrap'),document.querySelector('.preview-controls'));importController=null;loading=false;show('import-panel',false);lock(false);}
}
async function importFile(file){
  if(!file||running||loading||exporting)return;
  show('error',false);const problem=fileProblem(file);if(problem)return error(problem);
  try{const url=URL.createObjectURL(mediaBlob(file));await loadVideo(url,(file.name||'我的乐谱').replace(/\.[^.]+$/,''),'local');}
  catch(e){error('无法读取所选文件。请先将云端原视频下载到手机，再从「文件」重新选择。');}
}
for(const id of ['file','file-other'])$(id).onchange=()=>{const file=$(id).files?.[0];$(id).value='';return importFile(file);};
$('cancel-import').onclick=()=>importController?.abort();
$('resume-import').onclick=()=>{
  if(!loading)return;
  video.muted=true;
  const attempt=video.play();
  attempt?.then(()=>{if(!loading)video.pause();}).catch(e=>{
    if(!loading)return;
    if(e.name==='NotAllowedError')notice('浏览器阻止了播放，请再点击「继续读取画面」，或使用 Safari / Chrome 打开网页。');
    else if(e.name==='NotSupportedError')error(mediaMessage(4,{kind:mediaKind}));
  });
};
$('demo').onclick=()=>loadVideo(new URL('./demo.mp4',location.href).href,'乐谱拼接练习 · 样例','demo');
$('url-form').onsubmit=e=>{e.preventDefault();let url;try{url=new URL($('url').value);}catch{return error('请输入有效的视频文件地址。');}if(!['https:','http:'].includes(url.protocol))return error('仅支持 HTTP(S) 视频直链。');if(/(^|\.)(bilibili\.com|b23\.tv|youtube\.com|youtu\.be)$/.test(url.hostname))return error('这是视频页面链接。纯浏览器版不能解析它，请先保存视频，再从手机相册或文件选择。');loadVideo(url.href,'我的乐谱','url');};
function drawCrop(){['crop-left','crop-top','crop-right','crop-bottom'].forEach((id,i)=>$(id).value=Math.round(crop[i]*1000)/10);const ctx=overlay.getContext('2d'),w=overlay.width,h=overlay.height;ctx.clearRect(0,0,w,h);const [l,t,r,b]=crop;ctx.fillStyle='rgba(20,40,25,.35)';ctx.beginPath();ctx.rect(0,0,w,h);ctx.rect(l*w,t*h,(r-l)*w,(b-t)*h);ctx.fill('evenodd');ctx.lineWidth=Math.max(2,w/350);ctx.strokeStyle='#80a93c';ctx.strokeRect(l*w+2,t*h+2,(r-l)*w-4,(b-t)*h-4);}
function point(e){const rect=overlay.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(e.clientY-rect.top)/rect.height))];}
overlay.onpointerdown=e=>{if(running||loading)return;drag=point(e);overlay.setPointerCapture(e.pointerId);};
overlay.onpointermove=e=>{if(!drag||running||loading)return;const [x,y]=point(e);crop=[Math.min(x,drag[0]),Math.min(y,drag[1]),Math.max(x,drag[0]),Math.max(y,drag[1])];drawCrop();};
overlay.onpointerup=()=>{drag=null;if(crop[2]-crop[0]<.2||crop[3]-crop[1]<.12){crop=[0,0,1,1];drawCrop();notice('区域过小，已恢复全画面。请完整框住谱面。');}};
overlay.onpointercancel=()=>{drag=null;};
for(const id of ['crop-left','crop-top','crop-right','crop-bottom'])$(id).onchange=()=>{const next=['crop-left','crop-top','crop-right','crop-bottom'].map(id=>Number($(id).value)/100);if(validCrop(next)){crop=next;show('error',false);drawCrop();}else{error('边界无效：左要小于右，上要小于下，谱面区域不能过小。');drawCrop();}};
for(const platform of ['ios','android'])$(platform+'-guide-tab').onclick=()=>{for(const type of ['ios','android']){$(type+'-guide-tab').setAttribute('aria-selected',String(platform===type));show(type+'-guide-panel',platform===type);}};
$('reset').onclick=()=>{crop=[0,0,1,1];drawCrop();notice('');};
$('seek').oninput=()=>{$('time').textContent=stamp(Number($('seek').value));};
$('seek').onchange=async()=>{if(running)return;try{await seekTo(Number($('seek').value));}catch(e){error(e.message);}};
function rpc(type,payload={},transfer=[]){const id=++rpcId;return new Promise((resolve,reject)=>{requests.set(id,{resolve,reject});worker.postMessage({type,id,...payload},transfer);});}
function createWorker(){try{worker=new Worker(new URL('./worker.js',import.meta.url),{type:'module'});}catch{throw new Error('浏览器无法启动图像处理。请用 Safari / Chrome 通过网页地址打开，或刷新后重试。');}worker.onmessage=({data})=>{const call=requests.get(data.id);if(!call)return;requests.delete(data.id);data.error?call.reject(new Error(data.error)):call.resolve(data);};worker.onerror=()=>{for(const call of requests.values())call.reject(new Error('图像分析模块加载失败。请刷新页面后重试，或换用 Safari / Chrome。'));requests.clear();};}
async function acquireWake(){try{if(navigator.wakeLock&&document.visibilityState==='visible')wake=await navigator.wakeLock.request('screen');}catch{/* Screen lock support is optional. */}}
async function releaseWake(){try{await wake?.release();}catch{}wake=null;}
function setPaused(value){paused=value;$('pause').textContent=value?'继续处理':'暂停';$('progress-title').textContent=value?'已暂停':'正在寻找谱行';if(value)releaseWake();else acquireWake();}
$('pause').onclick=()=>{if(running)setPaused(!paused);};
$('cancel').onclick=()=>{cancelled=true;paused=false;$('progress-title').textContent='正在取消…';};
document.addEventListener('visibilitychange',()=>{if(running&&document.visibilityState==='hidden'){setPaused(true);notice('离开页面后已暂停。返回后点击「继续处理」。');}});
async function waitIfPaused(){while(paused&&!cancelled)await new Promise(r=>setTimeout(r,150));if(cancelled)throw new Error('已取消处理。可以调整范围后重新生成。');}
$('generate').onclick=async()=>{
  if(!source||running||exporting)return;
  const start=Number($('start').value),end=Number($('end').value),interval=Number($('interval').value);
  if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>video.duration+.05)return error('请设置视频长度以内的有效时间范围。');
  if((end-start)/interval>1200)return error('采样画面过多，请选择每 1 秒，或缩短时间范围。');
  show('error',false);show('result',false);notice('');clearExports();running=true;cancelled=false;paused=false;lock(true);show('processing');$('pause').textContent='暂停';$('progress-title').textContent='正在寻找谱行';$('progress').value=0;$('percent').textContent='0%';$('processing').scrollIntoView({behavior:'smooth',block:'center'});
  $('processing').insertBefore($('video-wrap'),$('progress'));
  $('processing').scrollIntoView({behavior:'smooth',block:'center'});
  video.pause();
  try{
    createWorker();await acquireWake();
    await rpc('reset');
    const [l,t,r,b]=crop,srcW=(r-l)*video.videoWidth,srcH=(b-t)*video.videoHeight;
    const scale=Math.min(1,Number($('quality').value)/srcW,900/srcH);
    scratch.width=Math.round(srcW*scale);scratch.height=Math.round(srcH*scale);
    for(let time=start;time<end-.04;time+=interval){
      await waitIfPaused();await seekTo(time);await waitIfPaused();
      capture.drawImage(video,l*video.videoWidth,t*video.videoHeight,srcW,srcH,0,0,scratch.width,scratch.height);
      let pixels;try{pixels=capture.getImageData(0,0,scratch.width,scratch.height);}catch{throw new Error('这个视频直链不允许浏览器读取画面。请下载视频后，从本地选择。');}
      const reply=await rpc('frame',{buffer:pixels.data.buffer,width:scratch.width,height:scratch.height,time},[pixels.data.buffer]);
      const percent=Math.min(96,Math.round((time-start+interval)/(end-start)*96));$('progress').value=percent;$('percent').textContent=`${percent}%`;
      $('progress-text').textContent=`${stamp(time)} / ${stamp(end)} · ${reply.summary.frames} 帧`;$('row-count').textContent=`${reply.summary.rows} 行`;
      $('seek').value=time;$('time').textContent=stamp(time);
    }
    await waitIfPaused();$('progress-title').textContent='正在排列谱行';result=(await rpc('finish')).result;rows=result.rows;chosen=new Set(rows.map(r=>r.id));
    await buildImages();unsaved=true;show('processing',false);show('result');$('result').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){error(e.message||'处理失败，请尝试缩短视频或降低输出宽度。');show('processing',false);}
  finally{$('setup').insertBefore($('video-wrap'),document.querySelector('.preview-controls'));running=false;lock(false);worker?.terminate();worker=null;requests.clear();await releaseWake();scratch.width=1;scratch.height=1;}
};
function canvasFor(row){const canvas=document.createElement('canvas');canvas.width=row.width;canvas.height=row.height;const ctx=canvas.getContext('2d');const image=ctx.createImageData(row.width,row.height);for(let i=0;i<row.pixels.length;i++){const v=row.pixels[i],p=i*4;image.data[p]=v;image.data[p+1]=v;image.data[p+2]=v;image.data[p+3]=255;}ctx.putImageData(image,0,0);return canvas;}
function toBlob(canvas){return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('图片导出失败。请降低输出宽度或缩短视频。')),'image/png'));}
async function buildImages(){
  clearExports();const picked=rows.filter(r=>chosen.has(r.id));if(!picked.length)throw new Error('请至少保留一行乐谱。');
  const width=picked[0].width,withHeader=result.header?[{...result.header,id:0},...picked]:picked,pages=planPages(withHeader,width);
  const title=($('title').value||source.title||'完整乐谱').trim();
  const images=$('images');images.replaceChildren();
  for(let i=0;i<pages.length;i++){
    const page=pages[i],canvas=document.createElement('canvas');canvas.width=width+40;canvas.height=150+page.reduce((sum,r)=>sum+r.height+16,0);
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#23372a';ctx.font=`600 ${Math.max(18,width/34)}px -apple-system, sans-serif`;
    let caption=title;while(ctx.measureText(caption).width>width&&caption.length>4)caption=caption.slice(0,-2)+'…';ctx.fillText(caption,20,42);
    ctx.fillStyle='#7e897a';ctx.font=`${Math.max(11,width/80)}px -apple-system, sans-serif`;ctx.fillText(`动态乐谱拼接工具 · 浏览器内处理 · ${i+1} / ${pages.length}`,20,70);
    let y=94;for(const row of page){const rc=canvasFor(row);ctx.drawImage(rc,20,y);rc.width=rc.height=1;y+=row.height+16;}
    ctx.fillText('原视频逐行截图 · 请核对小节衔接',20,canvas.height-20);
    const blob=await toBlob(canvas),url=URL.createObjectURL(blob),name=`${title.replace(/[\\/:*?"<>|]/g,'-')}${pages.length>1?'-'+(i+1):''}.png`;
    exports.push({blob,url,name,width:canvas.width,height:canvas.height});canvas.width=canvas.height=1;
    const card=document.createElement('div');card.className='image-card';const info=document.createElement('div');info.className='caption';const text=document.createElement('span');text.textContent=`第 ${i+1} 张 · ${exports.at(-1).width} × ${exports.at(-1).height}`;
    const save=document.createElement('a');save.textContent='保存此图';save.href=url;save.download=name;save.className='download';info.append(text,save);
    const anchor=document.createElement('a');anchor.href=url;anchor.target='_blank';anchor.rel='noopener';const image=document.createElement('img');image.src=url;image.alt=`完整乐谱第 ${i+1} 张`;image.loading='lazy';anchor.append(image);card.append(info,anchor);images.append(card);
  }
  $('result-meta').textContent=`${picked.length} 行谱面 · ${exports.length===1?'完整长图':exports.length+' 张分图'} · 视频未上传`;
  $('save').textContent=exports.length===1?'保存图片 ↓':'查看分图并保存 ↓';
  const messages=[...result.warnings];if(exports.length>1)messages.push('为适应手机内存，长谱已自动分图。可以分别保存。');
  $('warnings').textContent=messages.join(' ');show('warnings',messages.length>0);switchTab('preview');
  const shareFiles=exports.map(p=>new File([p.blob],p.name,{type:'image/png'}));$('share').disabled=!(navigator.canShare&&navigator.canShare({files:shareFiles}));
}
$('save').onclick=()=>{if(exports.length===1){const a=document.createElement('a');a.href=exports[0].url;a.download=exports[0].name;document.body.append(a);a.click();a.remove();notice('若没有自动保存，请点开原图，长按保存到相册或文件。');}else{$('images').scrollIntoView({behavior:'smooth',block:'start'});notice('请使用每张图片上方的「保存此图」。');}};
$('share').onclick=async()=>{try{await navigator.share({files:exports.map(p=>new File([p.blob],p.name,{type:'image/png'}))});}catch(e){if(e.name!=='AbortError')error('分享不可用，请使用「保存图片」或长按原图。');}};
function switchTab(view){show('images',view==='preview');show('rows-view',view==='rows');$('preview-tab').classList.toggle('selected',view==='preview');$('rows-tab').classList.toggle('selected',view==='rows');}
$('preview-tab').onclick=()=>switchTab('preview');$('rows-tab').onclick=async()=>{switchTab('rows');try{await renderRows();}catch(e){error(e.message);}};
async function renderRows(){
  const list=$('rows');list.replaceChildren();previewURLs.forEach(URL.revokeObjectURL);previewURLs=[];
  for(let index=0;index<rows.length;index++){
    const row=rows[index],card=document.createElement('div');card.className='row-card'+(chosen.has(row.id)?'':' excluded');
    const head=document.createElement('div');head.className='row-head';const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=chosen.has(row.id);check.onchange=()=>{check.checked?chosen.add(row.id):chosen.delete(row.id);card.classList.toggle('excluded',!check.checked);countSelection();};label.append(check,document.createTextNode(`第 ${index+1} 行 · ${stamp(row.time)}`));head.append(label);
    for(const direction of [-1,1]){const b=document.createElement('button');b.textContent=direction<0?'↑':'↓';b.setAttribute('aria-label',`第${index+1}行${direction<0?'上':'下'}移`);b.disabled=index+direction<0||index+direction>=rows.length;b.onclick=()=>{[rows[index],rows[index+direction]]=[rows[index+direction],rows[index]];renderRows().catch(e=>error(e.message));};head.append(b);}
    const canvas=canvasFor(row),blob=await toBlob(canvas),url=URL.createObjectURL(blob);canvas.width=canvas.height=1;previewURLs.push(url);const image=document.createElement('img');image.src=url;image.alt=`第 ${index+1} 行`;image.loading='lazy';card.append(head,image);list.append(card);
  }countSelection();
}
function countSelection(){$('selection-count').textContent=`保留 ${chosen.size} / ${rows.length} 行`;$('rebuild').disabled=chosen.size===0;}
$('rebuild').onclick=async()=>{if(exporting||running)return;exporting=true;lock(true);$('rebuild').disabled=true;try{await buildImages();$('result').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){error(e.message);}finally{exporting=false;lock(false);$('rebuild').disabled=false;}};
$('again').onclick=()=>{$('setup').scrollIntoView({behavior:'smooth',block:'start'});notice('可以修改时间、清晰度或框选区域，再重新生成。');};
window.addEventListener('beforeunload',event=>{if(running||exporting||unsaved){event.preventDefault();event.returnValue='';}});
window.addEventListener('pagehide',()=>{if(running){cancelled=true;worker?.terminate();}releaseWake();});
