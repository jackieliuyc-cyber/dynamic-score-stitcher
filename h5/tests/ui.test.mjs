import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {planPages} from '../dist/engine.js';
import {validCrop,videoProblem} from '../dist/input.js';
import {fileProblem,mediaBlob,mediaMessage,waitForMedia} from '../dist/media.js';
const html=fs.readFileSync(new URL('../dist/index.html',import.meta.url),'utf8');
const script=fs.readFileSync(new URL('../dist/app.js',import.meta.url),'utf8').replace(/^import .*;$/gm,'').replaceAll('import.meta.url',JSON.stringify(new URL('../dist/app.js',import.meta.url).href));
function setup(){
 const nodes=new Map();
 function node(){const listeners=new Map();return {value:'',disabled:false,hidden:false,style:{},attrs:{},getContext:()=>({clearRect(){},beginPath(){},rect(){},fill(){},strokeRect(){}}),classList:{toggle(){}},setAttribute(key,value){this.attrs[key]=value;},addEventListener(name,fn){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},removeEventListener(name,fn){listeners.get(name)?.delete(fn);},emit(name){for(const fn of [...(listeners.get(name)||[])])fn();},removeAttribute(name){delete this[name];},load(){this.readyState=0;this.error=null;if(this.src){queueMicrotask(()=>{if(this.mode==='reject'){this.error={code:4};this.emit('error');}else if(this.mode==='wait'){this.readyState=1;this.emit('loadedmetadata');}else{this.readyState=2;this.emit('canplay');}});}},scrollIntoView(){},insertBefore(){},replaceChildren(){},pause(){}};}
 for(const match of html.matchAll(/id="([^"]+)"/g))nodes.set(match[1],node());
 Object.assign(nodes.get('video'),{duration:24,videoWidth:1280,videoHeight:720,currentTime:0,readyState:0});
 const sandbox={fileProblem,mediaBlob,mediaMessage,waitForMedia,AbortController,planPages,validCrop,videoProblem,URL,Map,Set,Number,Math,Promise,console,setTimeout,clearTimeout,requestAnimationFrame:callback=>setTimeout(callback,0),
  document:{getElementById:id=>{assert.ok(nodes.has(id),'Unknown DOM id '+id);return nodes.get(id);},createElement:()=>node(),querySelector:()=>node(),addEventListener(){},visibilityState:'visible'},
  navigator:{},window:{addEventListener(){}},Worker:class{constructor(){throw new Error('worker unavailable');}}};
 const context=vm.createContext(sandbox);vm.runInContext(script,context);
 return {nodes,context};
}
test('phone guide switches and exact crop updates match real page controls',()=>{
 const {nodes,context}=setup();
 nodes.get('android-guide-tab').onclick();
 assert.equal(nodes.get('android-guide-panel').hidden,false);
 assert.equal(nodes.get('ios-guide-panel').hidden,true);
 assert.equal(nodes.get('android-guide-tab').attrs['aria-selected'],'true');
 for(const [id,value] of [['crop-left',80],['crop-top',0],['crop-right',20],['crop-bottom',100]])nodes.get(id).value=value;
 nodes.get('crop-left').onchange();
 assert.match(nodes.get('error').textContent,/边界无效/);
 assert.deepEqual(Array.from(vm.runInContext('crop',context)),[0,0,1,1]);
});
test('worker initialization failure releases controls so a new attempt is possible',async()=>{
 const {nodes,context}=setup();
 nodes.get('start').value=0;nodes.get('end').value=24;nodes.get('interval').value=1;
 vm.runInContext("source={title:'test',kind:'local'}",context);
 await nodes.get('generate').onclick();
 assert.equal(nodes.get('file').disabled,false);
 assert.equal(nodes.get('generate').disabled,false);
 assert.equal(nodes.get('processing').hidden,true);
 assert.equal(vm.runInContext('running',context),false);
 assert.match(nodes.get('error').textContent,/无法启动图像处理/);
});

test('unsupported local import unlocks both pickers, then the same file can be selected again',async()=>{
 const {nodes,context}=setup();const file=new File(['video'],'IMG_1000.MOV',{type:'video/quicktime'});
 nodes.get('video').mode='reject';nodes.get('file').files=[file];nodes.get('file').value='chosen';
 await nodes.get('file').onchange();
 assert.equal(nodes.get('file').value,'');assert.equal(nodes.get('file').disabled,false);assert.equal(nodes.get('file-other').disabled,false);
 assert.equal(vm.runInContext('objectURL',context),null);assert.equal(nodes.get('setup').hidden,true);assert.match(nodes.get('error').textContent,/格式或编码/);
 nodes.get('video').mode='accept';nodes.get('file-other').files=[file];await nodes.get('file-other').onchange();
 assert.equal(nodes.get('setup').hidden,false);assert.equal(nodes.get('import-panel').hidden,true);assert.equal(vm.runInContext('source.kind',context),'local');
 vm.runInContext('releaseVideo()',context);
});
test('cancel reading clears local source and allows a new selection; dismissing picker preserves current source',async()=>{
 const {nodes,context}=setup();nodes.get('video').mode='wait';nodes.get('file').files=[new File(['x'],'clip.mp4')];
 const pending=nodes.get('file').onchange();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(nodes.get('file-other').disabled,true);nodes.get('cancel-import').onclick();await pending;
 assert.equal(nodes.get('file-other').disabled,false);assert.equal(nodes.get('import-panel').hidden,true);assert.equal(vm.runInContext('objectURL',context),null);
 vm.runInContext("source={title:'retained'}",context);nodes.get('file').files=[];await nodes.get('file').onchange();
 assert.equal(vm.runInContext('source.title',context),'retained');
});
