import test from 'node:test';
import assert from 'node:assert/strict';
import {fileProblem,mediaBlob,mediaMessage,waitForMedia} from '../dist/media.js';
class FakeVideo extends EventTarget {
 constructor(){super();this.readyState=0;this.error=null;this.seeking=false;this.listeners=0;}
 addEventListener(...args){this.listeners++;super.addEventListener(...args);}
 removeEventListener(...args){this.listeners--;super.removeEventListener(...args);}
 emit(name){this.dispatchEvent(new Event(name));}
}
test('iPhone MOV and Android empty or generic MIME reach native decoding',()=>{
 for(const file of [{name:'IMG_1234.MOV',type:'video/quicktime',size:200},{name:'recording.mp4',type:'',size:200},{name:'12345',type:'application/octet-stream',size:200},{name:'clip.webm',type:'video/webm',size:200},{name:'clip.avi',type:'video/x-msvideo',size:200}])assert.equal(fileProblem(file),'');
});
test('empty, oversized and clearly non-video files have specific guidance',()=>{
 assert.match(fileProblem({size:0}),/下载/);
 assert.match(fileProblem({size:701*1024**2}),/700 MB/);
 for(const [name,type] of [['photo.HEIC',''],['track','audio/mp4'],['report.pdf','application/pdf']])assert.match(fileProblem({name,type,size:100}),/不是视频/);
});
test('generic document-provider MIME gets only a container hint; explicit types stay unchanged',()=>{
 const f=new File(['data'],'clip.MOV',{type:'application/octet-stream'});const b=mediaBlob(f);
 assert.equal(b.type,'video/quicktime');assert.equal(b.size,f.size);
 const typed=new File(['data'],'clip.mov',{type:'video/quicktime'});assert.equal(mediaBlob(typed),typed);
 const unknown=new File(['data'],'no-extension');assert.equal(mediaBlob(unknown),unknown);
});
test('unsupported and corrupt media errors distinguish codec, read and abort causes',()=>{
 assert.match(mediaMessage(4),/格式或编码/);assert.match(mediaMessage(4),/H\.264/);
 assert.match(mediaMessage(3),/解码失败/);assert.match(mediaMessage(3),/损坏/);
 assert.match(mediaMessage(2),/本地/);assert.doesNotMatch(mediaMessage(2),/跨域/);
 assert.match(mediaMessage(2,{kind:'url'}),/跨域/);
 assert.match(mediaMessage(1),/中止/);
 assert.match(mediaMessage(null,{timeout:true}),/无法判断是否为格式/);
});
test('canplay alone can finish import without loadeddata',async()=>{
 const video=new FakeVideo();const promise=waitForMedia(video,{start:()=>{video.readyState=2;video.emit('canplay');},timeoutMs:100});
 await promise;assert.equal(video.listeners,0);
});
test('readiness polling handles mobile suppression of loadeddata',async()=>{
 const video=new FakeVideo();const promise=waitForMedia(video,{timeoutMs:100,pollMs:2});
 video.readyState=2;await promise;assert.equal(video.listeners,0);
});
test('metadata alone never passes as a decoded frame; manual playback can finish',async()=>{
 const video=new FakeVideo();let waiting=0,finished=false;
 const promise=waitForMedia(video,{onWaiting:state=>waiting=state,timeoutMs:100,pollMs:2}).then(()=>finished=true);
 video.readyState=1;video.emit('loadedmetadata');await new Promise(r=>setTimeout(r,5));assert.equal(waiting,1);assert.equal(finished,false);
 video.readyState=2;video.emit('loadeddata');await promise;assert.equal(video.listeners,0);
});
test('decode failure cleans listeners and permits retry on the same element',async()=>{
 const video=new FakeVideo();let pending=waitForMedia(video,{timeoutMs:100});video.error={code:3};video.emit('error');await assert.rejects(pending,/解码失败/);assert.equal(video.listeners,0);
 video.error=null;pending=waitForMedia(video,{start:()=>{video.readyState=2;video.emit('canplay');}});await pending;assert.equal(video.listeners,0);
});
test('cancel and timeout always release listeners and timers',async()=>{
 const video=new FakeVideo(),controller=new AbortController();const pending=waitForMedia(video,{signal:controller.signal,timeoutMs:100});controller.abort();await assert.rejects(pending,{name:'AbortError'});assert.equal(video.listeners,0);
 await assert.rejects(waitForMedia(video,{timeoutMs:5,pollMs:2}),/读取视频超时/);assert.equal(video.listeners,0);
});
