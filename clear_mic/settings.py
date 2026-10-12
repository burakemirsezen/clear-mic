import json
from dataclasses import dataclass,asdict
from .paths import DATA

@dataclass
class Voice:
    noise:int=1
    highpass:int=1
    compressor:int=1
    limiter:int=1
    highpass_hz:float=70
    threshold_db:float=-20
    ratio:float=2
    knee_db:float=6
    attack_ms:float=10
    release_ms:float=150
    makeup_db:float=0
    presence_db:float=0
    output_db:float=0
    ceiling_db:float=-1
    input_db:float=0
    auto_level:int=1
    noise_strength:float=90
    def validate(self):
        import math
        bounds={'noise_strength':(0,100),'highpass_hz':(40,160),'threshold_db':(-40,-6),'ratio':(1,6),'knee_db':(0,12),'attack_ms':(1,50),'release_ms':(50,500),'makeup_db':(0,8),'presence_db':(-3,3),'output_db':(-18,6),'ceiling_db':(-6,-.5),'input_db':(-18,12)}
        for name,(low,high) in bounds.items():
            value=float(getattr(self,name))
            if not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{name} must be between {low} and {high}')
            setattr(self,name,value)
        for name in ('noise','highpass','compressor','limiter','auto_level'):setattr(self,name,int(bool(getattr(self,name))))
        return self
PRESETS={'Natural speech':Voice(),'Even speech':Voice(threshold_db=-20,ratio=3,makeup_db=1,highpass_hz=80,presence_db=1),'Singing':Voice(noise=0,auto_level=0,compressor=0,highpass_hz=40,threshold_db=-18,ratio=1.5,attack_ms=25,release_ms=250,noise_strength=75),'Noise removal only':Voice(highpass=0,compressor=0,limiter=0,auto_level=0,noise_strength=100)}
def load():
    try:return json.loads((DATA/'settings.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
def save(value):
    path=DATA/'settings.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(path)
def voice_from(value):return Voice(**{k:v for k,v in value.items() if k in Voice.__dataclass_fields__}).validate()
