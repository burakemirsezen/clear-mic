#include <memory>
#include "api/echo_canceller3_factory.h"
#include "api/echo_canceller3_config.h"
#include "api/environment.h"
#include "audio_processing/audio_buffer.h"
namespace {
struct Echo {
    webrtc::Environment env;
    webrtc::AudioBuffer render{48000,2,48000,2,48000,2},capture{48000,1,48000,1,48000,1};
    std::unique_ptr<webrtc::EchoControl> aec;
    Echo(){webrtc::EchoCanceller3Factory factory; aec=factory.Create(env,48000,2,1);}
};
}
extern "C" __declspec(dllexport) void* cm_echo_create(){try{return new Echo;}catch(...){return nullptr;}}
extern "C" __declspec(dllexport) void cm_echo_destroy(void* p){delete static_cast<Echo*>(p);}
extern "C" __declspec(dllexport) int cm_echo_render(void* p,const float* reference){
    if(!p||!reference)return -1;
    auto& s=*static_cast<Echo*>(p);
    for(int i=0;i<480;i++){s.render.channels()[0][i]=reference[2*i]*32768.f;s.render.channels()[1][i]=reference[2*i+1]*32768.f;}
    s.render.SplitIntoFrequencyBands();s.aec->AnalyzeRender(&s.render);
    return 0;
}
extern "C" __declspec(dllexport) int cm_echo_capture(void* p,const float* mic,float* output,int delay_ms){
    if(!p||!mic||!output)return -1;auto& s=*static_cast<Echo*>(p);
    for(int i=0;i<480;i++)s.capture.channels()[0][i]=mic[i]*32768.f;
    s.aec->AnalyzeCapture(&s.capture);s.capture.SplitIntoFrequencyBands();
    s.aec->SetAudioBufferDelay(delay_ms);s.aec->ProcessCapture(&s.capture,false);s.capture.MergeFrequencyBands();
    for(int i=0;i<480;i++)output[i]=s.capture.channels()[0][i]/32768.f;
    return 0;
}
extern "C" __declspec(dllexport) int cm_echo_process(void* p,const float* mic,const float* reference,float* output,int delay_ms){
    int status=cm_echo_render(p,reference);return status?status:cm_echo_capture(p,mic,output,delay_ms);
}
extern "C" __declspec(dllexport) void cm_echo_metrics(void* p,float* values){
    if(!p||!values)return;auto m=static_cast<Echo*>(p)->aec->GetMetrics();
    values[0]=float(m.echo_return_loss_enhancement);values[1]=float(m.delay_ms);
}
