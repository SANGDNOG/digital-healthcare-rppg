'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Live, Scene, ReceivedFrames, dimensions } = require('../rppg/live_web/live.js');
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i=0;i<20;i++) await Promise.resolve(); };
const result = (t, overrides={}) => ({ boot_id:'boot', session_id:'session', seq:0, segment_id:1, elapsed_s:t,
  segment_elapsed_s:t, face_count:1, face_box:[10,20,100,100], frame_width:640, frame_height:480,
  frame_reasons:[], sample_count:300, analysis:{event_id:`1:${t}`,timestamp_s:t,hr_bpm:72,reasons:[],sampling_rate_hz:15}, ...overrides });
function fixture() {
  let now=0, frame=null, index=0;
  const calls=[], timers=new Map(), intervals=new Map(), tracks=[], views=[], encodes=[];
  const track={ stopped:0, stop(){this.stopped++;}, addEventListener(name,cb){this[name]=cb;} }; tracks.push(track);
  const stream={ getTracks:()=>tracks };
  const config={token:'secret',boot_id:'boot'};
  const env={ now:()=>now, uuid:()=> 'client',
    getUserMedia:async constraints=>{ env.constraints=constraints; env.permissions++; return stream; }, permissions:0,
    fetch:async (url,options)=>{ calls.push({url,options});
      if(env.override) {const v=env.override(url,options); if(v) return v;}
      const body=url==='/api/config'?config:url==='/api/session'?{session_id:'session',boot_id:'boot'}:url==='/api/stop'?{stopped:true}:result(now/1000,{seq:Number(options.headers['X-Frame-Seq'])});
      return {ok:true,json:async()=>body}; },
    setTimeout:(cb,ms)=>{ const id=++index;timers.set(id,{cb,ms});return id; }, clearTimeout:id=>timers.delete(id),
    setInterval:cb=>{const id=++index;intervals.set(id,cb);return id;},clearInterval:id=>intervals.delete(id),
    attach:async s=>{env.attached=s;}, frame:cb=>{frame=cb;return ++index;}, cancelFrame:()=>{frame=null;},
    videoTime:()=>now/1000, videoSize:()=>[1920,1080], encode:async size=>{ encodes.push({size,at:now});return {type:'image/png',size:100};},
    render:s=>views.push(s)
  };
  const live=new Live(env);
  return {live,env,calls,timers,intervals,track,stream,views,encodes, setNow:n=>{now=n;},
    frame:async metadata=>{const cb=frame;frame=null;assert.ok(cb,'scheduled frame');cb(metadata);await flush();},
    frameScheduled:()=>!!frame};
}
test('idle never requests permission or starts networking; explicit start is silent audio',async()=>{
  const f=fixture();assert.equal(f.env.permissions,0);assert.equal(f.calls.length,0);
  await f.live.start();assert.equal(f.env.permissions,1);assert.equal(f.env.constraints.audio,false);
  assert.deepEqual(f.env.constraints.video,{width:{ideal:640},height:{ideal:480},frameRate:{ideal:30}});
  assert.deepEqual(JSON.parse(f.calls.find(c=>c.url==='/api/session').options.body),{client_id:'client'});
  f.live.stop();await flush();assert.equal(f.track.stopped,1);assert.equal(f.env.attached,null);
  assert.equal(f.intervals.size,0);assert.equal(f.frameScheduled(),false);
  assert.ok(f.calls.some(c=>c.url==='/api/stop'));
});
test('permission rejection clears state; a late permission result after stop disposes every track',async()=>{
  const f=fixture();const d=deferred();f.env.getUserMedia=()=>d.promise;
  const start=f.live.start();await flush();f.live.stop();d.resolve(f.stream);await start;
  assert.equal(f.track.stopped,1);assert.equal(f.calls.some(c=>c.url==='/api/session'),false);
  const g=fixture();g.env.getUserMedia=async()=>{throw Object.assign(new Error(),{name:'NotAllowedError'});};
  await g.live.start();assert.equal(g.live.active,false);assert.match(g.live.message,/권한/);
});
test('late permission from an old start cannot replace a newer camera',async()=>{
  const f=fixture(),d=deferred(),old={stopped:0,stop(){this.stopped++;}};
  f.env.getUserMedia=()=>d.promise;const first=f.live.start();await flush();f.live.stop();
  f.env.getUserMedia=async()=>f.stream;await f.live.start();
  d.resolve({getTracks:()=>[old]});await first;
  assert.equal(old.stopped,1);assert.equal(f.track.stopped,0);assert.equal(f.live.active,true);f.live.stop();
});
test('device end disposes tracks and clears scene',async()=>{
  const f=fixture();await f.live.start();f.track.ended();assert.equal(f.live.active,false);assert.equal(f.track.stopped,1);
  assert.equal(f.live.scene.data,null);await flush();
});
test('late session creation is best-effort stopped without accepting it',async()=>{
  const f=fixture(),d=deferred();f.env.override=url=>url==='/api/session'?d.promise:null;
  const start=f.live.start();await flush();f.live.stop();
  d.resolve({ok:true,json:async()=>({session_id:'late',boot_id:'boot'})});await start;await flush();
  assert.equal(f.live.session,null);assert.equal(f.track.stopped,1);
  assert.ok(f.calls.some(c=>c.url==='/api/stop'&&JSON.parse(c.options.body).session_id==='late'));
});
test('single frame in flight, elapsed pacing, new frame dedup, bounded PNG and capture time before encoding',async()=>{
  const f=fixture();await f.live.start();f.setNow(1000);
  const d=deferred();f.env.encode=async size=>{f.encodes.push({size,at:1000});f.setNow(1050);return d.promise;};
  await f.frame({presentedFrames:1});assert.equal(f.frameScheduled(),false);assert.equal(f.calls.filter(c=>c.url==='/api/frame').length,0);
  d.resolve({type:'image/png',size:100});await flush();
  const call=f.calls.find(c=>c.url==='/api/frame');assert.equal(call.options.headers['X-Capture-Time'],'1');
  assert.equal(call.options.headers['Content-Type'],'image/png');assert.deepEqual(f.encodes[0].size,[640,360]);
  await f.frame({presentedFrames:2});assert.equal(f.encodes.length,1,'encoding counts toward cadence');
  f.setNow(1070);await f.frame({presentedFrames:1});assert.equal(f.encodes.length,1,'duplicate source skipped');
  f.env.encode=async()=>({type:'image/png',size:100});await f.frame({presentedFrames:3});
  assert.equal(f.calls.filter(c=>c.url==='/api/frame').length,2);f.live.stop();
});
test('RAF fallback skips repeated currentTime and dimensions fit both bounds',async()=>{
  assert.deepEqual(dimensions(1080,1920),[270,480]);assert.deepEqual(dimensions(320,240),[320,240]);assert.equal(dimensions(0,0),null);
  const f=fixture();await f.live.start();f.env.videoTime=()=>1;f.setNow(1000);await f.frame(null);
  f.setNow(1200);await f.frame(null);assert.equal(f.encodes.length,1);f.live.stop();
});
test('oversized or non-PNG encoded output is rejected before upload',async()=>{
  for(const blob of [{type:'image/png',size:2097153},{type:'image/jpeg',size:100},null]){
    const f=fixture();await f.live.start();f.env.encode=async()=>blob;await f.frame({presentedFrames:1});
    assert.equal(f.calls.some(c=>c.url==='/api/frame'),false);assert.equal(f.track.stopped,1);
  }
});
test('stop during encoding prevents upload; late frame response cannot restore stopped state',async()=>{
  const f=fixture(),d=deferred();await f.live.start();f.env.encode=()=>d.promise;
  await f.frame({presentedFrames:1});f.live.stop();d.resolve({type:'image/png',size:100});await flush();assert.equal(f.calls.some(c=>c.url==='/api/frame'),false);
  const g=fixture(),r=deferred();await g.live.start();g.env.override=url=>url==='/api/frame'?r.promise:null;
  await g.frame({presentedFrames:1});const call=g.calls.find(c=>c.url==='/api/frame');g.live.stop();assert.equal(call.options.signal.aborted,true);
  r.resolve({ok:true,json:async()=>result(21)});await flush();assert.equal(g.live.scene.data,null);assert.equal(g.frameScheduled(),false);
});
test('network error, request timeout and boot/session/seq mismatch stop the camera',async()=>{
  for(const response of ['reject','timeout',{boot_id:'other'},{session_id:'other'},{seq:999}]){
    const f=fixture();await f.live.start();f.env.override=(url,options)=>{
      if(url!=='/api/frame')return null;
      if(response==='reject')return Promise.reject(new Error('offline'));
      if(response==='timeout')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('abort'))));
      return Promise.resolve({ok:true,json:async()=>result(20,response)});
    };
    await f.frame({presentedFrames:1});
    if(response==='timeout'){const timer=[...f.timers.values()].find(t=>t.ms===6000);assert.ok(timer);timer.cb();await flush();}
    assert.equal(f.live.active,false);assert.equal(f.track.stopped,1);assert.equal(f.live.scene.data,null);
  }
});
test('two distinct events confirm; duplicate IDs and timestamps cannot confirm',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);assert.equal(s.view(20000).hr,null);
  s.receive(result(20.1,{analysis:{...result(20).analysis}}),20100,20100);assert.equal(s.streak,1);
  s.receive(result(20.2,{analysis:{...result(20).analysis,event_id:'new'}}),20200,20200);assert.equal(s.streak,1);
  s.receive(result(21),21000,21000);assert.equal(s.view(21000).status,'current');assert.equal(s.view(21000).hr,72);
});
test('bad frame blocks immediately, duplicates cannot recover, held age expires from endpoint',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);s.receive(result(21),21000,21000);
  s.receive(result(21.1,{frame_reasons:['motion'],analysis:result(21).analysis}),21100,21100);
  assert.equal(s.view(21100).status,'held');
  s.receive(result(21.2,{analysis:result(21).analysis}),21200,21200);assert.equal(s.view(21200).status,'held');
  s.receive(result(22),22000,22000);assert.equal(s.view(22000).status,'held');
  s.receive(result(23),23000,23000);assert.equal(s.view(23000).status,'current');
  assert.equal(s.view(24600).status,'held');assert.equal(s.view(26000).status,'held');assert.equal(s.view(26001).hr,null);
});
test('analysis gaps reset confirmation, old/delayed endpoints never appear current',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);s.receive(result(22),22000,22000);assert.equal(s.view(22000).hr,null);
  s.receive(result(23),23000,23000);assert.equal(s.view(23000).status,'current');
  assert.equal(s.view(24501).status,'held');
  s.receive(result(25),25000,25000);assert.equal(s.view(25000).status,'held');
  s.receive(result(26),26000,26000);assert.equal(s.view(26000).status,'current');
  s.receive(result(27),27000,31000);assert.equal(s.view(31000).hr,null,'receipt does not refresh endpoint age');
});
test('segment reset clears previous HR, progress, events and confirmation',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);s.receive(result(21),21000,21000);
  s.receive(result(22,{segment_id:2,segment_elapsed_s:0,analysis:null,face_count:2,frame_reasons:['multiple_faces']}),22000,22000);
  assert.equal(s.view(22000).hr,null);assert.equal(s.view(22000).progress,0);assert.equal(s.streak,0);
});
test('assets have strict external-only CSP, Korean accessible controls and frozen results link',()=>{
  const dir=path.join(__dirname,'../rppg/live_web');const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');const js=fs.readFileSync(path.join(dir,'live.js'),'utf8');
  assert.match(html,/lang="ko"/);assert.match(html,/script-src 'self'/);assert.match(html,/style-src 'self'/);
  assert.doesNotMatch(html,/unsafe-inline|https:\/\/|<style|onload=|onclick=/);
  assert.match(html,/<script src="\/live.js" defer><\/script>/);assert.match(html,/http:\/\/127.0.0.1:8765\//);
  assert.match(html,/role="status"/);assert.match(html,/for="progress"/);assert.match(html,/playsinline/);
  assert.match(js,/visibilitychange/);assert.match(js,/document.hidden/);assert.match(js,/pagehide/);
});

test('hidden page disposes camera, cancels requests and clears timers',async()=>{
  const f=fixture();await f.live.start();f.live.hidden();await flush();
  assert.equal(f.track.stopped,1);assert.equal(f.live.active,false);assert.equal(f.intervals.size,0);assert.equal(f.frameScheduled(),false);
  assert.ok(f.calls.some(c=>c.url==='/api/stop'));
});
test('reply gap resets streak even when no render ran during gap',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);
  s.receive(result(21),21000,21600);assert.equal(s.view(21600).hr,null);
});
test('invalid analysis and missing face block current immediately and require two fresh events',()=>{
  const s=new Scene();s.receive(result(20),20000,20000);s.receive(result(21),21000,21000);
  s.receive(result(22,{analysis:{...result(22).analysis,reasons:['diffuse_spectrum']}}),22000,22000);
  assert.equal(s.view(22000).status,'held');
  s.receive(result(23),23000,23000);assert.equal(s.view(23000).status,'held');
  s.receive(result(24),24000,24000);assert.equal(s.view(24000).status,'current');
  s.receive(result(24.1,{face_count:0,frame_reasons:['no_face'],analysis:result(24).analysis}),24100,24100);
  assert.equal(s.view(24100).status,'held');
});

