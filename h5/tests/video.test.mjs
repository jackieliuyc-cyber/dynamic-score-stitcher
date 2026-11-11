import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {ScoreEngine} from '../dist/engine.js';
const hasFFmpeg=spawnSync('ffmpeg',['-version'],{stdio:'ignore'}).status===0;
test('fresh encoded melody sample preserves all 12 rows in order at mobile width',{skip:!hasFFmpeg},async()=>{
 const source=fileURLToPath(new URL('../dist/demo.mp4',import.meta.url));
 const process=spawn('ffmpeg',['-v','error','-i',source,'-vf','fps=1,scale=960:540','-pix_fmt','rgba','-f','rawvideo','pipe:1']);
 let pending=Buffer.alloc(0),frames=0,error='';const engine=new ScoreEngine();
 const completion=new Promise((resolve,reject)=>{process.on('error',reject);process.on('close',code=>code===0?resolve():reject(new Error(error)));});
 process.stderr.on('data',chunk=>error+=chunk);
 for await(const chunk of process.stdout){
  pending=Buffer.concat([pending,chunk]);
  while(pending.length>=960*540*4){engine.add(pending.subarray(0,960*540*4),960,540,frames++);pending=pending.subarray(960*540*4);}
 }
 await completion;
 const result=engine.result();
 assert.equal(frames,24);assert.equal(result.rows.length,12);assert.equal(result.breaks,0);
 assert.deepEqual(result.rows.map(r=>r.position),result.rows.map(r=>r.position).sort((a,b)=>a-b));
 assert.ok(result.rows.every(r=>r.pixels.length===r.width*r.height));
});
