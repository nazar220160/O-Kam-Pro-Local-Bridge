// Archive reads never start recording or download camera SD video.
(() => {
  const A = {id:null,epoch:-1,generation:0,request:0,sdRequest:0,busy:false,loading:false,sdBusy:false,recording:false,exported:false,policyLoaded:false};
  const el = name => $('archive-' + name);
  const camera = () => S.cameras.find(c=>c.id===S.selected);
  const active = () => !document.hidden && !$('panel-services').hidden;
  const context = () => ({id:A.id,epoch:S.epoch,generation:A.generation});
  const current = c => !!S.username && S.selected===c.id && S.epoch===c.epoch && A.generation===c.generation;
  const path = c => '/api/cameras/' + encodeURIComponent(c.id) + '/archive';
  const text = (tag,value) => {const n=document.createElement(tag);n.textContent=value;return n};
  function reset() {
    A.generation++;A.request++;A.sdRequest++;A.busy=A.loading=A.sdBusy=A.recording=A.exported=A.policyLoaded=false;
    for(const name of ['server','cache','jobs','sd-date','sd-records'])el(name).replaceChildren();
    for(const name of ['status','workers','replay'])el(name).textContent='';
    el('sd-status').textContent='Нажмите «Проверить SD», чтобы запросить список с камеры.';
    el('segment').value='60';el('retention').value='7';el('quota').value='10240';el('duration').value='30';
  }
  function render() {
    const ready=!!S.username && !!camera()?.viewable,blocked=A.busy||A.loading;
    el('start').disabled=!ready||!A.exported||blocked;
    el('stop').disabled=!S.username||!A.recording||blocked;
    el('refresh').disabled=!S.username||!A.id||blocked;
    el('sd-refresh').disabled=!ready||!A.exported||blocked||A.sdBusy;
    el('sd-date').disabled=!ready||!A.exported||blocked||A.sdBusy;
    for(const name of ['segment','retention','quota','duration'])el(name).disabled=A.busy;
  }
  function validNumber(name,min,max) {
    const value=Number(el(name).value);
    if(!Number.isInteger(value)||value<min||value>max)throw new Error('range');
    return value;
  }
  function safeReplay(value) {
    try {const u=new URL(value);return ['rtsp:','rtsps:'].includes(u.protocol)&&!u.username&&!u.password&&!u.search&&!u.hash?u.href:''}catch{return ''}
  }
  async function command(payload,after) {
    if(!S.username||!A.id||A.busy||A.loading)return;
    const c=context();A.busy=true;A.request++;render();
    try {const result=await api(path(c),'POST',payload);if(current(c)){if(after)after(result,c);else el('status').textContent='Команда принята.'}}
    catch(error){if(current(c))el('status').textContent=friendly(error.code)}
    finally {if(current(c)){A.busy=false;render();if(payload.action!=='replay')void refresh()}}
  }
  function records(data) {
    el('server').replaceChildren();el('cache').replaceChildren();
    const c=context();
    for(const r of data.records||[]) {
      if(typeof r.token!=='string'||!r.token||r.token.length>256)continue;
      const row=document.createElement('div');row.className='archive-record';
      row.append(text('span','Линза '+(Number(r.lens||0)+1)+' · '+String(r.start??'')+' · '+String(r.duration??'?')+' с'));
      const file=document.createElement('a');file.textContent='Скачать MKV';file.href=path(c)+'/file/'+encodeURIComponent(r.token);file.download='recording.mkv';
      const replay=text('button','RTSP-повтор');replay.type='button';replay.className='text-button';
      replay.onclick=()=>{if(!current(c))return;return command({action:'replay',token:r.token},result=>{const uri=safeReplay(result.uri);el('replay').textContent=uri?'Адрес RTSP-повтора: '+uri:'Сервер не вернул безопасный адрес повтора.'})};
      row.append(file,replay);el(r.source==='sd'?'cache':'server').append(row);
    }
    for(const name of ['server','cache'])if(!el(name).children.length)el(name).append(text('p','Записей пока нет.'));
  }
  function show(data) {
    if(!A.policyLoaded) {
      if(Number.isInteger(data.storage?.retention_days))el('retention').value=String(data.storage.retention_days);
      if(Number.isInteger(data.storage?.max_bytes))el('quota').value=String(Math.ceil(data.storage.max_bytes/1048576));
      if(Number.isInteger(data.workers?.[0]?.segment_seconds))el('segment').value=String(data.workers[0].segment_seconds);
      A.policyLoaded=true;
    }
    A.recording=!!data.recording_enabled;
    el('status').textContent=(A.recording?'Запись включена.':'Запись выключена.')+' На диске: '+Number(data.storage?.count||0)+' файлов, '+Math.round(Number(data.storage?.bytes||0)/1048576)+' МиБ.'+(!A.exported?' Для записи включите экспорт моста.':'');
    el('workers').textContent=(data.workers||[]).map(w=>'Линза '+(Number(w.lens||0)+1)+': '+(w.error?'ошибка '+String(w.error):w.running?'записывается':'остановлена')).join(' · ');
    records(data);el('jobs').replaceChildren();
    const states={pending:'в очереди',downloading:'скачивается',completed:'завершено',error:'ошибка',cancelled:'отменено'};
    for(const job of data.jobs||[])el('jobs').append(text('p','Задание '+String(job.id)+': '+(states[job.state]||'неизвестно')+(job.error?' · '+String(job.error):'')));
  }
  async function refresh() {
    if(!active()||!S.username||!A.id||A.busy||A.loading)return;
    const c=context(),request=++A.request;A.loading=true;render();
    try {const [data,status]=await Promise.all([api(path(c)),api('/api/cameras/'+encodeURIComponent(c.id)+'/export')]);if(current(c)&&request===A.request){A.exported=!!status.enabled;show(data)}}
    catch(error){if(current(c)&&request===A.request)el('status').textContent=friendly(error.code)}
    finally {if(current(c)&&request===A.request){A.loading=false;render()}}
  }
  function sync() {
    if(A.id!==S.selected||A.epoch!==S.epoch){reset();A.id=S.selected;A.epoch=S.epoch;render();void refresh()}
    else render();
  }
  el('start').onclick=()=>{
    if(!camera()?.viewable||!A.exported)return;
    try{return command({action:'record',enabled:true,segment_seconds:validNumber('segment',5,3600),retention_days:validNumber('retention',1,365),max_bytes:validNumber('quota',1,1048576)*1048576})}
    catch{el('status').textContent='Проверьте длину сегмента (5–3600 с), хранение (1–365 дней) и лимит (1–1048576 МиБ).'}
  };
  el('stop').onclick=()=>command({action:'record',enabled:false});
  el('refresh').onclick=refresh;
  function showSD(list,c) {
    el('sd-records').replaceChildren();
    for(const r of list) {
      if(typeof r.id!=='string')continue;
      const row=document.createElement('div');row.className='archive-record';row.append(text('span',String(r.filename||r.id)+' · '+String(r.start||r.timestamp||'')+' · '+String(r.duration??'?')+' с'));
      const button=text('button','Скачать в архив моста');button.type='button';button.className='text-button';
      button.onclick=()=>{if(!current(c)||!camera()?.viewable)return;try{return command({action:'sd_import',source_id:r.id,duration:validNumber('duration',1,300)},()=>{el('sd-status').textContent='Задание скачивания добавлено. Статус появится в списке заданий.'})}catch{el('sd-status').textContent='Укажите длительность 1–300 секунд.'}};
      row.append(button);el('sd-records').append(row);
    }
    el('sd-status').textContent=list.length?'Список SD получен. Скачивание запускается только кнопкой выбранного фрагмента.':'За эту дату записей нет.';
  }
  async function loadSD(dates) {
    if(!S.username||!A.id||!camera()?.viewable||A.sdBusy)return;
    const c=context(),request=++A.sdRequest;A.sdBusy=true;render();el('sd-status').textContent='Запрашиваем архив SD…';
    try {
      if(dates) {
        const values=await api(path(c)+'/sd_dates');if(!current(c)||request!==A.sdRequest)return;
        el('sd-date').replaceChildren();
        const days=(Array.isArray(values)?values:values.dates||[]).filter(v=>/^\d{8}$/.test(v)).sort().reverse();
        for(const day of days){const option=text('option',day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6));option.value=day;el('sd-date').append(option)}
        el('sd-date').value=days[0]||'';
      }
      const day=el('sd-date').value;if(!/^\d{8}$/.test(day)){el('sd-status').textContent='Камера не вернула даты архива SD.';el('sd-records').replaceChildren();return}
      const result=await api(path(c)+'/sd_records?date='+day);
      if(current(c)&&request===A.sdRequest)showSD(Array.isArray(result)?result:result.records||[],c);
    } catch(error){if(current(c)&&request===A.sdRequest)el('sd-status').textContent=friendly(error.code)}
    finally{if(current(c)&&request===A.sdRequest){A.sdBusy=false;render()}}
  }
  el('sd-refresh').onclick=()=>loadSD(true);el('sd-date').onchange=()=>loadSD(false);
  const baseRender=renderDetails;renderDetails=function(...args){const result=baseRender.apply(this,args);sync();return result};
  const baseLogin=showLogin;showLogin=function(...args){reset();const result=baseLogin.apply(this,args);sync();return result};
  const baseTab=activateTab;activateTab=function(...args){const result=baseTab.apply(this,args);if(args[0]==='services'){sync();void refresh()}return result};
  document.addEventListener('visibilitychange',()=>{if(active()){sync();void refresh()}});
  setInterval(()=>{sync();if(active())void refresh()},5000);sync();
})();
