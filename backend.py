"""Local JSON-line control channel. Audio remains in the native callback thread."""
import json,sys,queue,threading,time,logging
from dataclasses import asdict
import sounddevice as sd
import soundfile as sf
from clear_mic.paths import initialize,DATA
from clear_mic.settings import Voice,PRESETS,load,save,voice_from
from clear_mic.audio_service import AudioService,devices,resolve,record_preview,process_clip,com_apartment
from clear_mic.processor import RATE

class Backend:
    def __init__(self):
        self.service=AudioService();self.requests=queue.Queue();self.preview=None;self.busy=False;self.record_until=0
        stored=load()
        if not isinstance(stored,dict):stored={}
        try:voice=voice_from(stored.get('voice',{}))
        except (ValueError,TypeError,AttributeError):voice=Voice()
        self.settings={'input':stored.get('input',''),'output':stored.get('output',''),'listen':stored.get('listen',''),'voice':asdict(voice),'preset':stored.get('preset','Natural speech'),'auto_start':bool(stored.get('auto_start',False)),'minimize_to_tray':bool(stored.get('minimize_to_tray',True))}
        self.inventory={};self.refresh()
    def emit(self,value):
        print(json.dumps(value,allow_nan=False),flush=True)
    def refresh(self):
        if self.service.active or self.busy:raise ValueError('Stop the microphone before refreshing devices.')
        sd.stop();sd._terminate();sd._initialize();self.inventory=devices()
        inputs=[n for n,i in self.inventory['input']];outputs=[n for n,i in self.inventory['output']]
        if self.settings['input'] not in inputs:self.settings['input']=next((n for n in inputs if not any(w in n.lower() for w in ('virtual','cable','streaming'))),inputs[0] if inputs else '')
        if self.settings['output'] not in outputs:self.settings['output']=next((n for n in outputs if 'Steam Streaming Microphone' in n),next((n for n in outputs if any(w in n.lower() for w in ('cable','voicemeeter','virtual'))),''))
        if self.settings['listen'] not in outputs:
            default=next((a['default_output_device'] for a in sd.query_hostapis() if a['name']=='Windows WASAPI'),-1)
            self.settings['listen']=next((n for n,i in self.inventory['output'] if i==default),outputs[0] if outputs else '')
        return self.snapshot()
    def snapshot(self):
        return {'settings':self.settings,'devices':{k:[n for n,i in v] for k,v in self.inventory.items()},'presets':{k:asdict(v) for k,v in PRESETS.items()},'preview_ready':self.preview is not None}
    def configure(self,value):
        if not isinstance(value,dict):raise ValueError('Invalid settings')
        result=self.settings.copy()
        for key in ('input','output','listen','preset'):
            if key in value:
                if not isinstance(value[key],str):raise ValueError('Invalid device or preset')
                result[key]=value[key]
        if self.service.active and any(result[k]!=self.settings[k] for k in ('input','output')):raise ValueError('Stop the microphone before changing routing.')
        for key in ('auto_start','minimize_to_tray'):
            if key in value:result[key]=bool(value[key])
        if 'voice' in value:result['voice']=asdict(voice_from(value['voice']))
        save(result);self.settings=result;self.service.configure(voice_from(result['voice']))
        return self.settings
    def start(self):
        if self.busy:raise ValueError('Wait for the preview recording to finish.')
        sd.stop();self.service.start(self.settings['input'],self.settings['output'],voice_from(self.settings['voice']))
    def record(self):
        if self.service.active or self.busy:raise ValueError('Stop the live microphone before recording a preview.')
        sd.stop();self.busy=True;self.record_until=time.monotonic()+5
        name=self.settings['input'];voice=voice_from(self.settings['voice'])
        def capture():
            try:
                raw=record_preview(name);processed=process_clip(raw,voice);stamp=str(time.time_ns())
                sf.write(DATA/'previews'/f'{stamp}-original.wav',raw,RATE,subtype='FLOAT');sf.write(DATA/'previews'/f'{stamp}-processed.wav',processed,RATE,subtype='FLOAT')
                self.requests.put({'internal':'preview','raw':raw})
            except Exception as e:self.requests.put({'internal':'preview_error','message':str(e)})
        self.preview_thread=threading.Thread(target=capture,daemon=True);self.preview_thread.start()
    def handle(self,message):
        if not isinstance(message,dict):raise ValueError('Invalid request')
        if 'internal' in message:
            self.busy=False
            if message['internal']=='preview':self.preview=message['raw'];self.emit({'event':'preview_ready'})
            else:self.emit({'event':'error','message':message['message']})
            return True
        action=message.get('action');value=message.get('value')
        if action=='snapshot':result=self.snapshot()
        elif action=='refresh':result=self.refresh()
        elif action=='configure':result=self.configure(value)
        elif action=='start':self.start();result=True
        elif action=='stop':self.service.stop();result=True
        elif action=='record':self.record();result=True
        elif action=='play':
            if self.preview is None or self.busy or self.service.active:raise ValueError('Record a preview and stop the live microphone first.')
            if value not in ('original','processed'):raise ValueError('Invalid playback mode')
            audio=process_clip(self.preview,voice_from(self.settings['voice'])) if value=='processed' else self.preview
            sd.stop();sd.play(audio,samplerate=RATE,device=resolve(self.settings['listen'],'output'),extra_settings=sd.WasapiSettings(auto_convert=True));result=True
        elif action=='stop_playback':sd.stop();result=True
        elif action=='quit':self.emit({'id':message.get('id'),'result':True});return False
        else:raise ValueError('Unknown action')
        self.emit({'id':message.get('id'),'result':result});return True
    def run(self):
        def read():
            for line in sys.stdin:
                try:self.requests.put(json.loads(line))
                except ValueError:self.requests.put({'action':'invalid'})
            self.requests.put({'action':'quit'})
        threading.Thread(target=read,daemon=True).start();self.emit({'event':'ready','snapshot':self.snapshot()})
        try:
            while True:
                try:message=self.requests.get(timeout=.1)
                except queue.Empty:message=None
                if message is not None:
                    try:
                        if not self.handle(message):break
                    except Exception as e:self.emit({'id':message.get('id') if isinstance(message,dict) else None,'error':str(e)})
                self.emit({'event':'status','stats':self.service.stats,'recording':self.busy,'remaining':max(0,self.record_until-time.monotonic()) if self.busy else 0})
        finally:
            self.service.stop();sd.stop()
            if self.busy:self.preview_thread.join(timeout=3)

def main():
    initialize();logging.basicConfig(filename=DATA/'logs'/'audio.log',level=logging.INFO)
    if '--self-test' in sys.argv:
        from clear_mic.self_test import run
        run();return
    with com_apartment():Backend().run()

if __name__=='__main__':
    try:main()
    except Exception as e:
        logging.exception('Audio backend stopped');print(json.dumps({'event':'fatal','message':str(e)}),flush=True);sys.exit(1)
