'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Scene, measurementInfo}=require('../rppg/live_web/live.js');
const row=(t,extra={})=>({segment_id:1,elapsed_s:t,segment_elapsed_s:t,face_count:1,frame_reasons:[],sample_count:330,
  analysis:{event_id:`1:${t}`,timestamp_s:t,hr_bpm:null,reasons:['diffuse_spectrum'],peak_concentration:.2},...extra});
const show=(s,t,active=true)=>measurementInfo({...s.view(t),active});
test('long running diffuse signal remains visibly analyzing after initial20s',()=>{
  const s=new Scene();for(let t=20;t<=240;t++)s.receive(row(t),t*1000,t*1000);
  const v=show(s,240000);assert.equal(s.view(240000).progress,20);
  assert.match(v.progressLabel,/최근 20초를 매초 분석 중/);
  assert.match(v.analysisLabel,/240.0초/);assert.match(v.signalLabel,/20.0%/);
  assert.match(v.signalLabel,/35%/);assert.equal(s.view(240000).hr,null);
});
test('stale replies and stale analysis never claim ongoing analysis or fresh signal',()=>{
  const s=new Scene();s.receive(row(240),240000,240000);
  assert.doesNotMatch(show(s,242000).progressLabel,/매초 분석 중/);
  assert.equal(show(s,242000).signalLabel,'—');
  s.receive(row(242,{analysis:row(240).analysis}),242000,242000);
  assert.doesNotMatch(show(s,242000).progressLabel,/매초 분석 중/);
  assert.equal(show(s,242000).signalLabel,'—');
});
test('collection, reset and idle show no previous analysis or concentration',()=>{
  const s=new Scene();s.receive(row(8,{analysis:null}),8000,8000);
  assert.match(show(s,8000).progressLabel,/8.0 \/ 20초/);
  assert.equal(show(s,8000).signalLabel,'—');
  s.receive(row(240),240000,240000);
  const idle=show(s,240000,false);assert.equal(idle.progressLabel,'측정 대기');assert.equal(idle.signalLabel,'—');assert.equal(idle.analysisLabel,'—');
  s.receive(row(241,{segment_id:2,segment_elapsed_s:0,analysis:null}),241000,241000);
  const reset=show(s,241000);assert.match(reset.progressLabel,/0.0 \/ 20초/);assert.equal(reset.analysisLabel,'—');assert.equal(reset.signalLabel,'—');
});
test('concentration is unavailable for missing, nonfinite or out of range values',()=>{
  for(const value of [null,undefined,NaN,Infinity,-.2,1.2]){
    const s=new Scene();s.receive(row(20,{analysis:{...row(20).analysis,peak_concentration:value}}),20000,20000);
    assert.equal(show(s,20000).signalLabel,'—');
  }
});
