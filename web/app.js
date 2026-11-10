'use strict';
const $ = id => document.getElementById(id);
let current = null, timer = null, crop = [0, 0, 1, 1], previewImage = null;
let dragStart = null, rowOrder = [], selected = new Set(), resultView = 'long';
const busyStates = new Set(['queued', 'preparing', 'uploading', 'processing']);
const show = (id, visible = true) => { $(id).hidden = !visible; };
const stamp = seconds => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
const fileUrl = (name, refresh = false) => `/files/${current.id}/${name}${refresh ? `?v=${Date.now()}` : ''}`;
function fail(message) { $('error').textContent = message; show('error'); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Score-Tool': '1'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请重试。');
  return data;
}
function lockSources(busy) {
  $('read-button').disabled = busy;
  $('file').disabled = busy;
}
function tab(source) {
  $('link-tab').setAttribute('aria-selected', String(source === 'link'));
  $('upload-tab').setAttribute('aria-selected', String(source === 'upload'));
  show('link-form', source === 'link'); show('upload-panel', source === 'upload');
}
$('link-tab').onclick = () => tab('link');
$('upload-tab').onclick = () => tab('upload');
$('link-form').onsubmit = async event => {
  event.preventDefault(); show('error', false); lockSources(true);
  try { await activate(await api('/api/link', {url: $('url').value.trim()})); }
  catch (error) { fail(error.message); lockSources(false); }
};
async function upload(file) {
  if (!file || $('file').disabled) return;
  if (file.size > 1024 ** 3) return fail('视频超过 1 GB，请先裁剪或压缩。');
  show('error', false); lockSources(true); show('empty', false); show('setup', false); show('result', false);
  show('status-panel'); $('status-title').textContent = '接收本地视频'; $('status-message').textContent = '文件仅传到本机工具';
  $('progress').value = 0; $('percent').textContent = '0%'; show('cancel', false);
  try {
    const data = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/upload?name=${encodeURIComponent(file.name)}`);
      xhr.setRequestHeader('X-Score-Tool', '1');
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = e => { if(e.lengthComputable) { const n = Math.round(e.loaded/e.total*100); $('progress').value=n; $('percent').textContent=`${n}%`; } };
      xhr.onload = () => { try { const d = JSON.parse(xhr.responseText); xhr.status < 300 ? resolve(d) : reject(new Error(d.error)); } catch { reject(new Error('上传未完成，请重试。')); } };
      xhr.onerror = () => reject(new Error('连接中断，请确认工具仍在运行。'));
      xhr.send(file);
    });
    await activate(data);
  } catch (error) { fail(error.message); lockSources(false); show('status-panel', false); }
  finally { show('cancel'); $('file').value = ''; }
}
$('file').onchange = e => upload(e.target.files[0]);
const drop = $('dropzone');
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files[0]); };
async function activate(job) {
  clearTimeout(timer); current = job; crop = [0,0,1,1]; show('empty', false); show('error', false);
  show('setup', false); show('result', false); renderState();
  if (busyStates.has(job.state)) poll();
  else if (job.state === 'done') renderResult();
  else if (job.state === 'ready') await renderSetup();
}
function renderState() {
  const busy = busyStates.has(current.state);
  lockSources(busy); show('status-panel', busy); show('cancel', busy);
  if (busy) {
    $('status-title').textContent = current.state === 'processing' ? '正在提取并拼接谱行' : '准备视频';
    $('status-message').textContent = current.message; $('progress').value = current.progress;
    $('percent').textContent = `${current.progress}%`;
  }
}
async function poll() {
  try {
    current = await api(`/api/jobs/${current.id}`); renderState();
    if (busyStates.has(current.state)) timer = setTimeout(poll, 850);
    else if (current.state === 'ready') await renderSetup();
    else if (current.state === 'done') { renderResult(); loadRecent(); }
    else { fail(current.message); if(current.video) await renderSetup(); }
  } catch (error) { lockSources(false); fail('无法连接本地工具，请确认启动窗口仍在运行。'); }
}
$('cancel').onclick = async () => {
  if (!current) return;
  try { await api(`/api/jobs/${current.id}/cancel`, {}); $('status-message').textContent = '正在取消…'; }
  catch(error) { fail(error.message); }
};
async function loadPreview() {
  const img = new Image();
  await new Promise((resolve,reject) => { img.onload=resolve; img.onerror=()=>reject(new Error('预览加载失败，请重新查看这一帧。')); img.src=fileUrl('preview.jpg',true); });
  previewImage=img; $('crop-canvas').width=img.naturalWidth; $('crop-canvas').height=img.naturalHeight; drawCrop();
}
async function renderSetup() {
  show('setup'); show('result',false); show('status-panel',false);
  $('title-input').value=current.title;
  $('resolution').textContent=`${current.video.width} × ${current.video.height} · ${stamp(current.video.duration)}`;
  $('end').value=current.video.duration.toFixed(1); $('start').value=0;
  $('preview-time').max=Math.max(0,Math.floor(current.video.duration)-1); $('preview-time').value=0;
  $('preview-time-label').textContent='00:00'; syncCropFields();
  $('process').disabled=false;
  await loadPreview();
}
function syncCropFields() {
  ['crop-left','crop-top','crop-right','crop-bottom'].forEach((id,i)=>$(id).value=Math.round(crop[i]*1000)/10);
}
function drawCrop() {
  if (!previewImage) return;
  const canvas=$('crop-canvas'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);ctx.drawImage(previewImage,0,0,w,h);
  const [x,y,r,b]=crop;ctx.fillStyle='rgba(15,35,23,.37)';ctx.beginPath();ctx.rect(0,0,w,h);ctx.rect(x*w,y*h,(r-x)*w,(b-y)*h);ctx.fill('evenodd');
  ctx.strokeStyle='#80ad36';ctx.lineWidth=Math.max(2,w/450);ctx.strokeRect(x*w+1,y*h+1,(r-x)*w-2,(b-y)*h-2);
}
const canvas=$('crop-canvas');
function point(e) { const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]; }
canvas.onpointerdown=e=>{dragStart=point(e);canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!dragStart)return;const p=point(e);crop=[Math.min(p[0],dragStart[0]),Math.min(p[1],dragStart[1]),Math.max(p[0],dragStart[0]),Math.max(p[1],dragStart[1])];syncCropFields();drawCrop();};
canvas.onpointerup=e=>{if(!dragStart)return;dragStart=null;if(crop[2]-crop[0]<.15||crop[3]-crop[1]<.1)crop=[0,0,1,1];syncCropFields();drawCrop();};
canvas.onpointercancel=()=>{dragStart=null;};
['crop-left','crop-top','crop-right','crop-bottom'].forEach(id=>$(id).onchange=()=>{
  const c=['crop-left','crop-top','crop-right','crop-bottom'].map(id=>Number($(id).value)/100);
  if(c.every(n=>Number.isFinite(n)&&n>=0&&n<=1)&&c[0]<c[2]&&c[1]<c[3]){crop=c;drawCrop();}
  else{fail('区域边界无效：左应小于右，上应小于下。');syncCropFields();}
});
$('reset-crop').onclick=()=>{crop=[0,0,1,1];syncCropFields();drawCrop();};
$('preview-time').oninput=()=>{$('preview-time-label').textContent=stamp(Number($('preview-time').value));};
$('refresh-preview').onclick=async()=>{
  $('refresh-preview').disabled=true;
  try{await api(`/api/jobs/${current.id}/preview`,{at:Number($('preview-time').value)});await loadPreview();}
  catch(error){fail(error.message);}finally{$('refresh-preview').disabled=false;}
};
$('process').onclick=async()=>{
  show('error',false);$('process').disabled=true;
  const options={title:$('title-input').value,crop,start:Number($('start').value),end:Number($('end').value),interval:Number($('interval').value)};
  if(options.start<0||options.start>=options.end||options.end>current.video.duration+.05){$('process').disabled=false;return fail('请填写视频范围内有效的开始和结束时间。');}
  try{current=await api(`/api/jobs/${current.id}/process`,options);show('setup',false);show('result',false);renderState();poll();}
  catch(error){fail(error.message);$('process').disabled=false;}
};
function renderResult() {
  show('setup',false);show('result');show('status-panel',false);show('error',false);lockSources(false);
  const result=current.result;
  rowOrder=result.rows.map(r=>r.id);selected=new Set(result.selected||rowOrder);
  // Retain the user's custom order and show excluded rows after the selection.
  if(result.selected)rowOrder=[...result.selected,...rowOrder.filter(id=>!selected.has(id))];
  $('result-meta').textContent=`${selected.size} 行谱面 · ${result.output_size.join(' × ')} px · PNG 无损图片`;
  $('download').href=fileUrl('score.png',true);$('download').download=`${result.title.replace(/[\\/:*?"<>|]/g,'-')}-完整乐谱.png`;
  $('full-image').href=fileUrl('score.png',true);$('score-image').src=fileUrl('thumbnail.png',true);
  const warnings=result.warnings||[];show('warnings',warnings.length>0);$('warnings').textContent=warnings.join(' ');
  resultView='long';setResultView('long');renderRows();
}
function setResultView(view){resultView=view;$('long-tab').setAttribute('aria-selected',String(view==='long'));$('rows-tab').setAttribute('aria-selected',String(view==='rows'));show('long-view',view==='long');show('rows-view',view==='rows');}
$('long-tab').onclick=()=>setResultView('long');$('rows-tab').onclick=()=>setResultView('rows');
$('reprocess').onclick=()=>{show('error',false);renderSetup().catch(error=>fail(error.message));};
function renderRows() {
  const container=$('row-list');container.replaceChildren();
  const byId=new Map(current.result.rows.map(r=>[r.id,r]));
  rowOrder.forEach((id,index)=>{
    const row=byId.get(id),card=document.createElement('div');card.className=`row-card${selected.has(id)?'':' excluded'}`;
    const controls=document.createElement('div');controls.className='row-controls';
    const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=selected.has(id);
    checkbox.onchange=()=>{checkbox.checked?selected.add(id):selected.delete(id);card.classList.toggle('excluded',!checkbox.checked);updateCount();};
    label.append(checkbox,document.createTextNode(`第 ${index+1} 行 · 原视频 ${stamp(row.time)}`));controls.append(label);
    [-1,1].forEach(direction=>{const button=document.createElement('button');button.textContent=direction<0?'↑':'↓';button.setAttribute('aria-label',`将第 ${index+1} 行${direction<0?'上':'下'}移`);button.disabled=index+direction<0||index+direction>=rowOrder.length;button.onclick=()=>{[rowOrder[index],rowOrder[index+direction]]=[rowOrder[index+direction],rowOrder[index]];renderRows();};controls.append(button);});
    const image=document.createElement('img');image.loading='lazy';image.src=fileUrl(row.file);image.alt=`第 ${index+1} 行乐谱`;
    card.append(controls,image);container.append(card);
  });updateCount();
}
function updateCount(){$('selected-count').textContent=`保留 ${selected.size} / ${rowOrder.length} 行`;$('rebuild').disabled=selected.size===0;}
$('rebuild').onclick=async()=>{
  $('rebuild').disabled=true;show('error',false);
  try{current=await api(`/api/jobs/${current.id}/compose`,{rows:rowOrder.filter(id=>selected.has(id))});renderResult();$('result').scrollIntoView({behavior:'smooth',block:'start'});}
  catch(error){fail(error.message);}finally{$('rebuild').disabled=false;}
};
async function loadRecent(){
  try{const {jobs}=await api('/api/jobs');const done=jobs.filter(j=>j.state==='done');show('recent-section',done.length>0);$('recent-list').replaceChildren();done.slice(0,8).forEach(job=>{const b=document.createElement('button');b.textContent=job.title;b.title=job.title;b.onclick=()=>{if(current&&busyStates.has(current.state))return fail('请等待当前任务完成，或先取消。');activate(job).catch(error=>fail(error.message));};$('recent-list').append(b);});}
  catch{/* No history is required to start a new task. */}
}
loadRecent();
