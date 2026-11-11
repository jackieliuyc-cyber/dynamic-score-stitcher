// Pixel-based staff extraction. No OCR service, uploaded video, or generative notation.
export function detectStaves(gray, w, h) {
  const strength = new Float32Array(h); let peak = 0;
  for (let y=0;y<h;y++) { let dark=0; for(let x=8;x<w-8;x+=2) if(gray[y*w+x]<195)dark++;
    strength[y]=dark/Math.max(1,(w-16)/2);peak=Math.max(peak,strength[y]); }
  // Ending bars and meter-change rows may occupy only part of the viewport.
  // Keep the five equally spaced lines check; do not require full-width staves.
  const threshold=Math.max(.30,peak*.35),groups=[];
  for(let y=0;y<h;y++)if(strength[y]>threshold){const last=groups.at(-1);if(last&&y-last.at(-1)<=2)last.push(y);else groups.push([y]);}
  const lines=groups.map(g=>g.reduce((a,b)=>a+b,0)/g.length), systems=[];
  for(let i=0;i+4<lines.length;){
    const ys=lines.slice(i,i+5),gaps=ys.slice(1).map((v,j)=>v-ys[j]);
    const sorted=[...gaps].sort((a,b)=>a-b),gap=(sorted[1]+sorted[2])/2;
    if(gap>=2.5&&gap<h/16&&gaps.every(g=>Math.abs(g-gap)<=Math.max(1.3,gap*.21))){
      const top=Math.round(ys[0]-gap*6.3),bottom=Math.round(ys[4]+gap*3.8);
      systems.push({y:ys[0],gap,top,bottom,complete:top>=3&&bottom<=h-3});i+=5;
    }else i++;
  }
  for(let i=0;i<systems.length-1;i++){const a=systems[i],b=systems[i+1];if(a.bottom>b.top){const cut=Math.round((a.y+4*a.gap+b.y)/2);a.bottom=Math.min(a.bottom,cut);b.top=Math.max(b.top,cut);}}
  return systems;
}
function blur(gray,w,h){
  const out=new Uint8Array(gray.length);
  for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const p=y*w+x;out[p]=(gray[p]*4+gray[p-1]+gray[p+1]+gray[p-w]+gray[p+w])/8;}
  return out;
}
function labelChange(a,b,w,systems){
  let changes=0;const right=Math.max(25,Math.round(w*.065));
  for(const s of systems.filter(s=>s.complete)){
    let union=0,xor=0,na=0,nb=0;
    for(let y=Math.max(0,Math.round(s.y-s.gap*4));y<Math.round(s.y-s.gap);y++)for(let x=0;x<right;x++){
      const aa=a[y*w+x]<150,bb=b[y*w+x]<150;union+=aa||bb;xor+=aa!==bb;na+=aa;nb+=bb;
    }
    if(na>5&&nb>5&&union>10&&xor/union>.18)changes++;
  }
  return changes>=2;
}
export function estimateScroll(a,b,w,h,oldSystems,systems){
  let diff=0,count=0;for(let y=10;y<h-10;y+=3)for(let x=8;x<w-8;x+=4){diff+=Math.abs(a[y*w+x]-b[y*w+x]);count++;}
  const changedLabels=labelChange(a,b,w,systems);
  if(diff/count<2.8&&!changedLabels)return 0;
  const candidates=new Set([0]);
  for(const old of oldSystems)for(const cur of systems){const delta=Math.round(old.y-cur.y);if(delta>=0&&delta<h*.75)for(let d=-2;d<=2;d++)if(delta+d>=0)candidates.add(delta+d);}
  const aa=blur(a,w,h),bb=blur(b,w,h),margin=Math.max(4,Math.round(h*.065));
  let best={rank:Infinity,loss:Infinity,shift:0};
  for(const shift of candidates){
    if(shift===0&&changedLabels)continue;
    const end=h-margin-shift;if(end-margin<h*.28)continue;
    let loss=0,active=0,leftLoss=0,leftCount=0;
    for(let y=margin;y<end;y+=2)for(let x=8;x<w-8;x+=4){
      const av=aa[(y+shift)*w+x],bv=bb[y*w+x];if(av<225||bv<225){const d=Math.abs(av-bv);loss+=d;active++;if(x<w*.08){leftLoss+=d;leftCount++;}}
    }
    if(active<50)continue;
    const error=loss/active/255+(leftCount>10?.3*leftLoss/leftCount/255:0);
    const rank=error+.12*shift/h;
    if(rank<best.rank)best={rank,loss:error,shift};
  }
  if(best.loss>.21)return null;
  if(best.shift<2&&labelChange(a,b,w,systems))return null;
  return best.shift;
}
export class ScoreEngine {
  constructor(){this.rows=[];this.previous=null;this.oldSystems=[];this.offset=0;this.segment=0;this.breaks=0;this.frames=0;this.blankFrames=0;this.header=null;this.bytes=0;}
  add(rgba,w,h,time){
    if(w<120||h<60)throw new Error('谱面区域太小，请扩大框选范围。');
    const gray=new Uint8Array(w*h),blue=new Uint8Array(w*h);
    for(let i=0;i<gray.length;i++){const p=i*4,r=rgba[p],g=rgba[p+1],b=rgba[p+2];gray[i]=r;blue[i]=b-r>14&&b-g>4?(r>100?5:1):0;}
    const systems=detectStaves(gray,w,h);this.frames++;
    const complete=systems.filter(s=>s.complete);if(!complete.length){this.blankFrames++;return this.summary();}
    if(this.previous){const shift=estimateScroll(this.previous,gray,w,h,this.oldSystems,systems);if(shift===null){this.segment++;this.offset=0;this.breaks++;}else this.offset+=shift;}
    this.previous=gray;this.oldSystems=systems;
    if(!this.rows.length){
      const end=Math.max(0,complete[0].top-8);let first=end,last=0;
      if(!systems.some(s=>s.y<complete[0].y)&&end>30){
        for(let y=0;y<end;y++){let ink=0;for(let x=0;x<w;x++)if(gray[y*w+x]<155)ink++;if(ink>w*.003){first=Math.min(first,y);last=y;}}
        if(last>first){const top=Math.max(0,first-6),bottom=Math.min(end,last+8);this.header={width:w,height:bottom-top,pixels:gray.slice(top*w,bottom*w)};}
      }
    }
    for(const s of complete){
      const position=s.y+this.offset;
      let row;for(let index=this.rows.length-1;index>=0;index--){const candidate=this.rows[index];if(candidate.segment===this.segment&&Math.abs(candidate.position-position)<s.gap*3.3){row=candidate;break;}}
      let penalty=0;for(let y=s.top;y<s.bottom;y++)for(let x=0;x<w;x++)penalty+=blue[y*w+x];
      let replace=false;
      if(!row){row={id:this.rows.length+1,position,segment:this.segment,time,penalty:Infinity,seen:0,width:w,height:s.bottom-s.top,pixels:null};this.rows.push(row);replace=true;}
      row.seen++;row.position=row.position*.8+position*.2;
      if(replace||penalty<row.penalty){
        if(row.pixels)this.bytes-=row.pixels.byteLength;
        row.penalty=penalty;row.time=time;row.height=s.bottom-s.top;row.pixels=gray.slice(s.top*w,s.bottom*w);
        for(let i=0;i<row.pixels.length;i++)row.pixels[i]=Math.max(0,Math.min(255,(row.pixels[i]-10)*255/237));
        this.bytes+=row.pixels.byteLength;
      }
    }
    if(this.rows.length>200||this.bytes>24*1024*1024)throw new Error('谱面过长，已达到手机处理上限。请缩短时间范围，分段生成。');
    return this.summary();
  }
  summary(){return {rows:this.rows.length,frames:this.frames,breaks:this.breaks};}
  result(){
    if(!this.rows.length)throw new Error('未识别到完整五线谱。请框选清晰谱面，或更换视频。');
    const warnings=[];
    if(this.breaks)warnings.push(`有 ${this.breaks} 处画面无法连续对齐，请在「检查谱行」中核对。`);
    if(this.rows.some(r=>r.penalty>350))warnings.push('部分彩色播放标记无法完全避开，已转为灰度。');
    if(this.rows.length===1)warnings.push('只找到一行谱面。横向滚动视频暂不支持，请检查是否完整。');
    return {rows:this.rows.sort((a,b)=>a.segment-b.segment||a.position-b.position),header:this.header,warnings,frames:this.frames,breaks:this.breaks};
  }
}
export function planPages(rows,width,maxPixels=6500000,maxHeight=7800){
  const limit=Math.min(maxHeight,Math.floor(maxPixels/(width+40))),pages=[];let page=[],height=150;
  for(const row of rows){const needed=row.height+16;if(page.length&&height+needed>limit){pages.push(page);page=[];height=150;}page.push(row);height+=needed;}
  if(page.length)pages.push(page);return pages;
}
