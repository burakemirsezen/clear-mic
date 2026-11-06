const $ = id => document.getElementById(id);
const state = { ready:false, settings:{}, devices:{input:[],output:[]}, presets:{}, stats:{status:'stopped'}, previewReady:false, previewInfo:null, recording:false };
let saveTimer, saveChain = Promise.resolve(), commandBusy = false, lastError = '', playing = false;
const stageNames = {highpass:'Rumble cut',noise:'Noise removal',gate:'Noise gate',auto_level:'Automatic volume',compressor:'Compression',limiter:'Peak protection'};
const sliderDefinitions = [
  ['noise_strength','Noise strength',0,100,1,'%'],
  ['gate_threshold_db','Gate threshold',-75,-15,1,'dBFS'],
  ['highpass_hz','Rumble cut',40,160,1,'Hz'], ['threshold_db','Compression threshold',-40,-6,.5,'dB'],
  ['ratio','Compression ratio',1,6,.1,':1'], ['makeup_db','Speech boost',0,8,.1,'dB'],
  ['presence_db','Clarity EQ',-3,3,.1,'dB'], ['output_db','Output volume',-18,6,.1,'dB'],
  ['input_db','Input trim',-18,12,.1,'dB'], ['attack_ms','Compressor attack',1,50,1,'ms'],
  ['release_ms','Compressor release',50,500,5,'ms'], ['ceiling_db','Limiter ceiling',-6,-.5,.1,'dB'],
  ['gate_hold_ms','Gate hold',50,500,10,'ms'], ['gate_release_ms','Gate release',40,500,10,'ms']
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
for(const action of ['minimize','close','quit'])$(action).onclick=async()=>{
  if(action!=='minimize')await saveSettings().catch(()=>{});
  appAction(action).catch(()=>{});
};
$('data-folder').onclick=()=>{appAction('folder').catch(()=>{});};
$('source-link').onclick=()=>{appAction('source').catch(()=>{});};
$('driver-info').onclick=()=>{appAction('driver-info').catch(()=>{});};
$('driver-license').onclick=()=>{appAction('driver-license').catch(()=>{});};
$('driver-controls').onclick=()=>{appAction('driver-controls').catch(()=>{});};
function updateDriver() {
  const driver=state.driver||{}, endpoints=driver.endpoints||[];
  const available=driver.installed&&endpoints.some(e=>e.flow==='input')&&endpoints.some(e=>e.flow==='output');
  $('device-setup').hidden=Boolean(available);
  $('driver-state').textContent=available?'Clear Mic (VB-Audio) is ready':driver.installed?'Device installed — waiting for Windows endpoints':'Virtual microphone not created yet';
  $('create-device').disabled=Boolean(driver.foreign_vbcable||state.settingUp);
  $('remove-device').disabled=Boolean(!driver.installed||state.settingUp);
  $('driver-controls').disabled=Boolean(!driver.installed||!driver.buffer_samples||state.settingUp);
  $('check-driver').disabled=Boolean(state.settingUp);
  $('driver-detail').textContent=driver.buffer_samples?`Driver buffer: ${driver.buffer_samples} samples. Total delay also includes Windows and your receiving app.`:available?'Microphone ready. Restart Windows to enable the optional driver buffer controls.':'Powered by VB-Audio’s signed VB-CABLE driver.';
  $('create-device').textContent=state.settingUp?'Creating device…':driver.installed?'Repair microphone':'Create microphone';
  $('device-setup-title').textContent=driver.foreign_vbcable?'VB-CABLE is already installed':'Create your virtual microphone';
  $('device-setup-description').textContent=driver.foreign_vbcable?'Clear Mic will leave that existing cable untouched. You can still select it as an output.':driver.installed?'Windows may need a restart before the microphone becomes available.':'Clear Mic can create a dedicated microphone for your games and calls.';
  pairedName();
}
$('check-driver').onclick=async()=>{try{state.driver=await appAction('device-status');updateDriver();}catch{}};
$('create-device').onclick=async()=>{
  if(state.settingUp)return;
  state.settingUp=true;updateDriver();updateStatus();footer('Windows will request administrator permission to create the microphone.');
  try {
    await saveSettings();const result=await appAction('create-device');state.driver=result.driver;state.settings=result.snapshot.settings;state.devices=result.snapshot.devices;renderSettings();updateDriver();
    footer(result.driver.warning||(result.driver.endpoints.length>=2?'Your Clear Mic microphone is ready. Select it in your game or calling app.':'Driver installed. Restart Windows to finish creating the microphone.'));
  } catch {} finally { state.settingUp=false;updateDriver();updateStatus(); }
};
$('remove-device').onclick=async()=>{
  if(state.settingUp)return;
  state.settingUp=true;updateDriver();updateStatus();
  try {
    const result=await appAction('remove-device');
    if(!result.cancelled){state.driver=result.driver;state.settings=result.snapshot.settings;state.devices=result.snapshot.devices;renderSettings();footer('Virtual microphone removed. You can create it again at any time.');}
  } catch {} finally {state.settingUp=false;updateDriver();updateStatus();}
};
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
  input.value=state.settings.voice[name==='noise_strength'&&state.settings.engine==='fullband'?'fullband_strength':name];$('value-'+name).textContent=format(input.value,definition[5]);
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
  input.addEventListener('input',()=>{if(!state.ready)return;state.settings.voice[name==='noise_strength'&&state.settings.engine==='fullband'?'fullband_strength':name]=Number(input.value);state.settings.preset='Custom';updateSlider(name);updatePresets();scheduleSave();});
  input.addEventListener('change',()=>{if(state.ready)saveSettings().catch(()=>{});});
  const ends=document.createElement('div');ends.className='slider-ends';const a=document.createElement('span'),b=document.createElement('span');a.textContent=format(low,unit);b.textContent=format(high,unit);ends.append(a,b);
  control.append(heading,input,ends);$(index<8?'voice-sliders':'advanced-sliders').append(control);
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
  $('voice-guidance').textContent=state.settings.preset==='Singing'?'Singing preserves sustained notes and dynamics: speech noise removal, automatic volume and compression start off. Use Input trim for a fixed level. Speaker echo cancellation can remove backing tracks played by your selected PC speakers.':'Lower Noise strength for more voice detail; raise it to remove more keyboard and background sound. Natural speech starts at 90%. Automatic volume settles over a few seconds.';
  if(state.settings.engine==='fullband')$('voice-guidance').textContent='Full-band cleanup starts at 65% noise strength to retain voice detail. Lower it for a more natural voice; raise it for more isolation. Speaker echo cancellation uses your selected playback device.';
}
function updateChain() {
  $('chain-stages').replaceChildren();
  const neural=state.settings.engine&&state.settings.engine!=='classic';
  for(const [name,label] of Object.entries(stageNames)) {
    const enabled=name==='noise'&&neural?state.settings.engine==='fullband':Boolean(state.settings.voice[name]);
    const chip=document.createElement('span');chip.className='chain-chip'+(enabled?'':' off');chip.append(icon('check'),document.createTextNode(label));$('chain-stages').append(chip);
    $('stage-'+name).checked=enabled;
  }
  $('stage-noise').disabled=Boolean(neural);$('slider-noise_strength').disabled=Boolean(neural&&state.settings.engine!=='fullband');
  $('engine-guidance').textContent=state.settings.engine==='fullband'?'Keeps the 48 kHz voice range, including detail above 8 kHz. Playback echo removal and gentle neural noise reduction work together. Noise strength remains adjustable.':'Classic keeps 48 kHz voice detail and lets you adjust RNNoise. Compare it for singing or if you prefer less processing.';
}
function fillSelect(id,values,selected) {
  const select=$(id);select.replaceChildren();
  if(!values.length){const option=document.createElement('option');option.value='';option.textContent='No device found';select.append(option);}
  if(selected&&!values.includes(selected)){const option=document.createElement('option');option.value=selected;option.textContent=selected+' (unavailable — reconnect or choose another)';option.disabled=true;select.append(option);}
  if(!selected&&values.length){const option=document.createElement('option');option.value='';option.textContent='Choose a device';select.append(option);}
  for(const name of values){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}
  select.value=selected;
}
function physicalDevice(name) { return Boolean(name)&&!['clear mic','virtual','cable','voicemeeter','streaming'].some(w=>name.toLowerCase().includes(w)); }
function virtualOutput(name) { return ['streaming microphone','cable','voicemeeter','virtual','clear mic feed'].some(w=>name.toLowerCase().includes(w)); }
function previewReferenceProblem() {
  if(!state.previewReady||!state.settings.echo_cancel||!state.previewInfo)return '';
  if(!state.previewInfo.has_reference)return 'Record a new preview with speaker echo cancellation enabled.';
  if(state.previewInfo.speakers!==state.settings.speakers)return 'Speaker selection changed. Record a new preview with these speakers to compare echo cancellation.';
  return '';
}
function routeProblem() {
  if(!physicalDevice(state.settings.input)||!state.devices.input.includes(state.settings.input))return 'Your microphone is unavailable. Reconnect it and refresh devices, or choose another microphone.';
  if(!virtualOutput(state.settings.output||'')||!state.devices.output.includes(state.settings.output))return 'Choose an available virtual output, or create your Clear Mic microphone.';
  if(state.settings.echo_cancel&&(!physicalDevice(state.settings.speakers)||!state.devices.output.includes(state.settings.speakers)))return 'Your speakers are unavailable. Reconnect them and refresh devices, or choose another speaker device.';
  return '';
}
function pairedName() {
  const output=state.settings.output||'';
  let name='The paired virtual microphone';
  if(output.includes('Clear Mic (VB-Audio Virtual Cable)'))name=state.driver?.endpoints?.find(e=>e.flow==='input')?.name||'CABLE Output (Clear Mic (VB-Audio Virtual Cable))';
  else if(output.includes('Steam Streaming Microphone'))name=state.devices.input.find(n=>n.includes('Steam Streaming Microphone'))||'Microphone (Steam Streaming Microphone)';
  else if(/cable input/i.test(output))name=state.devices.input.find(n=>/cable output/i.test(n))||'CABLE Output';
  else if(/voicemeeter/i.test(output))name='The matching VoiceMeeter recording output';
  $('paired-device').textContent=name;
}
function renderSettings() {
  fillSelect('input-device',state.devices.input.filter(physicalDevice),state.settings.input);
  fillSelect('output-device',state.devices.output.filter(virtualOutput),state.settings.output);
  for(const [id,key] of [['listen-device','listen'],['speaker-device','speakers']])fillSelect(id,state.devices.output.filter(physicalDevice),state.settings[key]);
  $('echo-cancel').checked=Boolean(state.settings.echo_cancel);
  $('echo-mode').value=state.settings.echo_mode||'natural';
  $('voice-engine').value=state.settings.engine||'classic';
  $('preview-match').checked=Boolean(state.settings.preview_match);
  for(const definition of sliderDefinitions)updateSlider(definition[0]);
  $('auto-start').checked=state.settings.auto_start;$('minimize-tray').checked=state.settings.minimize_to_tray;
  updatePresets();updateChain();pairedName();
}
for(const [id,key] of [['input-device','input'],['output-device','output'],['listen-device','listen'],['speaker-device','speakers'],['echo-mode','echo_mode']])$(id).onchange=()=>{state.settings[key]=$(id).value;pairedName();updateStatus();saveSettings().catch(()=>{});};
$('voice-engine').onchange=()=>{state.settings.engine=$('voice-engine').value;updateSlider('noise_strength');updatePresets();updateChain();updateStatus();saveSettings().catch(()=>{});};
for(const [id,key] of [['auto-start','auto_start'],['minimize-tray','minimize_to_tray'],['echo-cancel','echo_cancel'],['preview-match','preview_match']])$(id).onchange=()=>{state.settings[key]=$(id).checked;updateStatus();saveSettings().catch(()=>{});};
$('launch-login').onchange=async()=>{try{$('launch-login').checked=await appAction('login',$('launch-login').checked);}catch{$('launch-login').checked=!$('launch-login').checked;}};
$('refresh').onclick=async()=>{try{await saveSettings();const data=await call('refresh');state.settings=data.settings;state.devices=data.devices;renderSettings();footer('Devices refreshed.');}catch{}};
$('toggle-mic').onclick=async()=>{
  if(commandBusy||!state.ready)return;commandBusy=true;updateStatus();
  try{await saveSettings();await call(['running','starting'].includes(state.stats.status)?'stop':'start');}catch{}finally{commandBusy=false;updateStatus();}
};
$('record-preview').onclick=async()=>{
  if(commandBusy)return;commandBusy=true;updateStatus();
  try{await saveSettings();await call('record');footer('Recording a five-second voice preview.');}catch{}finally{commandBusy=false;updateStatus();}
};
for(const [id,mode] of [['play-original','original'],['play-processed','processed']])$(id).onclick=async()=>{
  if(commandBusy)return;commandBusy=true;updateStatus();footer('Preparing your preview…');
  try{await saveSettings();await call('play',mode);playing=true;footer(`Playing your ${mode} recording.`);}catch{}finally{commandBusy=false;updateStatus();}
};
$('stop-playback').onclick=async()=>{try{await call('stop_playback');playing=false;footer('Preview playback stopped.');}catch{}};
function updateStatus() {
  const stats=state.stats, on=stats.status==='running', active=on||stats.status==='starting';
  $('status-pill').classList.toggle('on',on);document.querySelector('.hero').classList.toggle('active',on);
  $('status-text').textContent=on?'MICROPHONE ON':stats.status==='starting'?'CONNECTING…':stats.status==='error'?'AUDIO STOPPED':'MICROPHONE OFF';
  $('hero-title').textContent=on?'Your clean mic is live.':stats.status==='starting'?'Getting your mic ready…':'Ready when you are.';
  $('hero-description').textContent=on?(stats.routing_note||'Your voice is being sent to the virtual microphone.'):(routeProblem()||'Clean up background noise and keep your voice natural.');
  $('toggle-mic').classList.toggle('on',active);$('toggle-mic').querySelector('span').textContent=active?'Turn off microphone':'Turn on microphone';
  $('toggle-mic').disabled=!state.ready||state.recording||commandBusy||state.settingUp||(!active&&Boolean(routeProblem()));
  $('input-device').disabled=$('output-device').disabled=active||state.recording||state.settingUp;
  $('speaker-device').disabled=$('echo-cancel').disabled=active||state.recording||state.settingUp;
  $('echo-mode').disabled=active||state.recording||state.settingUp||!state.settings.echo_cancel;
  $('voice-engine').disabled=active||state.recording||state.settingUp||!state.ready;
  $('echo-mode-description').textContent=state.settings.echo_mode==='strong'?'Stronger echo suppression can muffle your voice during playback. Try Natural voice if it sounds robotic.':'Keeps more voice detail during playback. Some extra speaker bleed may remain, especially at high volume.';
  if(state.settings.engine==='fullband')$('echo-mode-description').textContent='Natural voice keeps your full voice, including consonants and air, while speakers play. Strong isolation removes more bleed but can muffle you when playback overlaps speech.';
  $('echo-status').textContent=on&&stats.echo_enabled?(stats.echo_processing?'Removing speaker echo · playback and room tail':'Echo stage transparent · speakers quiet'):'The device playing your games, music and calls. Safe to leave on with headphones.';
  $('refresh').disabled=active||state.recording||!state.ready||state.settingUp;
  $('record-preview').disabled=active||state.recording||commandBusy||!state.ready||state.settingUp||!physicalDevice(state.settings.input)||!state.devices.input.includes(state.settings.input)||(state.settings.echo_cancel&&(!physicalDevice(state.settings.speakers)||!state.devices.output.includes(state.settings.speakers)));
  $('create-device').disabled=Boolean(state.driver?.foreign_vbcable||state.settingUp||state.recording||commandBusy);
  $('remove-device').disabled=Boolean(!state.driver?.installed||state.settingUp||state.recording||commandBusy);
  $('record-preview').querySelector('span:last-child').textContent=state.recording?(state.remaining>0?`Recording… ${Math.ceil(state.remaining)}s`:'Finishing preview…'):'Record 5 seconds';
  const previewUnavailable=!state.previewReady||state.recording||active||commandBusy||!physicalDevice(state.settings.listen)||!state.devices.output.includes(state.settings.listen),referenceProblem=previewReferenceProblem();
  $('play-processed').disabled=previewUnavailable||Boolean(referenceProblem);
  $('play-original').disabled=previewUnavailable||Boolean(referenceProblem&&state.settings.preview_match);
  $('record-progress').hidden=!state.recording;$('record-progress').querySelector('span').style.width=`${Math.max(0,Math.min(100,100-state.remaining*20))}%`;
  $('signal-caption').textContent=on?'Live signal':'Waiting for audio';
  for(const name of ['input','output']) {
    const level=on?Math.max(-60,Math.min(0,stats[name+'_db'])):-60;
    $(name+'-db').textContent=on?`${Math.round(level)} dB`:'—';
    $(name+'-level').style.width=`${(level+60)/60*100}%`;$(name+'-level').classList.toggle('hot',level>-6);
  }
  $('processing').textContent=on?stats.mean_ms.toFixed(2)+' ms':'—';$('compression').textContent=on?stats.compressor_gr.toFixed(1)+' dB':'—';$('limiting').textContent=on?stats.limiter_gr.toFixed(1)+' dB':'—';
  $('dsp-delay').textContent=on&&Number.isFinite(stats.dsp_delay_ms)?stats.dsp_delay_ms.toFixed(1)+' ms':'—';
  $('automatic-gain').textContent=on?Number(stats.automatic_gain_db||0).toFixed(1)+' dB':'—';
  const gated=Boolean(state.settings.voice?.gate), reduction=Number(stats.gate_reduction_db||0);
  $('gate-status').textContent=!gated?'Noise gate is off. Enable it above to mute quiet noise between words.':on?`Gate input ${Math.round(stats.gate_input_db??-60)} dBFS · ${reduction>60?'Closed':reduction>.1?'Fading closed':'Open'}`:'Noise gate is enabled. Turn on the microphone to see its input level and open/closed state.';
  $('audio-warning').hidden=!(on&&(stats.clipped_samples||stats.warnings));$('audio-warning').textContent=stats.clipped_samples?'Input clipping detected. Lower the gain on your microphone.':`${stats.warnings||0} audio warning(s). Check your devices if sound drops out.`;
  if(stats.status==='error'&&stats.error!==lastError){lastError=stats.error;error(stats.error);}
  if(state.recording)$('preview-description').textContent=state.remaining>0?'Speak naturally, then try a few quiet and louder words.':'Finishing your recording and preparing the comparison.';
  else $('preview-description').textContent=state.previewReady?'Preview ready. Replaying Processed uses your current settings.':'Record five seconds, then compare your original and processed voice.';
  $('preview-source').hidden=!state.previewReady||!state.previewInfo;
  $('preview-source').textContent=state.previewInfo?`Recorded with ${state.previewInfo.input}. ${referenceProblem|| (state.previewInfo.input!==state.settings.input?'The selected microphone has changed; this preview is from the earlier microphone.':state.previewInfo.has_reference?'Speaker reference was captured for this preview.':'This preview was recorded without a speaker reference.')}`:'';
}
window.clearMic.subscribe(message=>{
  if(message.event==='status'){state.stats=message.stats;state.recording=message.recording;state.remaining=message.remaining;updateStatus();}
  if(message.event==='preview_started'){state.previewReady=false;state.previewInfo=null;state.recording=true;state.remaining=5;playing=false;updateStatus();}
  if(message.event==='preview_ready'){state.previewReady=true;state.previewInfo=message.preview_info||null;state.recording=false;footer('Preview ready. Compare Original and Processed.');updateStatus();}
  if(message.event==='error'||message.event==='fatal'){error(message.message);if(message.event==='fatal'){state.ready=false;state.stats={status:'error'};updateStatus();}}
});
async function boot() {
  try {
    const data=await appAction('boot');Object.assign(state,{settings:data.settings,devices:data.devices,presets:data.presets,previewReady:data.preview_ready,previewInfo:data.preview_info||null,ready:true,driver:data.virtual_device});
    $('version').textContent=data.version;$('launch-login').checked=data.launch_at_login;
    const descriptions={'Natural speech':'Gentle shaping. Your voice, just cleaner.','Even speech':'A steadier level for animated conversations.','Singing':'Preserve held notes, tone and dynamics.','Noise removal only':'Keep your mic character. Remove the noise.'};
    for(const name of Object.keys(state.presets)) {
      const card=document.createElement('button');card.className='preset-card';card.dataset.preset=name;
      const title=document.createElement('span');title.className='preset-name';title.textContent=name;
      const description=document.createElement('span');description.className='preset-description';description.textContent=descriptions[name];card.append(title,description,icon('check','preset-check'));
      card.onclick=()=>{state.settings.voice=structuredClone(state.presets[name]);state.settings.preset=name;renderSettings();saveSettings().catch(()=>{});};$('presets').append(card);
    }
    renderSettings();updateDriver();updateStatus();footer(data.notice||'Your voice is processed on this device.');
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
  const originalDevices=state.devices;
  const originalPreviewInfo=state.previewInfo,originalStats=state.stats;
  state.devices={input:['USB test mic'],output:['CABLE Input','Headphones']};
  state.settings={...initial,input:'Missing USB mic',output:'CABLE Input',listen:'Headphones',echo_cancel:false};
  renderSettings();updateStatus();
  const missingMicProtected=$('toggle-mic').disabled&&$('record-preview').disabled&&$('input-device').selectedOptions[0].textContent.includes('unavailable');
  state.settings.input='USB test mic';state.settings.output='Missing cable';renderSettings();updateStatus();
  const missingOutputProtected=$('toggle-mic').disabled&&!$('record-preview').disabled;
  state.settings.output='CABLE Input';state.settings.listen='CABLE Input';state.previewReady=true;renderSettings();updateStatus();
  const previewRouteProtected=$('play-original').disabled&&$('play-processed').disabled;
  state.settings.listen='Headphones';state.settings.speakers='Headphones';state.settings.echo_cancel=true;state.settings.preview_match=true;
  state.previewInfo={input:'USB test mic',speakers:'Earlier speakers',has_reference:true};updateStatus();
  const mismatchedReferenceProtected=$('play-original').disabled&&$('play-processed').disabled&&$('preview-source').textContent.includes('Speaker selection changed');
  state.settings.preview_match=false;updateStatus();
  const unmatchedOriginalAvailable=!$('play-original').disabled&&$('play-processed').disabled;
  state.stats={status:'running',mean_ms:2.1,input_db:-30,output_db:-28,compressor_gr:0,limiter_gr:0,dsp_delay_ms:60.96,echo_enabled:true,echo_processing:true};updateStatus();
  const delayClearlyReported=$('dsp-delay').textContent==='61.0 ms'&&$('processing').textContent==='2.10 ms'&&$('echo-status').textContent.startsWith('Removing speaker echo');
  state.previewReady=false;state.previewInfo=originalPreviewInfo;state.stats=originalStats;state.devices=originalDevices;state.settings=structuredClone(initial);renderSettings();updateStatus();
  const before=state.settings.voice.output_db;$('slider-output_db').value=-3;$('slider-output_db').dispatchEvent(new Event('input'));$('slider-output_db').dispatchEvent(new Event('change'));await saveChain;
  const saved=await call('snapshot');const savedSlider=saved.settings.voice.output_db===-3;
  $('slider-noise_strength').value=85;$('slider-noise_strength').dispatchEvent(new Event('input'));await saveSettings();
  const noiseStrengthSaved=(await call('snapshot')).settings.voice[state.settings.engine==='fullband'?'fullband_strength':'noise_strength']===85;
  $('stage-gate').checked=true;$('stage-gate').dispatchEvent(new Event('change'));
  $('slider-gate_threshold_db').value=-42;$('slider-gate_threshold_db').dispatchEvent(new Event('input'));
  $('slider-gate_hold_ms').value=180;$('slider-gate_hold_ms').dispatchEvent(new Event('input'));
  $('slider-gate_release_ms').value=160;$('slider-gate_release_ms').dispatchEvent(new Event('input'));await saveSettings();
  const gateVoice=(await call('snapshot')).settings.voice;
  const gateSaved=gateVoice.gate===1&&gateVoice.gate_threshold_db===-42&&gateVoice.gate_hold_ms===180&&gateVoice.gate_release_ms===160;
  $('preview-match').checked=false;$('preview-match').dispatchEvent(new Event('change'));await saveSettings();
  const comparisonSaved=(await call('snapshot')).settings.preview_match===false;
  $('stage-auto_level').checked=false;$('stage-auto_level').dispatchEvent(new Event('change'));await saveSettings();
  const levelSaved=(await call('snapshot')).settings.voice.auto_level===0;
  const speakerControls=Boolean($('speaker-device')&&$('echo-cancel'));
  $('voice-engine').value='fullband';$('voice-engine').dispatchEvent(new Event('change'));await saveSettings();
  const engineSaved=(await call('snapshot')).settings.engine==='fullband';
  const neuralNoiseHandled=$('stage-noise').disabled&&$('stage-noise').checked&&!$('slider-noise_strength').disabled;
  $('slider-noise_strength').value=37;$('slider-noise_strength').dispatchEvent(new Event('input'));await saveSettings();
  state.recording=true;updateStatus();const engineLocked=$('voice-engine').disabled;state.recording=false;
  $('voice-engine').value='classic';$('voice-engine').dispatchEvent(new Event('change'));await saveSettings();
  $('slider-noise_strength').value=82;$('slider-noise_strength').dispatchEvent(new Event('input'));await saveSettings();
  const independentVoice=(await call('snapshot')).settings.voice;
  $('voice-engine').value='fullband';$('voice-engine').dispatchEvent(new Event('change'));await saveSettings();
  const noiseStrengthIndependent=independentVoice.fullband_strength===37&&independentVoice.noise_strength===82&&Number($('slider-noise_strength').value)===37;
  $('voice-engine').value='classic';$('voice-engine').dispatchEvent(new Event('change'));await saveSettings();
  $('echo-mode').value='strong';$('echo-mode').dispatchEvent(new Event('change'));await saveSettings();
  const echoModeSaved=(await call('snapshot')).settings.echo_mode==='strong';
  state.recording=true;updateStatus();const echoModeLocked=$('echo-mode').disabled;state.recording=false;
  document.querySelector('[data-preset="Even speech"]').click();await saveChain;const presetSaved=(await call('snapshot')).settings.preset==='Even speech';
  document.querySelector('[data-preset="Singing"]').click();await saveChain;
  const singing=(await call('snapshot')).settings;
  const singingSaved=singing.preset==='Singing'&&singing.voice.noise===0&&singing.voice.auto_level===0&&singing.voice.compressor===0&&singing.voice.limiter===1;
  state.settings=initial;renderSettings();await saveSettings();
  const originalDriver=state.driver;
  state.driver={installed:false,foreign_vbcable:false,endpoints:[]};updateDriver();updateStatus();
  const setupVisible=!$('device-setup').hidden&&!$('create-device').disabled;
  const setupPages=window.checkLayout();
  state.driver={installed:false,foreign_vbcable:true,endpoints:[]};updateDriver();updateStatus();
  const foreignProtected=$('create-device').disabled;
  state.driver=originalDriver;updateDriver();updateStatus();
  const sizes=window.checkLayout();
  return {pass:mismatchedReferenceProtected&&unmatchedOriginalAvailable&&delayClearlyReported&&noiseStrengthIndependent&&engineSaved&&engineLocked&&neuralNoiseHandled&&gateSaved&&echoModeSaved&&echoModeLocked&&missingMicProtected&&missingOutputProtected&&previewRouteProtected&&savedSlider&&noiseStrengthSaved&&comparisonSaved&&levelSaved&&speakerControls&&presetSaved&&singingSaved&&setupVisible&&foreignProtected&&[...sizes,...setupPages].every(s=>s.noHorizontalOverflow&&s.contentVisible),mismatchedReferenceProtected,unmatchedOriginalAvailable,delayClearlyReported,noiseStrengthIndependent,engineSaved,engineLocked,neuralNoiseHandled,gateSaved,echoModeSaved,echoModeLocked,missingMicProtected,missingOutputProtected,previewRouteProtected,savedSlider,noiseStrengthSaved,comparisonSaved,levelSaved,speakerControls,presetSaved,singingSaved,setupVisible,foreignProtected,setupPages,pages:sizes,audioStatus:state.stats.status,previewRecorded:state.previewReady};
};
boot();
