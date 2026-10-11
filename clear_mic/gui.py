import json,os,queue,threading,time
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk,messagebox
import numpy as np
import sounddevice as sd
import soundfile as sf
from . import __version__,startup
from .paths import ROOT,DATA
from .settings import Voice,PRESETS,load,save,voice_from
from .audio_service import AudioService,devices,record_preview,process_clip
from .processor import RATE

BG='#111a27';PANEL='#1b2738';TEXT='#e6eef8';MUTED='#a5b6cb';ACCENT='#62dfbd'

class App:
    def __init__(self,root,no_tray=False):
        self.root=root;self.events=queue.Queue();self.service=AudioService();self.busy=False;self.preview=None;self.closing=False;self.save_timer=None;self.error_shown=None
        self.saved=load();self.voice=voice_from(self.saved.get('voice',{}));self.tray=None
        scale=max(1,float(root.tk.call('tk','scaling'))/(96/72))
        root.title('Clear Mic');root.geometry(f'{round(790*scale)}x{round(740*scale)}');root.minsize(round(700*scale),round(680*scale));root.configure(bg=BG)
        icon=ROOT/'assets'/'clear-mic.ico'
        if icon.exists():root.iconbitmap(str(icon))
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10),background=BG,foreground=TEXT)
        style.configure('TFrame',background=BG);style.configure('TLabel',background=BG,foreground=TEXT)
        style.configure('Muted.TLabel',foreground=MUTED);style.configure('Title.TLabel',font=('Segoe UI',24,'bold'))
        style.configure('TButton',background=PANEL,foreground=TEXT,padding=(14,9),borderwidth=0);style.map('TButton',background=[('active','#2b3e55')])
        style.configure('Accent.TButton',background=ACCENT,foreground=BG,font=('Segoe UI',12,'bold'),padding=(18,11));style.map('Accent.TButton',background=[('active','#87efd2'),('disabled','#344957')])
        style.configure('TCombobox',fieldbackground=PANEL,background=PANEL,foreground=TEXT,arrowcolor=TEXT);style.map('TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',TEXT)])
        style.configure('TCheckbutton',background=BG,foreground=TEXT);style.map('TCheckbutton',background=[('active',BG)])
        style.configure('TNotebook',background=BG,borderwidth=0);style.configure('TNotebook.Tab',background=PANEL,foreground=MUTED,padding=(20,10));style.map('TNotebook.Tab',background=[('selected','#294355')],foreground=[('selected',TEXT)])
        style.configure('Horizontal.TScale',background=BG,troughcolor=PANEL)
        root.option_add('*TCombobox*Listbox.background',PANEL);root.option_add('*TCombobox*Listbox.foreground',TEXT)
        page=ttk.Frame(root,padding=24);page.pack(fill='both',expand=True)
        header=ttk.Frame(page);header.pack(fill='x');ttk.Label(header,text='Clear Mic',style='Title.TLabel').pack(side='left')
        ttk.Label(header,text=f'LOCAL · CPU · RNNOISE   {__version__}',style='Muted.TLabel').pack(side='right')
        ttk.Label(page,text='A clear voice for games and calls.',style='Muted.TLabel').pack(anchor='w',pady=(4,18))
        tabs=ttk.Notebook(page);tabs.pack(fill='both',expand=True)
        self.home=ttk.Frame(tabs,padding=(18,18));self.sound=ttk.Frame(tabs,padding=(18,16));self.options=ttk.Frame(tabs,padding=(18,18))
        tabs.add(self.home,text='Microphone');tabs.add(self.sound,text='Voice');tabs.add(self.options,text='Settings')
        self.input=tk.StringVar(value=self.saved.get('input',''));self.output=tk.StringVar(value=self.saved.get('output',''));self.listen=tk.StringVar(value=self.saved.get('listen',''))
        self.device_boxes={}
        for label,var,kind in [('Your microphone',self.input,'input'),('Virtual microphone output',self.output,'output')]:
            ttk.Label(self.home,text=label).pack(anchor='w',pady=(4,5));box=ttk.Combobox(self.home,textvariable=var,state='readonly');box.pack(fill='x',pady=(0,12));box.bind('<<ComboboxSelected>>',lambda e:self.persist());self.device_boxes[kind]=box
        ttk.Label(self.home,text='In Steam or your calling app, select the recording side of this virtual device.',style='Muted.TLabel',wraplength=650).pack(anchor='w')
        action=ttk.Frame(self.home);action.pack(fill='x',pady=(20,16));self.start_button=ttk.Button(action,text='Start microphone',style='Accent.TButton',command=self.toggle);self.start_button.pack(side='left')
        ttk.Button(action,text='Refresh devices',command=self.refresh).pack(side='right')
        self.status=tk.StringVar(value='Stopped');ttk.Label(self.home,textvariable=self.status,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(0,12))
        self.input_meter=self.meter(self.home,'Input');self.output_meter=self.meter(self.home,'Output')
        self.stats=tk.StringVar(value='No recording is saved during live use.');ttk.Label(self.home,textvariable=self.stats,style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(16,0))
        self.warning=tk.StringVar(value='');ttk.Label(self.home,textvariable=self.warning,foreground='#ffd58b',wraplength=650).pack(anchor='w',pady=(8,0))
        top=ttk.Frame(self.sound);top.pack(fill='x');self.preset=tk.StringVar(value=self.saved.get('preset','Natural speech'));ttk.Label(top,text='Speech preset').pack(side='left')
        box=ttk.Combobox(top,textvariable=self.preset,values=list(PRESETS)+['Custom'],state='readonly',width=20);box.pack(side='right');box.bind('<<ComboboxSelected>>',self.apply_preset)
        self.vars={}
        toggles=ttk.Frame(self.sound);toggles.pack(fill='x',pady=(14,10))
        for name,label in [('noise','Noise removal'),('highpass','High-pass'),('compressor','Compressor'),('limiter','Limiter')]:
            variable=tk.BooleanVar(value=bool(getattr(self.voice,name)));self.vars[name]=variable;ttk.Checkbutton(toggles,text=label,variable=variable,command=self.changed).pack(side='left',padx=(0,12))
        self.value_labels={}
        for name,label,low,high,unit in [('highpass_hz','Rumble cut',40,160,'Hz'),('threshold_db','Compression threshold',-40,-6,'dB'),('ratio','Compression ratio',1,6,':1'),('makeup_db','Speech boost',0,8,'dB'),('presence_db','Clarity EQ',-3,3,'dB'),('output_db','Output volume',-18,6,'dB')]:
            row=ttk.Frame(self.sound);row.pack(fill='x',pady=5);ttk.Label(row,text=label,width=24).pack(side='left');var=tk.DoubleVar(value=getattr(self.voice,name));self.vars[name]=var
            ttk.Scale(row,from_=low,to=high,variable=var,command=lambda x:self.changed()).pack(side='left',fill='x',expand=True,padx=8);value=tk.StringVar();self.value_labels[name]=(value,unit);ttk.Label(row,textvariable=value,width=9,anchor='e').pack(side='right')
        ttk.Label(self.sound,text='Natural starts gently: 70 Hz high-pass, 2:1 soft compression, 2 dB boost, neutral EQ, −1 dB peak ceiling.',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(8,10))
        preview=ttk.Frame(self.sound);preview.pack(fill='x',pady=7);self.record_button=ttk.Button(preview,text='Record 5s preview',command=self.record);self.record_button.pack(side='left')
        self.raw_button=ttk.Button(preview,text='Original',command=lambda:self.play(False),state='disabled');self.raw_button.pack(side='left',padx=8)
        self.processed_button=ttk.Button(preview,text='Processed',command=lambda:self.play(True),state='disabled');self.processed_button.pack(side='left')
        ttk.Button(preview,text='Stop playback',command=sd.stop).pack(side='right')
        ttk.Label(self.sound,text='Preview records only when pressed. Stop the live microphone first. Sound changes apply live; replay Processed to hear updated settings.',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(7,0))
        ttk.Label(self.options,text='Preview playback device').pack(anchor='w');self.listen_box=ttk.Combobox(self.options,textvariable=self.listen,state='readonly');self.listen_box.pack(fill='x',pady=(7,20));self.listen_box.bind('<<ComboboxSelected>>',lambda e:self.persist())
        self.auto=tk.BooleanVar(value=self.saved.get('auto_start',False));self.minimize=tk.BooleanVar(value=self.saved.get('minimize_to_tray',True));self.login=tk.BooleanVar(value=startup.enabled())
        ttk.Checkbutton(self.options,text='Start microphone automatically when Clear Mic opens',variable=self.auto,command=self.persist).pack(anchor='w',pady=7)
        ttk.Checkbutton(self.options,text='Close window to tray (audio keeps running)',variable=self.minimize,command=self.persist).pack(anchor='w',pady=7)
        ttk.Checkbutton(self.options,text='Launch Clear Mic when I sign into Windows',variable=self.login,command=self.set_startup).pack(anchor='w',pady=7)
        ttk.Label(self.options,text='Advanced speech controls',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(22,7))
        for name,label,low,high,unit in [('input_db','Input trim',-18,12,'dB'),('attack_ms','Compressor attack',1,50,'ms'),('release_ms','Compressor release',50,500,'ms'),('ceiling_db','Limiter ceiling',-6,-.5,'dB')]:
            row=ttk.Frame(self.options);row.pack(fill='x',pady=5);ttk.Label(row,text=label,width=24).pack(side='left');var=tk.DoubleVar(value=getattr(self.voice,name));self.vars[name]=var
            ttk.Scale(row,from_=low,to=high,variable=var,command=lambda x:self.changed()).pack(side='left',fill='x',expand=True,padx=8);value=tk.StringVar();self.value_labels[name]=(value,unit);ttk.Label(row,textvariable=value,width=9,anchor='e').pack(side='right')
        ttk.Label(self.options,text='Limiter adds 2 ms of lookahead. Input clipping needs lower gain on the microphone. Clear Mic uses an existing virtual audio device; it does not install a driver.',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(14,12))
        bottom=ttk.Frame(self.options);bottom.pack(fill='x');ttk.Button(bottom,text='Open data folder',command=lambda:os.startfile(DATA)).pack(side='left');ttk.Button(bottom,text='Quit Clear Mic',command=self.quit).pack(side='right')
        self.footer=tk.StringVar(value='Ready. Live use stays local; no cloud processing.');ttk.Label(page,textvariable=self.footer,style='Muted.TLabel',wraplength=740).pack(fill='x',pady=(14,0))
        self.update_values();self.refresh();root.protocol('WM_DELETE_WINDOW',self.close_window)
        if not no_tray:
            try:
                from .tray import Tray
                self.tray=Tray(self.events)
            except Exception:self.minimize.set(False)
        root.after(100,self.poll)
        if self.auto.get():root.after(400,self.start)
    def meter(self,parent,label):
        row=ttk.Frame(parent);row.pack(fill='x',pady=6);ttk.Label(row,text=label,width=9).pack(side='left');canvas=tk.Canvas(row,height=18,bg=PANEL,highlightthickness=0);canvas.pack(side='left',fill='x',expand=True);value=ttk.Label(row,text='−60 dB',width=9,anchor='e');value.pack(side='right');return canvas,value
    def update_meter(self,meter,level):
        canvas,value=meter;canvas.delete('all');width=canvas.winfo_width()*max(0,min(1,(level+60)/60));canvas.create_rectangle(0,0,width,18,fill=ACCENT if level<-6 else '#ffd58b',outline='');value.configure(text=f'{level:.0f} dB')
    def update_values(self):
        for name,(value,unit) in self.value_labels.items():value.set(f'{self.vars[name].get():.1f}{unit}' if unit==':1' else f'{self.vars[name].get():.0f} {unit}' if unit in ('Hz','ms') else f'{self.vars[name].get():.1f} {unit}')
    def current_voice(self):
        values=asdict(self.voice)
        for name,var in self.vars.items():values[name]=var.get()
        return voice_from(values)
    def changed(self):
        self.preset.set('Custom');self.update_values()
        if self.save_timer:self.root.after_cancel(self.save_timer)
        self.save_timer=self.root.after(180,self.persist)
    def apply_preset(self,event=None):
        if self.preset.get() not in PRESETS:return
        self.voice=voice_from(asdict(PRESETS[self.preset.get()]))
        for name,var in self.vars.items():var.set(getattr(self.voice,name))
        self.update_values();self.persist()
    def persist(self):
        self.save_timer=None
        try:
            self.voice=self.current_voice();value={'voice':asdict(self.voice),'input':self.input.get(),'output':self.output.get(),'listen':self.listen.get(),'preset':self.preset.get(),'auto_start':self.auto.get(),'minimize_to_tray':self.minimize.get()};save(value);self.service.configure(self.voice)
        except Exception as e:self.error(e)
    def refresh(self):
        if self.service.active or self.busy:return
        try:
            sd._terminate();sd._initialize();available=devices();inputs=[n for n,i in available['input']];outputs=[n for n,i in available['output']]
            self.device_boxes['input']['values']=inputs;self.device_boxes['output']['values']=outputs;self.listen_box['values']=outputs
            if self.input.get() not in inputs:self.input.set(next((n for n in inputs if not any(t in n.lower() for t in ('virtual','cable','streaming'))),inputs[0] if inputs else ''))
            if self.output.get() not in outputs:self.output.set(next((n for n in outputs if 'Steam Streaming Microphone' in n),next((n for n in outputs if any(t in n.lower() for t in ('cable','voicemeeter','virtual'))),'')))
            if self.listen.get() not in outputs:
                default=next((a['default_output_device'] for a in sd.query_hostapis() if a['name']=='Windows WASAPI'),-1);self.listen.set(next((n for n,i in available['output'] if i==default),outputs[0] if outputs else ''))
            if not self.output.get():self.footer.set('Choose an installed virtual output, such as a cable or virtual mixer, before starting.')
        except Exception as e:self.error(e)
    def toggle(self):self.stop() if self.service.active else self.start()
    def start(self):
        if self.busy:return
        try:sd.stop();self.persist();self.service.start(self.input.get(),self.output.get(),self.voice);self.error_shown=None
        except Exception as e:self.error(e)
    def stop(self):
        try:self.service.stop()
        except Exception as e:self.error(e)
    def record(self):
        if self.busy:return
        if self.service.active:self.footer.set('Stop the live microphone before recording a preview.');return
        self.busy=True;self.record_button['state']='disabled';self.start_button['state']='disabled';self.footer.set('Recording five seconds. Speak normally, softly, then a little louder.');name=self.input.get();voice=self.current_voice()
        def run():
            try:
                raw=record_preview(name);processed=process_clip(raw,voice);stamp=str(time.time_ns());sf.write(DATA/'previews'/f'{stamp}-original.wav',raw,RATE,subtype='FLOAT');sf.write(DATA/'previews'/f'{stamp}-processed.wav',processed,RATE,subtype='FLOAT');self.events.put(('preview',raw))
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('ready',None))
        self.preview_thread=threading.Thread(target=run,daemon=True);self.preview_thread.start()
    def play(self,processed):
        if self.preview is None or self.service.active or self.busy:return
        try:
            from .audio_service import resolve
            audio=process_clip(self.preview,self.current_voice()) if processed else self.preview
            sd.stop();sd.play(audio,samplerate=RATE,device=resolve(self.listen.get(),'output'),extra_settings=sd.WasapiSettings(auto_convert=True));self.footer.set('Playing processed voice.' if processed else 'Playing original recording.')
        except Exception as e:self.error(e)
    def set_startup(self):
        try:startup.set_enabled(self.login.get())
        except Exception as e:self.login.set(startup.enabled());self.error(e)
    def poll(self):
        if self.closing:return
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='show':self.root.deiconify();self.root.lift()
            elif kind=='start':self.start()
            elif kind=='stop':self.stop()
            elif kind=='quit':self.quit();return
            elif kind=='preview':self.preview=value;self.raw_button['state']=self.processed_button['state']='normal';self.footer.set('Preview ready. Compare Original and Processed, then adjust Voice settings.')
            elif kind=='ready':self.busy=False;self.record_button['state']=self.start_button['state']='normal'
            elif kind=='error':self.error(value)
        stats=self.service.stats;status=stats.get('status','stopped');self.status.set({'running':'● Microphone running','starting':'Starting…','stopped':'Stopped','error':'Audio stopped'}.get(status,status));self.start_button['text']='Stop microphone' if self.service.active else 'Start microphone'
        if status=='error' and stats.get('error')!=self.error_shown:self.error_shown=stats['error'];self.error(stats['error'])
        if status=='running':
            self.update_meter(self.input_meter,stats['input_db']);self.update_meter(self.output_meter,stats['output_db']);self.stats.set(f"Processing {stats['mean_ms']:.2f} ms / frame · Compression {stats['compressor_gr']:.1f} dB · Limiter {stats['limiter_gr']:.1f} dB · Audio warnings {stats['warnings']}")
            self.warning.set('Input clipping detected. Reduce the gain on your microphone.' if stats['clipped_samples'] else '')
        elif status=='stopped':self.update_meter(self.input_meter,-60);self.update_meter(self.output_meter,-60)
        self.root.after(100,self.poll)
    def error(self,error):self.footer.set(str(error));messagebox.showerror('Clear Mic',str(error))
    def close_window(self):
        if self.tray and self.minimize.get():self.persist();self.root.withdraw()
        else:self.quit()
    def quit(self):
        self.closing=True
        if self.save_timer:self.root.after_cancel(self.save_timer)
        self.persist();self.service.stop();sd.stop()
        if self.busy and hasattr(self,'preview_thread'):self.preview_thread.join(timeout=3)
        if self.tray:self.tray.stop()
        self.root.destroy()