test('jittered 30fps callbacks sustain near 15 uploads/s including encoding and round trip',async()=>{
  const f=fixture();await f.live.start();
  f.env.encode=async size=>{f.encodes.push(size);f.setNow(f.env.now()+8);return {type:'image/png',size:100};};
  const jitter=[0.2,-0.4,0.3,-0.2,0.1,-0.3];
  for(let i=0;i<300;i++){
    const time=1000+i*1000/30+jitter[i%jitter.length];f.setNow(time);
    f.env.override=(url,options)=>{if(url!=='/api/frame')return null;
      f.setNow(time+25);return Promise.resolve({ok:true,json:async()=>result((time-1000)/1000,{seq:Number(options.headers['X-Frame-Seq'])})});};
    await f.frame({presentedFrames:i+1});
  }
  const count=f.calls.filter(c=>c.url==='/api/frame').length;
  assert.ok(count>=148&&count<=151,`expected about 150 uploads, got ${count}`);
  assert.ok(f.live.scene.view(11000).fps>14);f.live.stop();
});
test('missed deadlines are skipped with no burst or round-trip sleep',async()=>{
  const f=fixture();await f.live.start();f.setNow(1000);await f.frame({presentedFrames:1});
  f.setNow(1450);await f.frame({presentedFrames:2});
  assert.ok(f.live.nextCapture>1450&&f.live.nextCapture<1517);
  f.setNow(1455);await f.frame({presentedFrames:3});
  assert.equal(f.calls.filter(c=>c.url==='/api/frame').length,2);f.live.stop();
});
test('stuck video play times out, disposes tracks, and late play cannot create a session',async()=>{
  const f=fixture(),d=deferred();f.env.attach=stream=>stream?d.promise:Promise.resolve();
  const starting=f.live.start();await flush();
  const timer=[...f.timers.values()].find(t=>t.ms===8000);assert.ok(timer);timer.cb();await starting;
  assert.equal(f.track.stopped,1);assert.equal(f.live.active,false);
  d.resolve();await flush();assert.equal(f.calls.some(c=>c.url==='/api/session'),false);
});
test('stop cancels pending video preparation and rejected detach is handled',async()=>{
  const f=fixture(),d=deferred();f.env.attach=stream=>stream?d.promise:Promise.reject(new Error('detach'));
  const starting=f.live.start();await flush();f.live.stop();await starting;await flush();
  assert.equal(f.track.stopped,1);assert.equal(f.timers.size,0);d.resolve();await flush();
  assert.equal(f.calls.some(c=>c.url==='/api/session'),false);
});

