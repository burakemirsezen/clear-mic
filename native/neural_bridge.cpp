#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "localvqe_api.h"

namespace {
constexpr unsigned Frame=480,Hop=256,Taps=193,Queue=1024;
constexpr double Pi=3.14159265358979323846;
thread_local std::string last_error;
// Mirrored rings keep each FIR dot product contiguous; no allocation in process.
struct Fir {
    std::array<float,Taps*2> history{};unsigned position=0;
    void push(float x){history[position]=history[position+Taps]=x;position=(position+1)%Taps;}
    float get(const std::array<float,Taps>& coefficients)const{
        double sum=0;const float* h=history.data()+position+Taps-1;
        for(unsigned k=0;k<Taps;k++)sum+=coefficients[k]*h[-(int)k];
        return (float)sum;
    }
};
struct Neural {
    DWORD owner_thread=GetCurrentThreadId();int original_priority=GetThreadPriority(GetCurrentThread());
    localvqe_ctx_t model=0;
    std::array<float,Taps> coefficients{};
    Fir mic_filter,reference_filter,output_filter;
    std::array<float,Hop> mic{},reference{},result{};
    std::array<float,Queue> output{};
    unsigned down_phase=0,up_phase=0,input_count=0,read=0,write=Hop,count=Hop;
    Neural(const char* path,int threads){
        double sum=0;
        for(unsigned k=0;k<Taps;k++){
            const int m=(int)k-(Taps-1)/2;
            const double ideal=m?std::sin(2*Pi*7200/48000*m)/(Pi*m):2*7200.0/48000;
            const double window=.42-.5*std::cos(2*Pi*k/(Taps-1))+.08*std::cos(4*Pi*k/(Taps-1));
            coefficients[k]=(float)(ideal*window);sum+=coefficients[k];
        }
        for(float& x:coefficients)x=(float)(x/sum);
        auto options=localvqe_options_new();
        if(!options)throw std::runtime_error("Cannot allocate neural engine options");
        int status=localvqe_options_set_model_path(options,path);
        if(!status)status=localvqe_options_set_threads(options,threads);
        if(!status)model=localvqe_new_with_options(options);
        localvqe_options_free(options);
        if(status||!model){if(original_priority!=THREAD_PRIORITY_ERROR_RETURN)SetThreadPriority(GetCurrentThread(),original_priority);throw std::runtime_error("Cannot load the neural voice model. Extract the complete updated app folder.");}
    }
    ~Neural(){if(model)localvqe_free(model);if(GetCurrentThreadId()==owner_thread&&original_priority!=THREAD_PRIORITY_ERROR_RETURN)SetThreadPriority(GetCurrentThread(),original_priority);}
    void process(const float* input,const float* render,float* out){
        for(unsigned i=0;i<Frame;i++)if(!std::isfinite(input[i])||!std::isfinite(render[2*i])||!std::isfinite(render[2*i+1]))throw std::runtime_error("Invalid neural audio input");
        for(unsigned i=0;i<Frame;i++){
            mic_filter.push(input[i]);reference_filter.push((render[2*i]+render[2*i+1])*.5f);
            if(down_phase==0){
                mic[input_count]=mic_filter.get(coefficients);reference[input_count]=reference_filter.get(coefficients);
                if(++input_count==Hop){
                    if(localvqe_process_frame_f32(model,mic.data(),reference.data(),Hop,result.data()))throw std::runtime_error("Neural voice processing failed");
                    if(count+Hop>Queue)throw std::runtime_error("Neural output queue overflow");
                    for(float x:result){if(!std::isfinite(x))throw std::runtime_error("Neural model returned invalid audio");output[write]=x;write=(write+1)%Queue;}
                    count+=Hop;input_count=0;
                }
            }
            down_phase=(down_phase+1)%3;
        }
        for(unsigned i=0;i<Frame;i++){
            float x=0;
            if(up_phase==0){
                if(!count)throw std::runtime_error("Neural output queue underrun");
                x=3*output[read];read=(read+1)%Queue;--count;
            }
            output_filter.push(x);out[i]=output_filter.get(coefficients);up_phase=(up_phase+1)%3;
        }
    }
};
}
extern "C" __declspec(dllexport) void* cm_neural_create(const char* path,int threads){try{return new Neural(path,threads);}catch(const std::exception& e){last_error=e.what();return nullptr;}}
extern "C" __declspec(dllexport) const char* cm_neural_error(){return last_error.c_str();}
extern "C" __declspec(dllexport) void cm_neural_destroy(void* value){delete static_cast<Neural*>(value);}
extern "C" __declspec(dllexport) int cm_neural_process(void* value,const float* mic,const float* reference,float* output){
    if(!value||!mic||!reference||!output)return -1;
    try{static_cast<Neural*>(value)->process(mic,reference,output);return 0;}
    catch(const std::exception& e){last_error=e.what();return -2;}
}
// Fixed streaming delay: model OLA 16 ms + hop adapter 16 ms + two FIRs 4 ms.
extern "C" __declspec(dllexport) unsigned cm_neural_latency(){return 1728;}
