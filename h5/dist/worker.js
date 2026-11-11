import {ScoreEngine} from './engine.js';
let engine=new ScoreEngine();
self.onmessage=({data})=>{
  try{
    if(data.type==='reset'){engine=new ScoreEngine();self.postMessage({id:data.id,ok:true});}
    if(data.type==='frame'){const summary=engine.add(new Uint8ClampedArray(data.buffer),data.width,data.height,data.time);self.postMessage({id:data.id,summary});}
    if(data.type==='finish'){
      const result=engine.result(),buffers=result.rows.map(r=>r.pixels.buffer);if(result.header)buffers.push(result.header.pixels.buffer);
      self.postMessage({id:data.id,result},buffers);
    }
  }catch(error){self.postMessage({id:data.id,error:error.message||'画面分析失败。'});}
};
