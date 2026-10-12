#include <memory>
#include <algorithm>
#include <array>
#include <cmath>
#include "api/echo_canceller3_factory.h"
#include "api/echo_canceller3_config.h"
#include "api/environment.h"
#include "audio_processing/audio_buffer.h"
namespace {
struct Echo {
    webrtc::Environment env;
    webrtc::AudioBuffer render{48000,2,48000,2,48000,2},capture{48000,1,48000,1,48000,1};
    std::unique_ptr<webrtc::EchoControl> aec;
    // Match the measured AEC3 impulse delay so quiet/playback transitions never
    // move the microphone timeline. Keep AEC learning even while output is dry.
    std::array<float,430> dry_delay{};
    unsigned dry_index=0;
    int tail_frames=0;
    bool playback_seen=false;
    float wet=0;
    Echo(){webrtc::EchoCanceller3Factory factory; aec=factory.Create(env,48000,2,1);}
};
}
extern "C" __declspec(dllexport) void* cm_echo_create(){try{return new Echo;}catch(...){return nullptr;}}
extern "C" __declspec(dllexport) void cm_echo_destroy(void* p){delete static_cast<Echo*>(p);}
extern "C" __declspec(dllexport) int cm_echo_render(void* p,const float* reference){
    if(!p||!reference)return -1;
    auto& s=*static_cast<Echo*>(p);
    for(int i=0;i<480;i++){
        s.render.channels()[0][i]=reference[2*i]*32768.f;s.render.channels()[1][i]=reference[2*i+1]*32768.f;
        if(std::max(std::abs(reference[2*i]),std::abs(reference[2*i+1]))>0.0031622777f)s.playback_seen=true; // -50 dBFS
    }
    s.render.SplitIntoFrequencyBands();s.aec->AnalyzeRender(&s.render);
    return 0;
}
extern "C" __declspec(dllexport) int cm_echo_capture(void* p,const float* mic,float* output,int delay_ms){
    if(!p||!mic||!output)return -1;auto& s=*static_cast<Echo*>(p);
    std::array<float,480> dry;
    for(int i=0;i<480;i++){
        s.capture.channels()[0][i]=mic[i]*32768.f;
        dry[i]=s.dry_delay[s.dry_index];s.dry_delay[s.dry_index]=mic[i];
        s.dry_index=(s.dry_index+1)%s.dry_delay.size();
    }
    if(s.playback_seen)s.tail_frames=70; // 700 ms for playback's acoustic tail.
    else if(s.tail_frames>0)--s.tail_frames;
    s.playback_seen=false;
    const float target=s.tail_frames>0?1.f:0.f;
    s.aec->AnalyzeCapture(&s.capture);s.capture.SplitIntoFrequencyBands();
    s.aec->SetAudioBufferDelay(delay_ms);s.aec->ProcessCapture(&s.capture,false);s.capture.MergeFrequencyBands();
    for(int i=0;i<480;i++){
        s.wet=target>s.wet?std::min(target,s.wet+1.f/480):std::max(target,s.wet-1.f/2400);
        output[i]=dry[i]+s.wet*(s.capture.channels()[0][i]/32768.f-dry[i]);
    }
    return 0;
}
extern "C" __declspec(dllexport) int cm_echo_process(void* p,const float* mic,const float* reference,float* output,int delay_ms){
    int status=cm_echo_render(p,reference);return status?status:cm_echo_capture(p,mic,output,delay_ms);
}
extern "C" __declspec(dllexport) void cm_echo_metrics(void* p,float* values){
    if(!p||!values)return;auto m=static_cast<Echo*>(p)->aec->GetMetrics();
    values[0]=float(m.echo_return_loss_enhancement);values[1]=float(m.delay_ms);
    values[2]=static_cast<Echo*>(p)->wet;
}
