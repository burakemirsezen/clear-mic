#include <memory>
#include <algorithm>
#include <array>
#include <cmath>
#include "api/echo_canceller3_factory.h"
#include "api/echo_canceller3_config.h"
#include "api/environment.h"
#include "audio_processing/audio_buffer.h"
namespace {
using Config=webrtc::EchoCanceller3Config;

// Natural voice: preserve near-end harmonics and consonants during simultaneous
// playback. The adaptive linear filter still subtracts the correlated echo;
// residual suppression waits for stronger echo evidence before masking voice.
void preserve_voice_tuning(Config& config){
    auto& suppressor=config.suppressor;
    using Mask=Config::Suppressor::MaskingThresholds;
    suppressor.normal_tuning.mask_lf=Mask(4.f,20.f,1.f);
    suppressor.normal_tuning.mask_hf=Mask(4.f,20.f,1.f);
    suppressor.nearend_tuning.mask_lf=Mask(8.f,30.f,1.f);
    suppressor.nearend_tuning.mask_hf=Mask(8.f,30.f,1.f);
    suppressor.dominant_nearend_detection.enr_threshold=1.f;
    suppressor.dominant_nearend_detection.snr_threshold=10.f;
    suppressor.dominant_nearend_detection.trigger_threshold=3;
    suppressor.dominant_nearend_detection.hold_duration=100;
    suppressor.nearend_tuning.max_inc_factor=4.f;
    suppressor.nearend_tuning.max_dec_factor_lf=.5f;
    suppressor.floor_first_increase=.01f;
}

Config make_config(bool preserve_voice,int filter_blocks){
    Config config;
    if(preserve_voice)preserve_voice_tuning(config);
    // Upstream's 13 blocks (52 ms) is sized for phones/laptops. Desktop speakers
    // and rooms ring longer, so a longer adaptive filter removes more echo.
    if(filter_blocks>0){
        config.filter.refined.length_blocks=filter_blocks;
        config.filter.coarse.length_blocks=filter_blocks;
    }
    return config;
}

std::unique_ptr<webrtc::EchoControl> make_aec(const webrtc::Environment& env,const Config& config,int rate){
    webrtc::EchoCanceller3Factory factory(config,std::optional(config));
    return factory.Create(env,rate,2,1);
}

struct Echo {
    webrtc::Environment env;
    webrtc::AudioBuffer render{48000,2,48000,2,48000,2},capture{48000,1,48000,1,48000,1};
    std::unique_ptr<webrtc::EchoControl> aec;
    // AEC3 at 48 kHz only adapts a linear filter in the 0-8 kHz band. Above that
    // it scales 8-24 kHz by one scalar: the deepest 4-8 kHz suppression gain.
    // During playback that removes consonants and air from the voice (muffling).
    // Split mode gives each upper QMF band its own 16 kHz AEC3 instance with a
    // real adaptive filter and per-frequency residual suppression. The 16 kHz
    // instances share the 48 kHz instance's block pipeline, so the band outputs
    // stay sample-aligned with the low band before synthesis.
    bool split_bands=false;
    std::array<std::unique_ptr<webrtc::EchoControl>,2> upper;
    std::array<std::unique_ptr<webrtc::AudioBuffer>,2> upper_render,upper_capture;
    // Match the measured AEC3 impulse delay so quiet/playback transitions never
    // move the microphone timeline. Keep AEC learning even while output is dry.
    std::array<float,430> dry_delay{};
    unsigned dry_index=0;
    int tail_frames=0;
    bool playback_seen=false;
    float wet=0;
    Echo(bool preserve_voice,int filter_blocks,bool split,bool upper_preserve){
        aec=make_aec(env,make_config(preserve_voice,filter_blocks),48000);
        split_bands=split;
        if(split)for(int b=0;b<2;b++){
            upper[b]=make_aec(env,make_config(upper_preserve,filter_blocks),16000);
            upper_render[b]=std::make_unique<webrtc::AudioBuffer>(16000,2,16000,2,16000,2);
            upper_capture[b]=std::make_unique<webrtc::AudioBuffer>(16000,1,16000,1,16000,1);
        }
    }
};
}
// Defaults: upstream 13-block filter (longer filters measured slower to converge
// on music), split upper bands tuned like the selected echo mode.
extern "C" __declspec(dllexport) void* cm_echo_create_tuned(int preserve_voice,int filter_blocks,int split_bands,int upper_preserve){
    try{return new Echo(preserve_voice!=0,filter_blocks,split_bands!=0,upper_preserve!=0);}catch(...){return nullptr;}
}
extern "C" __declspec(dllexport) void* cm_echo_create(){return cm_echo_create_tuned(1,13,1,1);}
extern "C" __declspec(dllexport) void* cm_echo_create_with_protection(int enabled){return cm_echo_create_tuned(enabled,13,1,enabled);}
extern "C" __declspec(dllexport) void cm_echo_destroy(void* p){delete static_cast<Echo*>(p);}
extern "C" __declspec(dllexport) int cm_echo_render(void* p,const float* reference){
    if(!p||!reference)return -1;
    auto& s=*static_cast<Echo*>(p);
    for(int i=0;i<480;i++){
        s.render.channels()[0][i]=reference[2*i]*32768.f;s.render.channels()[1][i]=reference[2*i+1]*32768.f;
        if(std::max(std::abs(reference[2*i]),std::abs(reference[2*i+1]))>0.0031622777f)s.playback_seen=true; // -50 dBFS
    }
    s.render.SplitIntoFrequencyBands();s.aec->AnalyzeRender(&s.render);
    if(s.split_bands)for(int b=0;b<2;b++){
        auto& r=*s.upper_render[b];
        for(int ch=0;ch<2;ch++)std::copy_n(s.render.split_bands(ch)[b+1],160,r.channels()[ch]);
        s.upper[b]->AnalyzeRender(&r);
    }
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
    if(s.split_bands)for(int b=0;b<2;b++){
        auto& c=*s.upper_capture[b];
        std::copy_n(s.capture.split_bands(0)[b+1],160,c.channels()[0]);
        s.upper[b]->AnalyzeCapture(&c);s.upper[b]->SetAudioBufferDelay(delay_ms);s.upper[b]->ProcessCapture(&c,false);
    }
    s.aec->SetAudioBufferDelay(delay_ms);s.aec->ProcessCapture(&s.capture,false);
    if(s.split_bands)for(int b=0;b<2;b++)std::copy_n(s.upper_capture[b]->channels()[0],160,s.capture.split_bands(0)[b+1]);
    s.capture.MergeFrequencyBands();
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