test('received frame rate counts actual replies, rejects duplicates and ages out stalled replies',()=>{
  const rate=new ReceivedFrames(0);
  for(let i=1;i<=45;i++) rate.record(i*1000/15-20,i*1000/15);
  assert.equal(rate.rate(3000),15);
  rate.record(2980,3000);rate.record(1000,3001);rate.record(NaN,3002);
  assert.equal(rate.rate(3000),15,'duplicates and out-of-order captures do not inflate count');
  assert.equal(rate.rate(6000),0,'no stale optimistic rate while next reply is pending');
  const slow=new ReceivedFrames(0);slow.record(0,2999);
  assert.equal(slow.rate(3000),1/3,'one delayed reply is not an infinite inter-arrival rate');
});
test('slow transfer warning appears at 3s without analysis, survives segment resets and clears on stop',async()=>{
  const f=fixture();await f.live.start();
  f.env.override=(url,options)=>url==='/api/frame'?Promise.resolve({ok:true,json:async()=>result(f.env.now()/1000,{
    seq:Number(options.headers['X-Frame-Seq']),segment_id:Number(options.headers['X-Frame-Seq']),segment_elapsed_s:0,analysis:null,sample_count:1})}):null;
  for(let i=0;i<6;i++){f.setNow(i*500);await f.frame({presentedFrames:i+1});}
  f.setNow(2999);f.live.emit();assert.equal(f.views.at(-1).transferWarning,'');
  f.setNow(3000);f.live.emit();assert.match(f.views.at(-1).transferWarning,/전송 속도가 부족해 심박수를 계산할 수 없습니다/);
  assert.equal(f.views.at(-1).receivedFps,5/3);
  f.setNow(3500);await f.frame({presentedFrames:7});assert.ok(f.views.at(-1).transferWarning);
  assert.equal(f.views.at(-1).progress,0);assert.equal(f.views.at(-1).data.analysis,null);
  f.live.stop();assert.equal(f.views.at(-1).transferWarning,'');assert.equal(f.views.at(-1).receivedFps,null);
});
test('healthy received cadence clears warning before any analysis; stalled upload triggers it again',async()=>{
  const f=fixture();await f.live.start();f.setNow(3000);f.live.emit();assert.ok(f.views.at(-1).transferWarning);
  for(let i=1;i<=45;i++){
    f.setNow(3000+i*1000/15);f.live.received.record(3000+i*1000/15-10,f.env.now());
  }
  f.live.emit();assert.equal(f.views.at(-1).receivedFps,15);assert.equal(f.views.at(-1).transferWarning,'');
  f.setNow(9000);f.live.emit();assert.equal(f.views.at(-1).receivedFps,0);assert.ok(f.views.at(-1).transferWarning);f.live.stop();
});

