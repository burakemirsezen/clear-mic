#include <algorithm>
#include <cmath>
#include <memory>
#include "api/audio_processing.h"
#include "api/environment.h"
#include "audio_processing/audio_buffer.h"
#include "audio_processing/gain_controller2.h"
namespace {
struct Leveler {
    webrtc::Environment env;
    webrtc::AudioBuffer buffer{48000,1,48000,1,48000};
    std::unique_ptr<webrtc::GainController2> agc;
    Leveler(){
        webrtc::AudioProcessing::Config::GainController2 c;
        c.enabled=true;c.adaptive_digital.enabled=true;
        c.adaptive_digital.headroom_db=6;
        c.adaptive_digital.max_gain_db=18;
        c.adaptive_digital.initial_gain_db=6;
        c.adaptive_digital.max_gain_change_db_per_second=3;
        c.adaptive_digital.max_output_noise_level_dbfs=-50;
        c.input_volume_controller.enabled=false;
        agc=std::make_unique<webrtc::GainController2>(env,c,webrtc::InputVolumeController::Config{},48000,1,true);
    }
};
}
extern "C" __declspec(dllexport) void* cm_level_create(){try{return new Leveler;}catch(...){return nullptr;}}
extern "C" __declspec(dllexport) void cm_level_destroy(void* p){delete static_cast<Leveler*>(p);}
// Samples use WebRTC's float S16 scale. Return the effective frame gain in dB.
extern "C" __declspec(dllexport) float cm_level_process(void* p,float* samples){
    auto& s=*static_cast<Leveler*>(p);double before=0,after=0;
    auto* channel=s.buffer.channels()[0];
    for(int i=0;i<480;i++){channel[i]=samples[i];before+=double(samples[i])*samples[i];}
    s.agc->Analyze(255,s.buffer);s.agc->Process(false,&s.buffer);
    for(int i=0;i<480;i++){samples[i]=channel[i];after+=double(samples[i])*samples[i];}
    return before>1e-10?float(10*std::log10(std::max(after,1e-10)/before)):0;
}
