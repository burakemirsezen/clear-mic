// Windows shared-mode playback reference for AEC. Never writes audio to disk.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <functiondiscoverykeys_devpkey.h>
#include <avrt.h>
#include <wrl/client.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
using Microsoft::WRL::ComPtr;
namespace {
void check(HRESULT hr,const char* message){if(FAILED(hr))throw std::runtime_error(std::string(message)+" (Windows audio error "+std::to_string((unsigned long)hr)+")");}
std::wstring wide(const char* s){int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,nullptr,0);if(!n)throw std::runtime_error("Invalid speaker name");std::wstring w(n,0);MultiByteToWideChar(CP_UTF8,0,s,-1,w.data(),n);w.resize(n-1);return w;}
struct Reference {
    static constexpr unsigned Frames=8,Samples=960;
    std::thread worker;std::atomic<bool> stop{false},failed{false};
    std::mutex mutex;std::condition_variable ready_cv;bool ready=false;
    float ring[Frames][Samples]{},partial[Samples]{};unsigned read=0,write=0,count=0,used=0;
    std::atomic<unsigned> drops{0},discontinuities{0};
    std::chrono::steady_clock::time_point last_packet{};
    std::string error;
    ~Reference(){stop=true;if(worker.joinable())worker.join();}
    void push(float value){
        partial[used++]=value;
        if(used==Samples){
            std::lock_guard<std::mutex> lock(mutex);
            if(count==Frames){read=(read+1)%Frames;count--;drops++;}
            std::copy(partial,partial+Samples,ring[write]);write=(write+1)%Frames;count++;used=0;
            last_packet=std::chrono::steady_clock::now();
        }
    }
    void run(std::wstring name){
        HRESULT apartment=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        HANDLE event=nullptr,priority=nullptr;
        try {
            check(apartment,"Initialize speaker access");
            ComPtr<IMMDeviceEnumerator> enumerator;check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)),"Open speakers");
            ComPtr<IMMDeviceCollection> devices;check(enumerator->EnumAudioEndpoints(eRender,DEVICE_STATE_ACTIVE,&devices),"List speakers");
            UINT n=0;devices->GetCount(&n);ComPtr<IMMDevice> selected;unsigned matches=0;
            for(UINT i=0;i<n;i++){
                ComPtr<IMMDevice> device;devices->Item(i,&device);ComPtr<IPropertyStore> store;
                if(FAILED(device->OpenPropertyStore(STGM_READ,&store)))continue;
                PROPVARIANT value;PropVariantInit(&value);store->GetValue(PKEY_Device_FriendlyName,&value);
                if(value.vt==VT_LPWSTR&&value.pwszVal&&name==value.pwszVal){selected=device;matches++;}
                PropVariantClear(&value);
            }
            if(matches!=1)throw std::runtime_error("Selected speakers are unavailable or ambiguous. Stop, refresh devices and choose your speakers again.");
            ComPtr<IAudioClient> client;check(selected->Activate(__uuidof(IAudioClient),CLSCTX_ALL,nullptr,(void**)&client),"Open speaker reference");
            // Windows performs channel mixing and high-quality resampling for the reference.
            WAVEFORMATEX format{};format.wFormatTag=WAVE_FORMAT_IEEE_FLOAT;format.nChannels=1;format.nSamplesPerSec=48000;
            format.nChannels=2;format.wBitsPerSample=32;format.nBlockAlign=8;format.nAvgBytesPerSec=384000;
            event=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!event)throw std::runtime_error("Cannot create speaker event");
            DWORD flags=AUDCLNT_STREAMFLAGS_LOOPBACK|AUDCLNT_STREAMFLAGS_EVENTCALLBACK|AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM|AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
            check(client->Initialize(AUDCLNT_SHAREMODE_SHARED,flags,0,0,&format,nullptr),"Start speaker reference");
            check(client->SetEventHandle(event),"Set speaker event");
            ComPtr<IAudioCaptureClient> capture;check(client->GetService(IID_PPV_ARGS(&capture)),"Read speaker audio");
            DWORD task=0;priority=AvSetMmThreadCharacteristicsW(L"Audio",&task);
            check(client->Start(),"Capture speaker playback");
            {std::lock_guard<std::mutex> lock(mutex);ready=true;}ready_cv.notify_one();
            while(!stop){
                WaitForSingleObject(event,20);UINT available=0;check(capture->GetNextPacketSize(&available),"Check speaker reference");
                while(available&&!stop){
                    BYTE* data=nullptr;UINT length=0;DWORD status=0;
                    check(capture->GetBuffer(&data,&length,&status,nullptr,nullptr),"Capture speaker reference");
                    if(status&AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY)discontinuities++;
                    bool silent=(status&AUDCLNT_BUFFERFLAGS_SILENT)||!data;
                    auto* samples=reinterpret_cast<const float*>(data);
                    for(UINT i=0;i<length*2;i++)push(silent?0:samples[i]);
                    check(capture->ReleaseBuffer(length),"Release speaker reference");
                    check(capture->GetNextPacketSize(&available),"Check speaker reference");
                }
            }
            client->Stop();
        }catch(const std::exception& e){
            {std::lock_guard<std::mutex> lock(mutex);error=e.what();failed=true;ready=true;}ready_cv.notify_one();
        }
        if(priority)AvRevertMmThreadCharacteristics(priority);if(event)CloseHandle(event);if(SUCCEEDED(apartment))CoUninitialize();
    }
};
}
extern "C" __declspec(dllexport) void* cm_ref_create(const char* name,char* error,unsigned size){
    std::unique_ptr<Reference> r;
    try{
        r=std::make_unique<Reference>();auto speaker=wide(name);r->worker=std::thread([ptr=r.get(),speaker]{ptr->run(speaker);});
        std::unique_lock<std::mutex> lock(r->mutex);
        if(!r->ready_cv.wait_for(lock,std::chrono::seconds(5),[&]{return r->ready;}))throw std::runtime_error("Speaker reference startup timed out");
        if(r->failed)throw std::runtime_error(r->error);return r.release();
    }catch(const std::exception& e){if(error&&size){strncpy_s(error,size,e.what(),_TRUNCATE);}return nullptr;}
}
extern "C" __declspec(dllexport) void cm_ref_destroy(void* p){delete static_cast<Reference*>(p);}
// Callback never waits for the capture worker; at most eight frames are retained.
extern "C" __declspec(dllexport) int cm_ref_read(void* p,float* output){
    if(!p||!output)return -1;auto& r=*static_cast<Reference*>(p);if(r.failed)return -2;
    std::unique_lock<std::mutex> lock(r.mutex,std::try_to_lock);
    if(!lock.owns_lock()){std::fill(output,output+960,0.f);return 0;}
    if(!r.count||std::chrono::steady_clock::now()-r.last_packet>std::chrono::milliseconds(100)){
        r.count=0;r.read=r.write;std::fill(output,output+960,0.f);return 0;
    }
    std::copy(r.ring[r.read],r.ring[r.read]+960,output);r.read=(r.read+1)%Reference::Frames;r.count--;return 1;
}
extern "C" __declspec(dllexport) void cm_ref_stats(void* p,unsigned* output){
    if(!p||!output)return;auto& r=*static_cast<Reference*>(p);output[0]=r.drops;output[1]=r.discontinuities;
}
