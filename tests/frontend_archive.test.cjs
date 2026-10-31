const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function setup(){
 const nodes=new Map(),requests=[],intervals=[];
 const node=()=>({value:'',textContent:'',hidden:false,disabled:false,children:[],append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v},setAttribute(){},select(){}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
 for(const [id,value] of Object.entries({'archive-segment':'60','archive-retention':'7','archive-quota':'10240','archive-duration':'30'}))get(id).value=value;
 const ctx=vm.createContext({S:{username:'account',epoch:1,selected:'A',cameras:[{id:'A',viewable:true},{id:'B',viewable:true}]},$:get,document:{hidden:false,createElement:node,addEventListener(){}},api:(...args)=>new Promise((resolve,reject)=>requests.push({args,resolve,reject})),URL,renderDetails(){},showLogin(){this.S.epoch++;this.S.selected=null;this.S.username=null},activateTab(){},setInterval:f=>intervals.push(f),friendly:()=> 'Request failed',navigator:{clipboard:{writeText:async()=>{}}}});
 vm.runInContext(fs.readFileSync('web/archive.js','utf8'),ctx);return {get,requests,intervals,run:s=>vm.runInContext(s,ctx)};
}
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve()};
const reply=(e,archive={recording_enabled:false,records:[],workers:[],jobs:[],storage:{count:0,bytes:0}})=>{for(const r of e.requests.splice(0))r.resolve(r.args[0].endsWith('/export')?{enabled:true}:archive)};
(async()=>{
 let e=setup();assert(e.requests.every(r=>r.args.length===1),'initial reads only');const old=e.requests.splice(0);
 e.run("S.selected='B';renderDetails();S.selected='A';renderDetails()");
 for(const r of old)r.resolve(r.args[0].endsWith('/export')?{enabled:true}:{recording_enabled:true,records:[{token:'OLD',source:'server'}]});await flush();
 assert(!JSON.stringify(e.get('archive-server')).includes('OLD'),'A→B→A drops stale URLs');reply(e);await flush();
 let action=e.get('archive-start').onclick(),write=e.requests.at(-1);assert.equal(write.args[0],'/api/cameras/A/archive');assert.equal(write.args[1],'POST');assert.deepEqual(JSON.parse(JSON.stringify(write.args[2])),{action:'record',enabled:true,segment_seconds:60,retention_days:7,max_bytes:10737418240});
 e.run("S.selected='B';renderDetails()");write.resolve({recording_enabled:true,records:[]});await action;assert(!e.get('archive-status').textContent.includes('Запись включена'));
 e=setup();reply(e,{recording_enabled:false,records:[{token:'safe_token',source:'server',lens:0,start:1,duration:10}],workers:[],jobs:[],storage:{count:1,bytes:20}});await flush();
 const files=JSON.stringify(e.get('archive-server'));assert(files.includes('/api/cameras/A/archive/file/safe_token'));assert(!files.includes('password'));
 const sd=e.get('archive-sd-refresh').onclick();assert(e.requests.at(-1).args[0].endsWith('/sd_dates'));e.requests.at(-1).resolve(['20261031']);await flush();assert(e.requests.at(-1).args[0].endsWith('/sd_records?date=20261031'));e.requests.at(-1).resolve([{id:'clip',filename:'clip',source:'sd',duration:30}]);await sd;
 assert(e.requests.filter(r=>r.args[1]==='POST').length===0,'SD listing never downloads');
 const buttons=e.get('archive-sd-records').children[0].children.filter(x=>typeof x.onclick==='function');assert.equal(buttons.length,1);
 const download=buttons[0].onclick();write=e.requests.at(-1);assert.equal(write.args[2].action,'sd_import');assert.equal(write.args[2].source_id,'clip');write.resolve({id:'job',state:'pending'});await download;
 e.run('showLogin()');assert.equal(e.get('archive-server').children.length,0);assert(e.get('archive-start').disabled);
 e=setup();reply(e);await flush();e.get('panel-services').hidden=true;e.intervals[0]();assert.equal(e.requests.length,0,'inactive panel does not poll');
 e=setup();reply(e,{records:[{token:'one',source:'server'}]});await flush();
 const replayButton=e.get('archive-server').children[0].children.find(x=>typeof x.onclick==='function');
 const replay=replayButton.onclick();e.requests.at(-1).resolve({uri:'rtsp://bridge:SECRET@host/replay'});await replay;
 assert(!e.get('archive-replay').textContent.includes('SECRET'),'replay never embeds credentials');
 const sdPending=e.get('archive-sd-refresh').onclick(),oldSD=e.requests.at(-1);
 e.run("S.selected='B';renderDetails();S.selected='A';renderDetails()");oldSD.resolve(['20261031']);await sdPending;
 assert.equal(e.get('archive-sd-records').children.length,0,'stale SD date response cannot issue follow-up record request');
 e=setup();reply(e,{records:[],storage:{retention_days:90,max_bytes:20971520},workers:[{segment_seconds:120}]});await flush();
 assert.equal(e.get('archive-retention').value,'90');assert.equal(e.get('archive-quota').value,'20');assert.equal(e.get('archive-segment').value,'120');
 e.get('archive-retention').value='30';e.intervals[0]();reply(e,{storage:{retention_days:90,max_bytes:20971520}});await flush();
 assert.equal(e.get('archive-retention').value,'30','polling preserves an edited policy');
 console.log('Frontend archive passed: read-only status, explicit recording/import, stale selection rejection, safe downloads, logout and inactive polling');
})().catch(error=>{console.error(error);process.exit(1)});
