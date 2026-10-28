'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {StressPilot,Live,csvCell}=require('../rppg/live_web/live.js');
const row=(t,extra={})=>({elapsed_s:t,segment_id:1,face_count:1,frame_reasons:[],
  analysis:{event_id:`1:${t}`,timestamp_s:t,hr_bpm:70,reasons:[],peak_concentration:.6},...extra});
function tick(p,end){for(let n=p.lastTick+100;n<=end;n+=100)p.advance(n);}
function receive(p,t,extra={},delay=0){p.receive(row(t,extra),p.origin+t*1000,p.origin+t*1000+delay);}
function completed(){const p=new StressPilot('P01','same light');p.capture(10000);
  for(let t=1;t<=180;t++){tick(p,10000+t*1000);receive(p,t,{analysis:{...row(t).analysis,hr_bpm:t<60?70:t<120?80:75}});}return p;}
test('preparing cue precedes acquisition; first capture anchors clock, not click',()=>{
  const p=new StressPilot();p.advance(500000);assert.equal(p.status,'preparing');assert.equal(p.origin,null);
  p.capture(501000);assert.equal(p.origin,501000);assert.equal(p.phases[0].start,0);
  tick(p,560900);assert.equal(p.phase,0);tick(p,561000);assert.equal(p.phase,1);
  assert.equal(p.phases[0].end,60);assert.equal(p.phases[1].start,60);
});
test('full protocol gates at30 unique contained analyses, computes medians/deltas and missing !=0',()=>{
  const p=completed(),d=p.exportData();assert.equal(d.status,'complete');
  assert.deepEqual(d.phases.map(x=>x.usable_count),[40,40,40]);
  assert.deepEqual(d.phases.map(x=>x.median_hr_bpm),[70,80,75]);
  assert.equal(d.task_minus_rest_bpm,10);assert.equal(d.recovery_minus_rest_bpm,5);
  assert.deepEqual(d.phases.map(x=>x.self_report),[null,null,null]);
  p.setReport(0,'0');p.setReport(1,'');p.setReport(2,11);assert.deepEqual(p.reports,[0,null,null]);
  assert.match(d.protocol.interpretation,/not independent/);
});
test('strict upper containment rejects endpoint60 and180; arrival phase never assigns window',()=>{
  const p=new StressPilot();p.capture(0);tick(p,60000);
  receive(p,59,{},1100);receive(p,60);receive(p,80);tick(p,120000);receive(p,119);receive(p,120);
  tick(p,180000);const d=p.exportData();assert.equal(d.phases[0].contained_count,1);
  assert.equal(d.phases[1].contained_count,2);assert.equal(d.unassigned_count,2);
  assert.equal(d.events[0].window_end_s,59);
});
test('actual late cue is never backdated and contaminating window is excluded',()=>{
  const p=new StressPilot();p.capture(0);tick(p,59900);p.advance(60100);
  assert.equal(p.phases[0].end,60.1);assert.equal(p.phases[1].start,60.1);
  receive(p,80);receive(p,81);tick(p,120000);
  assert.equal(p.summary()[1].contained_count,1);assert.equal(p.summary()[1].usable_count,1);
});
test('duplicates, segment-reset IDs, old endpoints and invalid events cannot become held-HR records',()=>{
  const p=new StressPilot();p.capture(0);
  receive(p,21,{analysis:{...row(21).analysis,hr_bpm:null}});receive(p,21);
  receive(p,22,{analysis:{...row(22).analysis,event_id:'same'}});
  receive(p,23,{analysis:{...row(23).analysis,event_id:'same'}});
  receive(p,23,{segment_id:2,analysis:{...row(23).analysis,event_id:'same'}});
  // Reused IDs are scoped to a segment, while timestamps are unique across segments.
  receive(p,24,{segment_id:2,analysis:{...row(24).analysis,event_id:'same'}});
  receive(p,20);tick(p,60000);
  assert.equal(p.events.length,4);assert.equal(p.events[0].hr_bpm,null);
  assert.ok(p.events.at(-1).exclusions.includes('nonincreasing_endpoint'));
  assert.equal(p.summary()[0].usable_count,2);
});
test('freshness, frame conditions and quality reject distinctly and never reconsider',()=>{
  const p=new StressPilot();p.capture(0);
  receive(p,21,{},1600);receive(p,21);
  receive(p,22,{face_count:2});receive(p,23,{frame_reasons:['motion']});
  receive(p,24,{analysis:{...row(24).analysis,reasons:['diffuse_spectrum']}});
  receive(p,25,{analysis:{...row(25).analysis,hr_bpm:Infinity}});
  receive(p,26);tick(p,60000);
  assert.equal(p.events.length,6);assert.equal(p.summary()[0].usable_count,1);
  assert.equal(p.summary()[0].quality_excluded_count,5);
  assert.ok(p.events[0].exclusions.includes('stale_analysis'));
});
test('30 is required, complete phase required, no artificial span requirement',()=>{
  const p=new StressPilot();p.capture(0);for(let i=0;i<29;i++)receive(p,30+i*.01);
  tick(p,60000);assert.equal(p.summary()[0].engineering_gate,false);
  const q=new StressPilot();q.capture(0);for(let i=0;i<30;i++)receive(q,30+i*.01);
  q.abort('stop',40000);assert.equal(q.summary()[0].median_hr_bpm,null);
  const r=new StressPilot();r.capture(0);for(let i=0;i<30;i++)receive(r,30+i*.01);
  tick(r,60000);assert.equal(r.summary()[0].median_hr_bpm,70);
});
test('timer gap, hide/stop/error abortion preserve partials and terminal acquisition is immutable',()=>{
  for(const reason of ['hidden','stop','error']){
    const p=new StressPilot();p.capture(0);receive(p,25);p.abort(reason,26000);
    const before=JSON.stringify(p.exportData());p.capture(30000);p.advance(180000);receive(p,31);p.abort('again',32000);
    assert.equal(JSON.stringify(p.exportData()),before);assert.equal(p.status,'aborted');
  }
  const p=new StressPilot();p.capture(0);receive(p,25);p.advance(61000);
  assert.equal(p.status,'aborted');assert.equal(p.reason,'timer_gap');assert.equal(p.phases[0].complete,false);
  assert.equal(p.events.length,1);
  const q=completed(),before=JSON.stringify(q.exportData());receive(q,181);q.abort('stop',181000);assert.equal(JSON.stringify(q.exportData()),before);
});
test('allowlisted export excludes response secrets and CSV neutralizes user formulas',()=>{
  const p=new StressPilot('=CMD()',' \t@SUM(1)\n"x"');p.capture(0);
  receive(p,25,{token:'secretToken',boot_id:'secretBoot',session_id:'secretSession',client_id:'secretClient',face_box:[1,2,3,4],image:'secretImage',rgb:'secretRgb'});
  p.abort('stop',30000);const s=JSON.stringify(p.exportData());
  assert.doesNotMatch(s,/secret|boot_id|session_id|client_id|face_box|image|rgb|token/);
  assert.match(p.csv(),/"'=CMD\(\)"/);assert.match(p.csv(),/"' \t@SUM/);
  assert.equal(csvCell('hello,"world"'),'"hello,""world"""');assert.equal(csvCell(null),'""');
});
test('Live explicit pilot start shows rest before permission and requires reset to replace run',async()=>{
  let now=12345;const views=[];
  const e={now:()=>now,render:s=>views.push(s),setTimeout:()=>1,clearTimeout:()=>{},clearInterval:()=>{},cancelFrame:()=>{},attach:async()=>{},
    fetch:async()=>({ok:true,json:async()=>({token:'t',boot_id:'b'})}),
    getUserMedia:async()=>{assert.equal(views.at(-1).pilot.status,'preparing');throw Error('no device');}};
  const live=new Live(e);assert.equal(await live.startPilot('p','n'),true);
  assert.equal(live.pilot.status,'aborted');const p=live.pilot;
  assert.equal(await live.startPilot('new',''),false);assert.equal(live.pilot,p);
  assert.equal(live.resetPilot(),true);assert.equal(live.pilot,null);
});

test('Live advances render cue immediately, aborts gaps and stops complete pilot camera',()=>{
  let now=0,stops=0;const views=[];
  const env={now:()=>now,render:s=>views.push(s),attach:async()=>{},clearInterval:()=>{},cancelFrame:()=>{}};
  const live=new Live(env);live.pilot=new StressPilot();live.pilot.capture(0);live.active=true;
  live.stream={getTracks:()=>[{stop:()=>stops++}]};
  for(now=100;now<=60000;now+=100)live.advancePilot();
  assert.equal(views.at(-1).pilot.phase,1);assert.equal(views.at(-1).pilot.phases[1].start,60);
  for(now=60100;now<=180000;now+=100)live.advancePilot();
  assert.equal(live.pilot.status,'complete');assert.equal(live.active,false);assert.equal(stops,1);
  assert.equal(live.pilot.phases.every(p=>p.complete),true);
  live.pilot=new StressPilot();live.pilot.capture(now);live.active=true;
  now+=2000;assert.equal(live.advancePilot(),false);assert.equal(live.pilot.reason,'timer_gap');
});

test('reproducible metadata and quality metrics are allowlisted, numeric CSV negatives stay numeric',()=>{
  const p=new StressPilot(),q=new StressPilot();assert.notEqual(p.runId,q.runId);
  assert.ok(Number.isFinite(Date.parse(p.startedUtc)));p.capture(0);
  receive(p,25,{analysis:{...row(25).analysis,valid_fraction:.95,sampling_rate_hz:15,max_gap_seconds:.1}});
  p.abort('stop',27000);p.setReport(0,3);const d=p.exportData();
  assert.equal(d.terminal_elapsed_s,27);assert.equal(d.runtime_id,null);
  assert.equal(d.events[0].event_id,'1:25');assert.equal(d.events[0].segment_id,1);
  assert.equal(d.events[0].valid_fraction,.95);assert.equal(d.events[0].sampling_rate_hz,15);
  assert.equal(d.events[0].max_gap_seconds,.1);assert.equal(d.events[0].phase,'휴식');
  assert.ok(Number.isFinite(Date.parse(d.phases[0].self_report_submitted_utc)));
  assert.equal(csvCell(-5),'-5');assert.equal(csvCell('-5'),`"'-5"`);
  assert.equal(d.events[0].exclusions.includes('incomplete_phase'),true);
});

test('unvisited phases reject self-report after camera denial; started partial phases accept it',()=>{
  const denied=new StressPilot();denied.abort('camera_denied',12345);
  for(let i=0;i<3;i++)denied.setReport(i,0);
  assert.equal(denied.origin,null);
  assert.deepEqual(denied.reports,[null,null,null]);
  assert.deepEqual(denied.exportData().phases.map(p=>p.self_report_submitted_utc),[null,null,null]);
  const partial=new StressPilot();partial.capture(1000);partial.abort('stop',11000);
  partial.setReport(0,0);partial.setReport(1,7);partial.setReport(2,3);
  const phases=partial.exportData().phases;
  assert.equal(phases[0].complete,false);assert.equal(phases[0].self_report,0);
  assert.ok(Number.isFinite(Date.parse(phases[0].self_report_submitted_utc)));
  assert.deepEqual(phases.slice(1).map(p=>p.self_report),[null,null]);
  assert.deepEqual(phases.slice(1).map(p=>p.self_report_submitted_utc),[null,null]);
});

test('fractional actual cue lower bound tolerates subtraction rounding; upper endpoints stay strict',()=>{
  const p=new StressPilot();p.capture(0);tick(p,59900);p.advance(60100);
  for(const t of [20,60,60.1,80,80.1,119.9,120,179.9,180])receive(p,t);
  tick(p,120000);tick(p,180000);const d=p.exportData();
  assert.deepEqual(d.phases.map(p=>p.contained_count),[2,2,1]);
  assert.equal(d.events.find(e=>e.window_end_s===80.1).phase,'암산');
  for(const t of [60.1,120,180]){
    const e=d.events.find(e=>e.window_end_s===t);
    assert.equal(e.phase,null);assert.ok(e.exclusions.includes('cross_phase_or_outside'));
  }
  assert.equal(d.unassigned_count,4);
});
test('freshness inclusive bounds tolerate decimal rounding but reject meaningful excess',()=>{
  const p=new StressPilot();p.capture(0);
  for(const [t,age] of [[21,-.1],[22,-.100001],[23,1.5],[24,1.500001]])receive(p,t,{elapsed_s:t+age});
  tick(p,60000);
  assert.equal(p.summary()[0].usable_count,2);
  assert.deepEqual(p.events.map(e=>e.exclusions.includes('stale_analysis')),[false,true,false,true]);
});
