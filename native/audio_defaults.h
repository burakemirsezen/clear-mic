#pragma once
#include <audioclient.h>

// Windows has no public setter for default endpoints. This private COM interface
// is also used by AudioDeviceCmdlets. Only restore defaults replaced by our device.
struct __declspec(uuid("f8679f50-850a-41cf-9c72-430f290290c8")) AudioPolicy : IUnknown {
    virtual HRESULT STDMETHODCALLTYPE GetMixFormat(LPCWSTR,WAVEFORMATEX**)=0;
    virtual HRESULT STDMETHODCALLTYPE GetDeviceFormat(LPCWSTR,BOOL,WAVEFORMATEX**)=0;
    virtual HRESULT STDMETHODCALLTYPE ResetDeviceFormat(LPCWSTR)=0;
    virtual HRESULT STDMETHODCALLTYPE SetDeviceFormat(LPCWSTR,WAVEFORMATEX*,WAVEFORMATEX*)=0;
    virtual HRESULT STDMETHODCALLTYPE GetProcessingPeriod(LPCWSTR,BOOL,LONGLONG*,LONGLONG*)=0;
    virtual HRESULT STDMETHODCALLTYPE SetProcessingPeriod(LPCWSTR,LONGLONG*)=0;
    virtual HRESULT STDMETHODCALLTYPE GetShareMode(LPCWSTR,void*)=0;
    virtual HRESULT STDMETHODCALLTYPE SetShareMode(LPCWSTR,void*)=0;
    virtual HRESULT STDMETHODCALLTYPE GetPropertyValue(LPCWSTR,BOOL,const PROPERTYKEY&,PROPVARIANT*)=0;
    virtual HRESULT STDMETHODCALLTYPE SetPropertyValue(LPCWSTR,BOOL,const PROPERTYKEY&,const PROPVARIANT*)=0;
    virtual HRESULT STDMETHODCALLTYPE SetDefaultEndpoint(LPCWSTR,ERole)=0;
    virtual HRESULT STDMETHODCALLTYPE SetEndpointVisibility(LPCWSTR,BOOL)=0;
};
struct SavedDefault { EDataFlow flow;ERole role;std::wstring id; };
std::vector<SavedDefault> audioDefaults(){
    ComPtr<IMMDeviceEnumerator> enumerator;hr(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)),"Read Windows audio defaults");
    std::vector<SavedDefault> result;
    for(auto flow:{eRender,eCapture})for(auto role:{eConsole,eMultimedia,eCommunications}){
        ComPtr<IMMDevice> device;if(FAILED(enumerator->GetDefaultAudioEndpoint(flow,role,&device)))continue;
        LPWSTR id=nullptr;hr(device->GetId(&id),"Read default endpoint identity");result.push_back({flow,role,id});CoTaskMemFree(id);
    }
    return result;
}
void restoreDefaults(const std::vector<SavedDefault>& previous){
    const CLSID client={0x870af99c,0x171d,0x4f9e,{0xaf,0x0d,0xe6,0x3d,0xf4,0x0c,0x2b,0xc9}};
    ComPtr<AudioPolicy> policy;
    ComPtr<IMMDeviceEnumerator> enumerator;hr(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)),"Restore Windows audio defaults");
    for(const auto& item:previous){
        ComPtr<IMMDevice> current,original;ComPtr<IPropertyStore> store;
        if(FAILED(enumerator->GetDefaultAudioEndpoint(item.flow,item.role,&current)))continue;
        LPWSTR id=nullptr;hr(current->GetId(&id),"Read current audio default");bool same=item.id==id;CoTaskMemFree(id);if(same)continue;
        if(FAILED(current->OpenPropertyStore(STGM_READ,&store))||!endpointIsOwn(current.Get(),store.Get()))continue;
        if(FAILED(enumerator->GetDevice(item.id.c_str(),&original)))continue;
        DWORD state=0;if(FAILED(original->GetState(&state))||state!=DEVICE_STATE_ACTIVE)continue;
        if(!policy)hr(CoCreateInstance(client,nullptr,CLSCTX_ALL,__uuidof(AudioPolicy),(void**)&policy),"Open Windows audio default policy");
        hr(policy->SetDefaultEndpoint(item.id.c_str(),item.role),"Restore previous Windows audio device");
    }
}
