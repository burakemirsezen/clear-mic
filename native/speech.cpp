#include <algorithm>
#include <cmath>
#include <cstdint>
#include <new>
#include <intrin.h>
#include "rnnoise.h"

constexpr double SR=48000.0, PI=3.14159265358979323846;
constexpr unsigned FRAME=480, LOOK=96, RING=LOOK+1;
constexpr unsigned GATE_LOOK=240; // 5 ms; detector opens before the onset arrives.
extern "C" __declspec(dllimport) void* cm_level_create();
extern "C" __declspec(dllimport) void cm_level_destroy(void*);
extern "C" __declspec(dllimport) float cm_level_process(void*,float*);
struct Config { int noise,highpass,compressor,limiter; float highpass_hz,threshold_db,ratio,knee_db,attack_ms,release_ms,makeup_db,presence_db,output_db,ceiling_db,input_db; int auto_level; float noise_strength; int gate; float gate_threshold_db,gate_hold_ms,gate_release_ms; };
struct Biquad {
    double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
    double process(double x){double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;if(std::abs(z1)<1e-25)z1=0;if(std::abs(z2)<1e-25)z2=0;return y;}
    void highpass(double hz){double w=2*PI*hz/SR,c=cos(w),a=sin(w)/sqrt(2.0),a0=1+a;b0=(1+c)/2/a0;b1=-(1+c)/a0;b2=b0;a1=-2*c/a0;a2=(1-a)/a0;}
    void presence(double db){double w=2*PI*2800/SR,c=cos(w),a=sin(w)/(2*.707),A=pow(10,db/40),a0=1+a/A;b0=(1+a*A)/a0;b1=-2*c/a0;b2=(1-a*A)/a0;a1=b1;a2=(1-a/A)/a0;}
};
struct State {
    DenoiseState* noise=nullptr;void* leveler=nullptr;Config c{};Biquad hp,eq;
    float input[FRAME]{},denoised[FRAME]{},ring[RING]{};
    float original[960]{},dry[FRAME]{};unsigned original_index=0;float noise_mix=1;
    float maxima[128]{};int64_t indices[128]{};unsigned head=0,tail=0;int64_t seq=0;
    double energy=0,comp_gain=1,lim_gain=1,attack=.99,release=.99,rms=.99,lim_release=.999;
    float gate_delay[GATE_LOOK]{};unsigned gate_index=0,gate_hold=0;bool gate_open=false;double gate_gain=0;
    float stats[9]{};
};
static float clampf(float v,float lo,float hi){return std::clamp(v,lo,hi);}
static double dbgain(double db){return pow(10.0,db/20.0);}
extern "C" __declspec(dllexport) int cm_configure(void* handle,const Config* value){
    if(!handle||!value)return -1;State& s=*(State*)handle;Config c=*value;
    const float values[]={c.highpass_hz,c.threshold_db,c.ratio,c.knee_db,c.attack_ms,c.release_ms,c.makeup_db,c.presence_db,c.output_db,c.ceiling_db,c.input_db,c.noise_strength,c.gate_threshold_db,c.gate_hold_ms,c.gate_release_ms};for(float v:values)if(!std::isfinite(v))return -2;
    c.highpass_hz=clampf(c.highpass_hz,40,160);c.threshold_db=clampf(c.threshold_db,-40,-6);c.ratio=clampf(c.ratio,1,6);c.knee_db=clampf(c.knee_db,0,12);
    c.attack_ms=clampf(c.attack_ms,1,50);c.release_ms=clampf(c.release_ms,50,500);c.makeup_db=clampf(c.makeup_db,0,8);c.presence_db=clampf(c.presence_db,-3,3);
    c.output_db=clampf(c.output_db,-18,6);c.ceiling_db=clampf(c.ceiling_db,-6,-.5);c.input_db=clampf(c.input_db,-18,12);
    c.noise_strength=clampf(c.noise_strength,0,100);
    c.gate_threshold_db=clampf(c.gate_threshold_db,-75,-15);c.gate_hold_ms=clampf(c.gate_hold_ms,50,500);c.gate_release_ms=clampf(c.gate_release_ms,40,500);
    if(c.gate!=s.c.gate){std::fill(s.gate_delay,s.gate_delay+GATE_LOOK,0.f);s.gate_index=s.gate_hold=0;s.gate_open=false;s.gate_gain=0;}
    if(c.noise!=s.c.noise){std::fill(s.original,s.original+960,0.f);s.original_index=0;rnnoise_init(s.noise,nullptr);s.noise_mix=c.noise_strength/100.f;}
    if(c.highpass!=s.c.highpass||c.highpass_hz!=s.c.highpass_hz){s.hp.z1=s.hp.z2=0;s.hp.highpass(c.highpass_hz);}
    if(c.presence_db!=s.c.presence_db){s.eq.z1=s.eq.z2=0;s.eq.presence(c.presence_db);}
    if(c.limiter!=s.c.limiter){std::fill(s.ring,s.ring+RING,0.f);s.seq=0;s.head=s.tail=0;s.lim_gain=1;}
    if(c.compressor!=s.c.compressor){s.comp_gain=1;s.energy=0;}
    if(c.auto_level!=s.c.auto_level){
        void* leveler=c.auto_level?cm_level_create():nullptr;
        if(c.auto_level&&!leveler)return -3;
        cm_level_destroy(s.leveler);s.leveler=leveler;
    }
    s.c=c;s.attack=exp(-1/(SR*c.attack_ms*.001));s.release=exp(-1/(SR*c.release_ms*.001));s.rms=exp(-1/(SR*.02));s.lim_release=exp(-1/(SR*.08));return 0;
}
extern "C" __declspec(dllexport) void* cm_create(){
    State* s=new(std::nothrow) State;if(!s)return nullptr;s->noise=rnnoise_create(nullptr);if(!s->noise){delete s;return nullptr;}
    Config c{1,1,1,1,70,-20,2,6,10,150,0,0,0,-1,0,1,90,0,-45,150,120};
    if(cm_configure(s,&c)){rnnoise_destroy(s->noise);delete s;return nullptr;}return s;
}
extern "C" __declspec(dllexport) void cm_destroy(void* handle){if(handle){State* s=(State*)handle;rnnoise_destroy(s->noise);cm_level_destroy(s->leveler);delete s;}}
extern "C" __declspec(dllexport) int cm_process(void* handle,const float* input,float* output,unsigned n){
    if(!handle||!input||!output||n!=FRAME)return -1;State& s=*(State*)handle;
    float ip=0,op=0;double comp_reduction=0,lim_reduction=0;unsigned clips=0;
    double ing=dbgain(s.c.input_db),outg=dbgain(s.c.output_db),makeup=s.c.compressor?dbgain(s.c.makeup_db):1,ceiling=dbgain(s.c.ceiling_db);
    for(unsigned i=0;i<n;i++){
        if(!std::isfinite(input[i]))return -2;ip=std::max(ip,std::abs(input[i]));if(std::abs(input[i])>=.999f)clips++;
        double x=input[i]*ing;if(s.c.highpass)x=s.hp.process(x);s.input[i]=(float)(x*32768.0);
        if(s.c.noise){s.dry[i]=s.original[s.original_index];s.original[s.original_index]=s.input[i];s.original_index=(s.original_index+1)%960;}
    }
    float vad=0;
    if(s.c.noise)vad=rnnoise_process_frame(s.noise,s.denoised,s.input);else std::copy(s.input,s.input+n,s.denoised);
    if(s.c.noise){
        const float target=s.c.noise_strength/100.f;
        for(unsigned i=0;i<n;i++){
            s.noise_mix+=std::clamp(target-s.noise_mix,-1.f/960,1.f/960);
            s.denoised[i]=s.dry[i]+s.noise_mix*(s.denoised[i]-s.dry[i]);
        }
    }
    // Gate before automatic/makeup gain so boosted keyboard noise cannot open it.
    // Six dB of hysteresis and a sample-counted hold avoid chatter on quiet tails.
    float gate_peak=0;
    const double gate_threshold=dbgain(s.c.gate_threshold_db)*32768.0,gate_close=gate_threshold*dbgain(-6);
    const unsigned hold_samples=(unsigned)(SR*s.c.gate_hold_ms*.001);
    const double gate_release_step=1/(SR*s.c.gate_release_ms*.001);
    for(unsigned i=0;i<n;i++){
        const float x=s.denoised[i];gate_peak=std::max(gate_peak,std::abs(x)/32768.f);
        if(s.c.gate){
            const double magnitude=std::abs(x);
            if(magnitude>=gate_threshold||(s.gate_open&&magnitude>=gate_close)){s.gate_open=true;s.gate_hold=hold_samples;}
            else if(s.gate_hold)--s.gate_hold;
            else s.gate_open=false;
            s.gate_gain=s.gate_open?std::min(1.0,s.gate_gain+1.0/48):std::max(0.0,s.gate_gain-gate_release_step);
            const float delayed=s.gate_delay[s.gate_index];s.gate_delay[s.gate_index]=x;s.gate_index=(s.gate_index+1)%GATE_LOOK;
            s.denoised[i]=(float)(delayed*s.gate_gain);
        }
    }
    float automatic_gain=s.c.auto_level?cm_level_process(s.leveler,s.denoised):0;
    for(unsigned i=0;i<n;i++){
        double x=s.denoised[i]/32768.0;if(std::abs(s.c.presence_db)>.001)x=s.eq.process(x);
        if(s.c.compressor){
            s.energy=s.rms*s.energy+(1-s.rms)*x*x;double level=10*log10(std::max(s.energy,1e-18)),over=level-s.c.threshold_db,k=s.c.knee_db,gr=0;
            if(k>0&&over>-k/2&&over<k/2)gr=(1/s.c.ratio-1)*(over+k/2)*(over+k/2)/(2*k);
            else if(over>=k/2)gr=(1/s.c.ratio-1)*over;
            double target=dbgain(gr),coeff=target<s.comp_gain?s.attack:s.release;s.comp_gain=target+(s.comp_gain-target)*coeff;
            x*=s.comp_gain*makeup;comp_reduction=std::max(comp_reduction,-20*log10(std::max(s.comp_gain,1e-12)));
        }
        x*=outg;
        if(s.c.limiter){
            float peak=(float)std::abs(x);int64_t q=s.seq++;
            while(s.head!=s.tail&&s.indices[s.head]<q-LOOK)s.head=(s.head+1)%128;
            while(s.head!=s.tail&&s.maxima[(s.tail+127)%128]<=peak)s.tail=(s.tail+127)%128;
            s.maxima[s.tail]=peak;s.indices[s.tail]=q;s.tail=(s.tail+1)%128;
            double target=std::min(1.0,ceiling/std::max((double)s.maxima[s.head],1e-12));
            s.lim_gain=target<s.lim_gain?target:target+(s.lim_gain-target)*s.lim_release;
            s.ring[q%RING]=(float)x;x=s.ring[(q+1)%RING]*s.lim_gain;
            // Guaranteed sample-peak ceiling; this is not an intersample true-peak limiter.
            x=std::clamp(x,-ceiling,ceiling);lim_reduction=std::max(lim_reduction,-20*log10(std::max(s.lim_gain,1e-12)));
        }
        output[i]=(float)std::clamp(x,-1.0,1.0);op=std::max(op,std::abs(output[i]));
    }
    s.stats[0]=ip;s.stats[1]=op;s.stats[2]=(float)comp_reduction;s.stats[3]=(float)lim_reduction;s.stats[4]=(float)clips;s.stats[5]=automatic_gain;s.stats[6]=vad;s.stats[7]=gate_peak;s.stats[8]=s.c.gate?(float)(-20*log10(std::max(s.gate_gain,1e-6))):0;return 0;
}
extern "C" __declspec(dllexport) void cm_stats(void* handle,float* values){if(handle&&values)std::copy(((State*)handle)->stats,((State*)handle)->stats+9,values);}
extern "C" __declspec(dllexport) unsigned cm_latency(void* handle){if(!handle)return 0;const auto& c=((State*)handle)->c;return (c.limiter?LOOK:0)+(c.gate?GATE_LOOK:0);}
extern "C" __declspec(dllexport) unsigned cm_abi_version(){return 2;}
extern "C" __declspec(dllexport) int cm_cpu_supported(){int regs[4];__cpuid(regs,1);if(!(regs[2]&(1<<27))||!(regs[2]&(1<<28)))return 0;if((_xgetbv(0)&6)!=6)return 0;__cpuidex(regs,7,0);return (regs[1]&(1<<5))!=0;}
