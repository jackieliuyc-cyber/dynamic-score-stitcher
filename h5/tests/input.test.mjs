import test from 'node:test';
import assert from 'node:assert/strict';
import {validCrop,videoProblem} from '../dist/input.js';
test('touch crop rejects reversed, tiny and nonfinite regions',()=>{
  assert.ok(validCrop([0,.1,1,.9]));
  assert.ok(validCrop([.6,.7,.8,.82]));
  for(const crop of [[.8,0,.2,1],[0,0,.1,.1],[NaN,0,1,1],[-.1,0,1,1]])assert.equal(validCrop(crop),false);
});
test('screen recording formats must have finite duration and usable decoded dimensions',()=>{
  assert.equal(videoProblem(317,1920,1080),'');
  for(const duration of [Infinity,NaN,0])assert.match(videoProblem(duration,1920,1080),/时长|长度/);
  assert.match(videoProblem(901,1920,1080),/15 分钟/);
  assert.match(videoProblem(317,0,0),/画面/);
});
