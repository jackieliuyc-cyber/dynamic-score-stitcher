import test from 'node:test';import assert from 'node:assert/strict';
import {ScoreEngine,detectStaves,estimateScroll,planPages} from '../dist/engine.js';
function paper(rows=8){const w=640,h=1200,a=new Uint8Array(w*h).fill(250);for(let r=0;r<rows;r++){const y=130+r*110;for(let k=0;k<5;k++)for(let x=20;x<620;x++)a[(y+k*6)*w+x]=60;for(let x=45;x<610;x+=40){for(let yy=y-17;yy<y+20;yy++)a[yy*w+x]=0;for(let yy=y+15;yy<y+20;yy++)for(let xx=x-4;xx<x+2;xx++)a[yy*w+xx]=0;}for(let yy=y-20;yy<y-13;yy++)for(let x=20;x<24+r;x++)a[yy*w+x]=0;}return {a,w,h};}
function rgba(gray){const a=new Uint8ClampedArray(gray.length*4);for(let i=0;i<gray.length;i++){a[i*4]=a[i*4+1]=a[i*4+2]=gray[i];a[i*4+3]=255;}return a;}
test('five-line systems and complete margins',()=>{const {a,w}=paper();const rows=detectStaves(a.slice(0,w*450),w,450).filter(s=>s.complete);assert.equal(rows.length,3);assert.equal(rows[0].gap,6);});
test('repeated grooves align to the actual forward scroll',()=>{const {a,w}=paper();const x=a.slice(0,w*450),y=a.slice(w*65,w*515);assert.equal(estimateScroll(x,y,w,450,detectStaves(x,w,450),detectStaves(y,w,450)),65);});
test('full stream retains all eight repeated score rows',()=>{const {a,w}=paper(),e=new ScoreEngine();for(let offset=0;offset<=660;offset+=55){const frame=rgba(a.slice(offset*w,(offset+450)*w));e.add(frame,w,450,offset/55);}const r=e.result();assert.equal(r.rows.length,8);assert.equal(r.breaks,0);assert.ok(r.rows.every(row=>row.pixels.length===row.width*row.height));});
test('no notation gives an actionable error',()=>{const e=new ScoreEngine();e.add(rgba(new Uint8Array(640*450).fill(255)),640,450,0);assert.throws(()=>e.result(),/五线谱/);});
test('long scores split within mobile canvas budget',()=>{const rows=Array.from({length:100},(_,i)=>({id:i,height:120,width:960}));const pages=planPages(rows,960);assert.ok(pages.length>1);assert.deepEqual(pages.flat(),rows);for(const p of pages){const h=150+p.reduce((n,r)=>n+r.height+16,0);assert.ok(h<=7800);assert.ok(h*1000<=6500000);}});

test('short meter-change row and final bar survive alongside full-width staves',()=>{
 const w=960,h=540,a=new Uint8Array(w*h).fill(250),ys=[100,240,380];
 for(let index=0;index<ys.length;index++){
  const right=index===0?930:500;
  for(let line=0;line<5;line++)for(let x=25;x<right;x++)a[(ys[index]+line*7)*w+x]=55;
  // A distinct stem in each row prevents an accidental identical-row assertion.
  for(let y=ys[index]-20;y<ys[index]+20;y++)a[y*w+100+index*30]=0;
 }
 const staves=detectStaves(a,w,h).filter(row=>row.complete);assert.deepEqual(staves.map(row=>row.y),ys);
 const engine=new ScoreEngine();engine.add(rgba(a),w,h,0);engine.add(rgba(a),w,h,1);
 const result=engine.result();assert.equal(result.rows.length,3);assert.deepEqual(result.rows.map(row=>row.position),ys);
 assert.ok(result.rows[2].pixels.some(pixel=>pixel<100));
});
test('short beams with four lines or unequal spacing do not become a staff',()=>{
 const w=960,h=540,a=new Uint8Array(w*h).fill(250);
 for(const y of [100,107,114,121,240,247,254,270,277])for(let x=25;x<500;x++)a[y*w+x]=50;
 assert.equal(detectStaves(a,w,h).length,0);
});