test('processing location comes only from explicit-start config and clears while idle', async()=>{
  for(const [mode,label] of [['local','이 컴퓨터에서 분석 · 영상은 외부로 보내지 않습니다'],['remote','원격 PC에서 분석'],[undefined,''],['unknown','']]){
    const f=fixture();
    assert.equal(f.views.at(-1).processingLocation,'');assert.equal(f.calls.length,0);
    f.env.override=url=>url==='/api/config'?Promise.resolve({ok:true,json:async()=>({token:'secret',boot_id:'boot',execution_mode:mode})}):null;
    await f.live.start();assert.equal(f.views.at(-1).processingLocation,label);
    f.live.stop();assert.equal(f.views.at(-1).processingLocation,'');
  }
});
test('new start does not retain previous config label while config is pending',async()=>{
  const f=fixture();f.env.override=url=>url==='/api/config'?Promise.resolve({ok:true,json:async()=>({token:'secret',boot_id:'boot',execution_mode:'local'})}):null;
  await f.live.start();f.live.stop();const d=deferred();
  f.env.override=url=>url==='/api/config'?d.promise:null;
  const starting=f.live.start();await flush();assert.equal(f.views.at(-1).processingLocation,'');
  f.live.stop();d.resolve({ok:true,json:async()=>({token:'secret',boot_id:'boot',execution_mode:'remote'})});await starting;
  assert.equal(f.views.at(-1).processingLocation,'');
});
test('idle HTML privacy has no asserted processing location',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../rppg/live_web/index.html'),'utf8');
  assert.match(html,/<p id="processing-location" role="status" aria-live="polite"><\/p>/);
  assert.match(html,/영상은 저장하지 않습니다/);
  assert.doesNotMatch(html,/SSH|원격 PC에서 분석|이 컴퓨터에서 분석|Python|8767/);
});
