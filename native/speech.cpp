#include <algorithm>
#include <cmath>
#include <cstdint>
#include <new>
#include <intrin.h>
#include "rnnoise.h"

constexpr double SR=48000.0, PI=3.14159265358979323846;
constexpr unsigned FRAME=480, LOOK=96, RING=LOOK+1;
struct Config { int noise,highpass,compressor,limiter; float highpass_hz,threshold_db,ratio,knee_db,attack_ms,release_ms,makeup_db,presence_db,output_db,ceiling_db,input_db; };
struct Biquad {
    double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
    double process(double x){double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;if(std::abs(z1)<1e-25)z1=0;if(std::abs(z2)<1e-25)z2=0;return y;}
    void highpass(double hz){double w=2*PI*hz/SR,c=cos(w),a=sin(w)/sqrt(2.0),a0=1+a;b0=(1+c)/2/a0;b1=-(1+c)/a0;b2=b0;a1=-2*c/a0;a2=(1-a)/a0;}
    void presence(double db){double w=2*PI*2800/SR,c=cos(w),a=sin(w)/(2*.707),A=pow(10,db/40),a0=1+a/A;b0=(1+a*A)/a0;b1=-2*c/a0;b2=(1-a*A)/a0;a1=b1;a2=(1-a/A)/a0;}
};
struct State {
    DenoiseState* noise=nullptr;Config c{};Biquad hp,eq;
    float input[FRAME]{},denoised[FRAME]{},ring[RING]{};
    float maxima[128]{};int64_t indices[128]{};unsigned head=0,tail=0;int64_t seq=0;
    double energy=0,comp_gain=1,lim_gain=1,attack=.99,release=.99,rms=.99,lim_release=.999;
    float stats[5]{};
};
static float clampf(float v,float lo,float hi){return std::clamp(v,lo,hi);}
static double dbgain(double db){return pow(10.0,db/20.0);}
extern "C" __declspec(dllexport) int cm_configure(void* handle,const Config* value){
    if(!handle||!value)return -1;State& s=*(State*)handle;Config c=*value;
    const float values[]={c.highpass_hz,c.threshold_db,c.ratio,c.knee_db,c.attack_ms,c.release_ms,c.makeup_db,c.presence_db,c.output_db,c.ceiling_db,c.input_db};for(float v:values)if(!std::isfinite(v))return -2;
    c.highpass_hz=clampf(c.highpass_hz,40,160);c.threshold_db=clampf(c.threshold_db,-40,-6);c.ratio=clampf(c.ratio,1,6);c.knee_db=clampf(c.knee_db,0,12);
    c.attack_ms=clampf(c.attack_ms,1,50);c.release_ms=clampf(c.release_ms,50,500);c.makeup_db=clampf(c.makeup_db,0,8);c.presence_db=clampf(c.presence_db,-3,3);
    c.output_db=clampf(c.output_db,-18,6);c.ceiling_db=clampf(c.ceiling_db,-6,-.5);c.input_db=clampf(c.input_db,-18,12);
    if(c.highpass!=s.c.highpass||c.highpass_hz!=s.c.highpass_hz){s.hp.z1=s.hp.z2=0;s.hp.highpass(c.highpass_hz);}
    if(c.presence_db!=s.c.presence_db){s.eq.z1=s.eq.z2=0;s.eq.presence(c.presence_db);}
    if(c.limiter!=s.c.limiter){std::fill(s.ring,s.ring+RING,0.f);s.seq=0;s.head=s.tail=0;s.lim_gain=1;}
    if(c.compressor!=s.c.compressor){s.comp_gain=1;s.energy=0;}
    s.c=c;s.attack=exp(-1/(SR*c.attack_ms*.001));s.release=exp(-1/(SR*c.release_ms*.001));s.rms=exp(-1/(SR*.02));s.lim_release=exp(-1/(SR*.08));return 0;
}
extern "C" __declspec(dllexport) void* cm_create(){
    State* s=new(std::nothrow) State;if(!s)return nullptr;s->noise=rnnoise_create(nullptr);if(!s->noise){delete s;return nullptr;}
    Config c{1,1,1,1,70,-20,2,6,10,150,2,0,0,-1,0};cm_configure(s,&c);return s;
}
extern "C" __declspec(dllexport) void cm_destroy(void* handle){if(handle){State* s=(State*)handle;rnnoise_destroy(s->noise);delete s;}}
extern "C" __declspec(dllexport) int cm_process(void* handle,const float* input,float* output,unsigned n){
    if(!handle||!input||!output||n!=FRAME)return -1;State& s=*(State*)handle;
    float ip=0,op=0;double comp_reduction=0,lim_reduction=0;unsigned clips=0;
    double ing=dbgain(s.c.input_db),outg=dbgain(s.c.output_db),makeup=s.c.compressor?dbgain(s.c.makeup_db):1,ceiling=dbgain(s.c.ceiling_db);
    for(unsigned i=0;i<n;i++){
        if(!std::isfinite(input[i]))return -2;ip=std::max(ip,std::abs(input[i]));if(std::abs(input[i])>=.999f)clips++;
        double x=input[i]*ing;if(s.c.highpass)x=s.hp.process(x);s.input[i]=(float)(x*32768.0);
    }
    if(s.c.noise)rnnoise_process_frame(s.noise,s.denoised,s.input);else std::copy(s.input,s.input+n,s.denoised);
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
    s.stats[0]=ip;s.stats[1]=op;s.stats[2]=(float)comp_reduction;s.stats[3]=(float)lim_reduction;s.stats[4]=(float)clips;return 0;
}
extern "C" __declspec(dllexport) void cm_stats(void* handle,float* values){if(handle&&values)std::copy(((State*)handle)->stats,((State*)handle)->stats+5,values);}
extern "C" __declspec(dllexport) unsigned cm_latency(void* handle){return handle&&((State*)handle)->c.limiter?LOOK:0;}
extern "C" __declspec(dllexport) int cm_cpu_supported(){int regs[4];__cpuid(regs,1);if(!(regs[2]&(1<<27))||!(regs[2]&(1<<28)))return 0;if((_xgetbv(0)&6)!=6)return 0;__cpuidex(regs,7,0);return (regs[1]&(1<<5))!=0;}
