const $ = id => document.getElementById(id);
const state = { ready:false, settings:{}, devices:{input:[],output:[]}, presets:{}, stats:{status:'stopped'}, previewReady:false, recording:false };
let saveTimer, saveChain = Promise.resolve(), commandBusy = false, lastError = '', playing = false;
const stageNames = {noise:'Noise removal',highpass:'Rumble cut',compressor:'Compression',limiter:'Peak protection'};
const sliderDefinitions = [
  ['highpass_hz','Rumble cut',40,160,1,'Hz'], ['threshold_db','Compression threshold',-40,-6,.5,'dB'],
  ['ratio','Compression ratio',1,6,.1,':1'], ['makeup_db','Speech boost',0,8,.1,'dB'],
  ['presence_db','Clarity EQ',-3,3,.1,'dB'], ['output_db','Output volume',-18,6,.1,'dB'],
  ['input_db','Input trim',-18,12,.1,'dB'], ['attack_ms','Compressor attack',1,50,1,'ms'],
  ['release_ms','Compressor release',50,500,5,'ms'], ['ceiling_db','Limiter ceiling',-6,-.5,.1,'dB']
];
function icon(name, className='') { const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); const use=document.createElementNS(svg.namespaceURI,'use');use.setAttribute('href','#'+name);svg.append(use);if(className)svg.setAttribute('class',className);return svg; }
function error(message) { $('error-text').textContent=message;$('error').hidden=false; }
function footer(message) { $('footer-message').textContent=message; }
async function call(action,value) { try { return await window.clearMic.request(action,value); } catch(e) { error(e.message.replace(/^Error invoking remote method '[^']+': Error: /,''));throw e; } }
async function appAction(action,value) { try{return await window.clearMic.app(action,value);}catch(e){error(e.message.replace(/^Error invoking remote method '[^']+': Error: /,''));throw e;} }
function selectPage(name) {
  document.querySelectorAll('.page').forEach(page=>page.classList.toggle('active',page.id==='page-'+name));
  document.querySelectorAll('.nav').forEach(button=>{const active=button.dataset.page===name;button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');});
  document.querySelector('main').scrollTop=0;
}
window.selectPage=selectPage;
document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>selectPage(button.dataset.page)));
$('preset-shortcut').onclick=$('tune-voice').onclick=()=>selectPage('voice');
$('dismiss-error').onclick=()=>{$('error').hidden=true;};
for(const action of ['minimize','close','quit'])$(action).onclick=()=>{appAction(action).catch(()=>{});};
$('data-folder').onclick=()=>{appAction('folder').catch(()=>{});};
$('source-link').onclick=()=>{appAction('source').catch(()=>{});};
function saveSettings() {
  clearTimeout(saveTimer);saveTimer=null;
  if(!state.ready)return saveChain;
  const snapshot=structuredClone(state.settings);$('save-status').textContent='Saving…';
  saveChain=saveChain.catch(()=>{}).then(()=>call('configure',snapshot)).then(()=>{$('save-status').textContent='All changes saved';},e=>{$('save-status').textContent='Changes could not be saved';throw e;});
  return saveChain;
}
function scheduleSave() { clearTimeout(saveTimer);$('save-status').textContent='Saving…';saveTimer=setTimeout(()=>{saveSettings().catch(()=>{});},180); }
function format(value,unit) { if(unit===':1')return Number(value).toFixed(1)+':1';return (unit==='Hz'||unit==='ms'?Math.round(value):Number(value).toFixed(1))+' '+unit; }
function updateSlider(name) {
  const input=$('slider-'+name), definition=sliderDefinitions.find(item=>item[0]===name);
  input.value=state.settings.voice[name];$('value-'+name).textContent=format(input.value,definition[5]);
  const amount=(Number(input.value)-Number(input.min))/(Number(input.max)-Number(input.min))*100;
  input.style.background=`linear-gradient(to right, #88c8b1 ${amount}%, #354047 ${amount}%)`;
}
for(const [index,[name,label,low,high,step,unit]] of sliderDefinitions.entries()) {
  const control=document.createElement('div');control.className='slider-control';
  const heading=document.createElement('div');heading.className='slider-heading';
  const text=document.createElement('label');text.htmlFor='slider-'+name;text.textContent=label;
  const value=document.createElement('output');value.id='value-'+name;value.className='slider-value';value.htmlFor='slider-'+name;
  heading.append(text,value);
  const input=document.createElement('input');input.type='range';input.min=low;input.max=high;input.step=step;input.id='slider-'+name;
  input.addEventListener('input',()=>{if(!state.ready)return;state.settings.voice[name]=Number(input.value);state.settings.preset='Custom';updateSlider(name);updatePresets();scheduleSave();});
  const ends=document.createElement('div');ends.className='slider-ends';const a=document.createElement('span'),b=document.createElement('span');a.textContent=format(low,unit);b.textContent=format(high,unit);ends.append(a,b);
  control.append(heading,input,ends);$(index<6?'voice-sliders':'advanced-sliders').append(control);
}
for(const [name,label] of Object.entries(stageNames)) {
  const group=document.createElement('div');group.className='stage-toggle';
  const text=document.createElement('label');text.textContent=label;text.htmlFor='stage-'+name;
  const toggle=document.createElement('label');toggle.className='switch';
  const input=document.createElement('input');input.type='checkbox';input.id='stage-'+name;input.setAttribute('aria-label',label);input.onchange=()=>{state.settings.voice[name]=Number(input.checked);state.settings.preset='Custom';updatePresets();updateChain();scheduleSave();};
  toggle.append(input,document.createElement('span'));group.append(text,toggle);$('stages').append(group);
}
function updatePresets() {
  document.querySelectorAll('.preset-card').forEach(card=>{const selected=card.dataset.preset===state.settings.preset;card.classList.toggle('selected',selected);card.setAttribute('aria-pressed',String(selected));});
  $('current-preset').textContent=$('voice-preset-badge').textContent=state.settings.preset;
}
function updateChain() {
  $('chain-stages').replaceChildren();
  for(const [name,label] of Object.entries(stageNames)) {
    const chip=document.createElement('span');chip.className='chain-chip'+(state.settings.voice[name]?'':' off');chip.append(icon('check'),document.createTextNode(label));$('chain-stages').append(chip);
    $('stage-'+name).checked=Boolean(state.settings.voice[name]);
  }
}
function fillSelect(id,values,selected) {
  const select=$(id);select.replaceChildren();
  if(!values.length){const option=document.createElement('option');option.value='';option.textContent='No device found';select.append(option);}
  if(selected&&!values.includes(selected))values=[selected,...values];
  if(!selected&&values.length){const option=document.createElement('option');option.value='';option.textContent='Choose a virtual output';select.append(option);}
  for(const name of values){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}
  select.value=selected;
}
function pairedName() {
  const output=state.settings.output||'';
  let name='The paired virtual microphone';
  if(output.includes('Steam Streaming Microphone'))name=state.devices.input.find(n=>n.includes('Steam Streaming Microphone'))||'Microphone (Steam Streaming Microphone)';
  else if(/cable input/i.test(output))name=state.devices.input.find(n=>/cable output/i.test(n))||'CABLE Output';
  else if(/voicemeeter/i.test(output))name='The matching VoiceMeeter recording output';
  $('paired-device').textContent=name;
}
function renderSettings() {
  for(const [id,key,type] of [['input-device','input','input'],['output-device','output','output'],['listen-device','listen','output']])fillSelect(id,state.devices[type],state.settings[key]);
  for(const definition of sliderDefinitions)updateSlider(definition[0]);
  $('auto-start').checked=state.settings.auto_start;$('minimize-tray').checked=state.settings.minimize_to_tray;
  updatePresets();updateChain();pairedName();
}
for(const [id,key] of [['input-device','input'],['output-device','output'],['listen-device','listen']])$(id).onchange=()=>{state.settings[key]=$(id).value;pairedName();saveSettings().catch(()=>{});};
for(const [id,key] of [['auto-start','auto_start'],['minimize-tray','minimize_to_tray']])$(id).onchange=()=>{state.settings[key]=$(id).checked;saveSettings().catch(()=>{});};
$('launch-login').onchange=async()=>{try{$('launch-login').checked=await appAction('login',$('launch-login').checked);}catch{$('launch-login').checked=!$('launch-login').checked;}};
$('refresh').onclick=async()=>{try{await saveSettings();const data=await call('refresh');state.settings=data.settings;state.devices=data.devices;renderSettings();footer('Devices refreshed.');}catch{}};
$('toggle-mic').onclick=async()=>{
  if(commandBusy||!state.ready)return;commandBusy=true;updateStatus();
  try{await saveSettings();await call(['running','starting'].includes(state.stats.status)?'stop':'start');}catch{}finally{commandBusy=false;updateStatus();}
};
$('record-preview').onclick=async()=>{try{await saveSettings();await call('record');footer('Recording a five-second voice preview.');}catch{}};
for(const [id,mode] of [['play-original','original'],['play-processed','processed']])$(id).onclick=async()=>{try{await saveSettings();await call('play',mode);playing=true;footer(`Playing your ${mode} recording.`);}catch{}};
$('stop-playback').onclick=async()=>{try{await call('stop_playback');playing=false;footer('Preview playback stopped.');}catch{}};
function updateStatus() {
  const stats=state.stats, on=stats.status==='running', active=on||stats.status==='starting';
  $('status-pill').classList.toggle('on',on);document.querySelector('.hero').classList.toggle('active',on);
  $('status-text').textContent=on?'MICROPHONE ON':stats.status==='starting'?'CONNECTING…':stats.status==='error'?'AUDIO STOPPED':'MICROPHONE OFF';
  $('hero-title').textContent=on?'Your clean mic is live.':stats.status==='starting'?'Getting your mic ready…':'Ready when you are.';
  $('hero-description').textContent=on?'Your voice is being sent to the virtual microphone.':'Clean up background noise and keep your voice natural.';
  $('toggle-mic').classList.toggle('on',active);$('toggle-mic').querySelector('span').textContent=active?'Turn off microphone':'Turn on microphone';
  $('toggle-mic').disabled=!state.ready||state.recording||commandBusy;
  $('input-device').disabled=$('output-device').disabled=active||state.recording;
  $('refresh').disabled=active||state.recording||!state.ready;
  $('record-preview').disabled=active||state.recording||!state.ready;
  $('record-preview').querySelector('span:last-child').textContent=state.recording?`Recording… ${Math.ceil(state.remaining)}s`:'Record 5 seconds';
  $('play-original').disabled=$('play-processed').disabled=!state.previewReady||state.recording||active;
  $('record-progress').hidden=!state.recording;$('record-progress').querySelector('span').style.width=`${Math.max(0,Math.min(100,100-state.remaining*20))}%`;
  $('signal-caption').textContent=on?'Live signal':'Waiting for audio';
  for(const name of ['input','output']) {
    const level=on?Math.max(-60,Math.min(0,stats[name+'_db'])):-60;
    $(name+'-db').textContent=on?`${Math.round(level)} dB`:'—';
    $(name+'-level').style.width=`${(level+60)/60*100}%`;$(name+'-level').classList.toggle('hot',level>-6);
  }
  $('processing').textContent=on?stats.mean_ms.toFixed(2)+' ms':'—';$('compression').textContent=on?stats.compressor_gr.toFixed(1)+' dB':'—';$('limiting').textContent=on?stats.limiter_gr.toFixed(1)+' dB':'—';
  $('audio-warning').hidden=!(on&&(stats.clipped_samples||stats.warnings));$('audio-warning').textContent=stats.clipped_samples?'Input clipping detected. Lower the gain on your microphone.':`${stats.warnings||0} audio warning(s). Check your devices if sound drops out.`;
  if(stats.status==='error'&&stats.error!==lastError){lastError=stats.error;error(stats.error);}
  if(state.recording)$('preview-description').textContent='Speak naturally, then try a few quiet and louder words.';
  else $('preview-description').textContent=state.previewReady?'Preview ready. Replaying Processed uses your current settings.':'Record five seconds, then compare your original and processed voice.';
}
window.clearMic.subscribe(message=>{
  if(message.event==='status'){state.stats=message.stats;state.recording=message.recording;state.remaining=message.remaining;updateStatus();}
  if(message.event==='preview_ready'){state.previewReady=true;footer('Preview ready. Compare Original and Processed.');updateStatus();}
  if(message.event==='error'||message.event==='fatal'){error(message.message);if(message.event==='fatal'){state.ready=false;state.stats={status:'error'};updateStatus();}}
});
async function boot() {
  try {
    const data=await appAction('boot');Object.assign(state,{settings:data.settings,devices:data.devices,presets:data.presets,previewReady:data.preview_ready,ready:true});
    $('version').textContent=data.version;$('launch-login').checked=data.launch_at_login;
    const descriptions={'Natural speech':'Gentle shaping. Your voice, just cleaner.','Even speech':'A steadier level for animated conversations.','Noise removal only':'Keep your mic character. Remove the noise.'};
    for(const name of Object.keys(state.presets)) {
      const card=document.createElement('button');card.className='preset-card';card.dataset.preset=name;
      const title=document.createElement('span');title.className='preset-name';title.textContent=name;
      const description=document.createElement('span');description.className='preset-description';description.textContent=descriptions[name];card.append(title,description,icon('check','preset-check'));
      card.onclick=()=>{state.settings.voice=structuredClone(state.presets[name]);state.settings.preset=name;renderSettings();saveSettings().catch(()=>{});};$('presets').append(card);
    }
    renderSettings();updateStatus();footer('Your voice is processed on this device.');
  } catch(e){error('Could not connect to the audio service. Restart Clear Mic.');}
}
window.checkLayout=()=>{
  const sizes=[];
  for(const page of ['microphone','voice','settings']) {
    selectPage(page);const pane=$('page-'+page);sizes.push({page,noHorizontalOverflow:pane.scrollWidth<=pane.clientWidth+1,contentVisible:pane.getBoundingClientRect().width>400});
  }
  return sizes;
};
window.runUiChecks=async()=>{
  if(!state.ready)throw new Error('Audio service not ready');
  const initial=structuredClone(state.settings);
  const before=state.settings.voice.output_db;$('slider-output_db').value=-3;$('slider-output_db').dispatchEvent(new Event('input'));await saveSettings();
  const saved=await call('snapshot');const savedSlider=saved.settings.voice.output_db===-3;
  document.querySelector('[data-preset="Even speech"]').click();await saveChain;const presetSaved=(await call('snapshot')).settings.preset==='Even speech';
  state.settings=initial;renderSettings();await saveSettings();
  const sizes=window.checkLayout();
  return {pass:savedSlider&&presetSaved&&sizes.every(s=>s.noHorizontalOverflow&&s.contentVisible),savedSlider,presetSaved,pages:sizes,audioStatus:state.stats.status,previewRecorded:state.previewReady};
};
boot();
