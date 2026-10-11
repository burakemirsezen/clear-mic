#define UNICODE
#define _UNICODE
#include <windows.h>
#include <initguid.h>
#include <setupapi.h>
#include <newdev.h>
#include <cfgmgr32.h>
#include <devguid.h>
#include <devpkey.h>
#include <mmdeviceapi.h>
#include <devicetopology.h>
#include <functiondiscoverykeys_devpkey.h>
#include <propvarutil.h>
#include <wrl/client.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <vector>
#include <stdexcept>
#include <iomanip>
using Microsoft::WRL::ComPtr;
namespace fs=std::filesystem;
const wchar_t* INSTANCE=L"ROOT\\CLEARMIC\\0000";
const wchar_t HARDWARE[]=L"VBAudioVACWDM\0";
const wchar_t* ADAPTER=L"Clear Mic (VB-Audio Virtual Cable)";
void check(BOOL success,const char* action){if(!success)throw std::runtime_error(std::string(action)+" (Windows error "+std::to_string(GetLastError())+")");}
void hr(HRESULT result,const char* action){if(FAILED(result))throw std::runtime_error(std::string(action)+" (HRESULT "+std::to_string((unsigned long)result)+")");}
std::string utf8(const std::wstring& w){if(w.empty())return {};int n=WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),nullptr,0,nullptr,nullptr);std::string s(n,0);WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),s.data(),n,nullptr,nullptr);return s;}
std::string json(const std::wstring& value){std::string s="\"";for(unsigned char c:utf8(value)){if(c=='"'||c=='\\')s+='\\';if(c<32){std::ostringstream hex;hex<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<(unsigned)c;s+=hex.str();}else s+=c;}return s+'"';}
struct DeviceSet{HDEVINFO handle;DeviceSet():handle(SetupDiCreateDeviceInfoList(&GUID_DEVCLASS_MEDIA,nullptr)){if(handle==INVALID_HANDLE_VALUE)check(FALSE,"Open device list");}~DeviceSet(){SetupDiDestroyDeviceInfoList(handle);}};
bool admin(){SID_IDENTIFIER_AUTHORITY nt=SECURITY_NT_AUTHORITY;PSID group=nullptr;BOOL member=FALSE;if(AllocateAndInitializeSid(&nt,2,SECURITY_BUILTIN_DOMAIN_RID,DOMAIN_ALIAS_RID_ADMINS,0,0,0,0,0,0,&group)){CheckTokenMembership(nullptr,group,&member);FreeSid(group);}return member!=FALSE;}
std::wstring property(IPropertyStore* store,const PROPERTYKEY& key){PROPVARIANT v;PropVariantInit(&v);std::wstring s;if(SUCCEEDED(store->GetValue(key,&v))&&v.vt==VT_LPWSTR&&v.pwszVal)s=v.pwszVal;PropVariantClear(&v);return s;}
std::wstring deviceId(HDEVINFO set,SP_DEVINFO_DATA& device){wchar_t id[MAX_DEVICE_ID_LEN]{};check(SetupDiGetDeviceInstanceIdW(set,&device,id,MAX_DEVICE_ID_LEN,nullptr),"Read device identity");return id;}
bool ownId(const std::wstring& id){return _wcsicmp(id.c_str(),INSTANCE)==0;}
bool isVB(HDEVINFO set,SP_DEVINFO_DATA& device){wchar_t value[4096]{};DWORD type=0;if(!SetupDiGetDeviceRegistryPropertyW(set,&device,SPDRP_HARDWAREID,&type,(PBYTE)value,sizeof(value),nullptr))return false;for(const wchar_t* p=value;*p;p+=wcslen(p)+1)if(_wcsicmp(p,L"VBAudioVACWDM")==0)return true;return false;}
bool foreignVB(){HDEVINFO set=SetupDiGetClassDevsW(&GUID_DEVCLASS_MEDIA,nullptr,nullptr,0);if(set==INVALID_HANDLE_VALUE)check(FALSE,"Inspect audio devices");bool found=false;SP_DEVINFO_DATA device{sizeof(device)};for(DWORD i=0;SetupDiEnumDeviceInfo(set,i,&device);i++)if(isVB(set,device)&&!ownId(deviceId(set,device))){found=true;break;}SetupDiDestroyDeviceInfoList(set);return found;}
std::wstring adapterId(IMMDevice* device){ComPtr<IDeviceTopology> topology;if(FAILED(device->Activate(__uuidof(IDeviceTopology),CLSCTX_ALL,nullptr,(void**)&topology)))return {};ComPtr<IConnector> connector;if(FAILED(topology->GetConnector(0,&connector)))return {};LPWSTR id=nullptr;if(FAILED(connector->GetDeviceIdConnectedTo(&id)))return {};std::wstring result=id;CoTaskMemFree(id);return result;}
bool endpointIsOwn(IMMDevice* device,IPropertyStore* store){
    auto connection=adapterId(device);for(auto& c:connection)c=towupper(c);
    if(connection.find(L"ROOT#CLEARMIC#0000#")!=std::wstring::npos)return true;
    const auto id=property(store,PKEY_Device_InstanceId);
    if(ownId(id))return true;
    DEVINST node=0;if(CM_Locate_DevNodeW(&node,(DEVINSTID_W)id.c_str(),CM_LOCATE_DEVNODE_NORMAL)==CR_SUCCESS){
        for(int depth=0;depth<12;depth++){wchar_t name[MAX_DEVICE_ID_LEN]{};if(CM_Get_Device_IDW(node,name,MAX_DEVICE_ID_LEN,0)==CR_SUCCESS&&ownId(name))return true;DEVINST parent=0;if(CM_Get_Parent(&parent,node,0)!=CR_SUCCESS)break;node=parent;}
    }
    return false;
}
struct Endpoint{std::wstring id,name;EDataFlow flow;};
std::vector<Endpoint> endpoints(bool inspect=false){
    ComPtr<IMMDeviceEnumerator> enumerator;hr(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator)),"Open audio endpoints");
    ComPtr<IMMDeviceCollection> collection;hr(enumerator->EnumAudioEndpoints(eAll,DEVICE_STATE_ACTIVE,&collection),"List audio endpoints");UINT count=0;hr(collection->GetCount(&count),"Count audio endpoints");std::vector<Endpoint> result;
    for(UINT i=0;i<count;i++){
        ComPtr<IMMDevice> device;hr(collection->Item(i,&device),"Read audio endpoint");ComPtr<IPropertyStore> store;if(FAILED(device->OpenPropertyStore(STGM_READ,&store)))continue;
        auto name=property(store.Get(),PKEY_Device_FriendlyName);auto adapter=property(store.Get(),PKEY_DeviceInterface_FriendlyName);auto instance=property(store.Get(),PKEY_Device_InstanceId);
        if(inspect&&(name.find(L"Steam")!=std::wstring::npos||name.find(L"fifine")!=std::wstring::npos))std::cerr<<"Endpoint "<<utf8(name)<<"; adapter_id="<<utf8(adapterId(device.Get()))<<"\n";
        if(!endpointIsOwn(device.Get(),store.Get()))continue;
        ComPtr<IMMEndpoint> endpoint;hr(device.As(&endpoint),"Read endpoint type");EDataFlow flow;hr(endpoint->GetDataFlow(&flow),"Read endpoint direction");
        // Keep only the stereo playback feed, not VB-CABLE's optional 16-channel feed.
        if(flow==eRender&&name.find(L"16 Ch")!=std::wstring::npos)continue;
        LPWSTR id=nullptr;hr(device->GetId(&id),"Read endpoint identifier");result.push_back({id,name,flow});CoTaskMemFree(id);
    }return result;
}
std::string digest(const fs::path& path){std::ifstream file(path,std::ios::binary);if(!file)throw std::runtime_error("Driver file missing");BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)throw std::runtime_error("Cannot initialize checksum");DWORD size=0,returned=0;BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,(PUCHAR)&size,sizeof(size),&returned,0);std::vector<unsigned char> object(size),buffer(65536);unsigned char bytes[32]{};if(BCryptCreateHash(alg,&hash,object.data(),size,nullptr,0,0)<0){BCryptCloseAlgorithmProvider(alg,0);throw std::runtime_error("Cannot create checksum");}while(file){file.read((char*)buffer.data(),buffer.size());if(BCryptHashData(hash,buffer.data(),(ULONG)file.gcount(),0)<0)throw std::runtime_error("Checksum failed");}BCryptFinishHash(hash,bytes,32,0);BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(alg,0);std::ostringstream hex;for(auto b:bytes)hex<<std::hex<<std::setw(2)<<std::setfill('0')<<(unsigned)b;return hex.str();}
void verify(const fs::path& folder){
    const std::pair<const wchar_t*,const char*> files[]={
        {L"vbMmeCable64_win10.inf","61c857be74831cc299d9be62f8d49d137f14063454fc54f859d5bc9b4b813daf"},
        {L"vbaudio_cable64_win10.sys","f01344602472f1b527de5ee98f18987c03db48fea444e457d061e937f1d531d5"},
        {L"vbaudio_cable64_win10.cat","0a921ebadbe39cf3fa7c14ff37d1ca22565a9651244bd3ac177dc810bc99072e"}};
    for(auto& f:files)if(digest(folder/f.first)!=f.second)throw std::runtime_error("Driver package checksum mismatch. Installation refused.");
}
bool installed(){DeviceSet set;SP_DEVINFO_DATA device{sizeof(device)};return SetupDiOpenDeviceInfoW(set.handle,INSTANCE,nullptr,0,&device)!=FALSE&&isVB(set.handle,device);}
#include "audio_defaults.h"
// Pack45's unchanged control panel uses this interface and buffer command.
// Check the PnP identity before opening the control interface.
HANDLE cableControl(){
    const GUID control={0xd657ec7b,0xe6cc,0x48c6,{0x9a,0x35,0xc0,0xf9,0x07,0xe5,0xda,0xb9}};
    HDEVINFO set=SetupDiGetClassDevsW(&control,nullptr,nullptr,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
    if(set==INVALID_HANDLE_VALUE)return INVALID_HANDLE_VALUE;
    HANDLE handle=INVALID_HANDLE_VALUE;SP_DEVICE_INTERFACE_DATA item{sizeof(item)};
    for(DWORD i=0;SetupDiEnumDeviceInterfaces(set,nullptr,&control,i,&item);i++){
        DWORD size=0;SetupDiGetDeviceInterfaceDetailW(set,&item,nullptr,0,&size,nullptr);
        if(!size)continue;
        std::vector<BYTE> bytes(size);auto detail=(PSP_DEVICE_INTERFACE_DETAIL_DATA_W)bytes.data();detail->cbSize=sizeof(*detail);SP_DEVINFO_DATA device{sizeof(device)};
        if(SetupDiGetDeviceInterfaceDetailW(set,&item,detail,size,nullptr,&device)){
            if(!ownId(deviceId(set,device))||!isVB(set,device))continue;
            handle=CreateFileW(detail->DevicePath,GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0x800,nullptr);break;
        }
    }
    SetupDiDestroyDeviceInfoList(set);return handle;
}
DWORD currentBuffer(){HANDLE handle=cableControl();if(handle==INVALID_HANDLE_VALUE)return 0;DWORD state[104]{},returned=0;BOOL ok=DeviceIoControl(handle,0x222024,nullptr,0,state,sizeof(state),&returned,nullptr);CloseHandle(handle);return ok&&returned>=sizeof(state)?state[103]:0;}
void setBuffer(DWORD samples,bool persist){
    if(samples!=1536&&samples!=2048&&samples!=3072&&samples!=7168)throw std::runtime_error("Unsupported buffer size");
    if(!installed()||foreignVB())throw std::runtime_error("Buffer settings require Clear Mic's dedicated device only.");
    if(persist){
        if(!admin())throw std::runtime_error("Administrator permission is required to save driver buffering.");
        for(const auto key:{L"SOFTWARE\\VB-Audio\\Cable",L"SYSTEM\\CurrentControlSet\\Services\\VB-Cable"}){
            HKEY registry=nullptr;LSTATUS result=RegCreateKeyExW(HKEY_LOCAL_MACHINE,key,0,nullptr,0,KEY_SET_VALUE|KEY_WOW64_64KEY,nullptr,&registry,nullptr);
            if(result!=ERROR_SUCCESS)throw std::runtime_error("Cannot save virtual microphone buffer setting");
            result=RegSetValueExW(registry,L"VBAudioCableWDM_Latency",0,REG_DWORD,(BYTE*)&samples,sizeof(samples));RegCloseKey(registry);
            if(result!=ERROR_SUCCESS)throw std::runtime_error("Cannot save virtual microphone buffer setting");
        }
    }
    HANDLE handle=cableControl();if(handle==INVALID_HANDLE_VALUE)throw std::runtime_error("Virtual microphone control interface is unavailable");
    DWORD response=~0u,returned=0;BOOL ok=DeviceIoControl(handle,0x22204c,&samples,sizeof(samples),&response,sizeof(response),&returned,nullptr);CloseHandle(handle);
    check(ok,"Apply virtual microphone buffering");
    if(currentBuffer()!=samples)throw std::runtime_error("Driver did not confirm the requested buffer setting");
}
bool install(const fs::path& folder){
    verify(folder);if(!admin())throw std::runtime_error("Administrator permission is required to create a virtual microphone.");
    if(foreignVB())throw std::runtime_error("VB-CABLE is already installed outside Clear Mic. A second instance is not supported; the existing device was left unchanged.");
    {DeviceSet existing;SP_DEVINFO_DATA device{sizeof(device)};if(SetupDiOpenDeviceInfoW(existing.handle,INSTANCE,nullptr,0,&device)&&isVB(existing.handle,device)){ULONG flags=0,problem=0;if(CM_Get_DevNode_Status(&flags,&problem,device.DevInst,0)==CR_SUCCESS&&!problem&&(flags&DN_STARTED))return false;}}
    auto originalInf=fs::absolute(folder/L"vbMmeCable64_win10.inf").wstring();wchar_t publishedInf[MAX_PATH]{};
    check(SetupCopyOEMInfW(originalInf.c_str(),folder.c_str(),SPOST_PATH,0,publishedInf,MAX_PATH,nullptr,nullptr),"Stage Microsoft-signed driver package");
    DeviceSet set;SP_DEVINFO_DATA device{sizeof(device)};bool created=false;
    if(!SetupDiOpenDeviceInfoW(set.handle,INSTANCE,nullptr,0,&device)){
        check(SetupDiCreateDeviceInfoW(set.handle,INSTANCE,&GUID_DEVCLASS_MEDIA,ADAPTER,nullptr,0,&device),"Create Clear Mic device");
        check(SetupDiSetDeviceRegistryPropertyW(set.handle,&device,SPDRP_HARDWAREID,(const BYTE*)HARDWARE,sizeof(HARDWARE)),"Set signed driver hardware identity");
        check(SetupDiCallClassInstaller(DIF_REGISTERDEVICE,set.handle,&device),"Register Clear Mic device");created=true;
    }else if(!isVB(set.handle,device))throw std::runtime_error("Clear Mic device identity is occupied by another driver.");
    try{
        SP_DEVINSTALL_PARAMS_W params{sizeof(params)};check(SetupDiGetDeviceInstallParamsW(set.handle,&device,&params),"Read install parameters");params.Flags|=DI_ENUMSINGLEINF|DI_QUIETINSTALL;wcscpy_s(params.DriverPath,publishedInf);check(SetupDiSetDeviceInstallParamsW(set.handle,&device,&params),"Select exact signed driver package");
        check(SetupDiBuildDriverInfoList(set.handle,&device,SPDIT_COMPATDRIVER),"Read compatible signed driver");check(SetupDiCallClassInstaller(DIF_SELECTBESTCOMPATDRV,set.handle,&device),"Select compatible driver");
        SP_DRVINFO_DATA_W driver{sizeof(driver)};check(SetupDiGetSelectedDriverW(set.handle,&device,&driver),"Read selected driver");BOOL restart=FALSE;
        check(DiInstallDevice(nullptr,set.handle,&device,&driver,0,&restart),"Install Clear Mic virtual driver");
        check(SetupDiSetDeviceRegistryPropertyW(set.handle,&device,SPDRP_FRIENDLYNAME,(const BYTE*)ADAPTER,(DWORD)((wcslen(ADAPTER)+1)*sizeof(wchar_t))),"Name Clear Mic adapter");
        check(SetupDiGetDeviceInstallParamsW(set.handle,&device,&params),"Read install result");return restart||(params.Flags&(DI_NEEDREBOOT|DI_NEEDRESTART))!=0;
    }catch(...){if(created)SetupDiCallClassInstaller(DIF_REMOVE,set.handle,&device);throw;}
}
bool remove(){
    if(!admin())throw std::runtime_error("Administrator permission is required to remove a virtual microphone.");
    DeviceSet set;SP_DEVINFO_DATA device{sizeof(device)};
    if(!SetupDiOpenDeviceInfoW(set.handle,INSTANCE,nullptr,0,&device))return false;
    if(!isVB(set.handle,device))throw std::runtime_error("Device identity does not belong to Clear Mic.");
    SP_REMOVEDEVICE_PARAMS params{};params.ClassInstallHeader.cbSize=sizeof(SP_CLASSINSTALL_HEADER);params.ClassInstallHeader.InstallFunction=DIF_REMOVE;params.Scope=DI_REMOVEDEVICE_GLOBAL;
    check(SetupDiSetClassInstallParamsW(set.handle,&device,&params.ClassInstallHeader,sizeof(params)),"Prepare Clear Mic removal");
    check(SetupDiCallClassInstaller(DIF_REMOVE,set.handle,&device),"Remove Clear Mic virtual microphone");
    SP_DEVINSTALL_PARAMS_W state{sizeof(state)};
    return !SetupDiGetDeviceInstallParamsW(set.handle,&device,&state)||(state.Flags&(DI_NEEDREBOOT|DI_NEEDRESTART))!=0;
}

std::string status(bool reboot=false){auto list=endpoints();std::ostringstream out;out<<"{\"installed\":"<<(installed()?"true":"false")<<",\"foreign_vbcable\":"<<(foreignVB()?"true":"false")<<",\"buffer_samples\":"<<currentBuffer()<<",\"reboot_required\":"<<(reboot?"true":"false")<<",\"endpoints\":[";for(size_t i=0;i<list.size();i++){if(i)out<<',';out<<"{\"id\":"<<json(list[i].id)<<",\"name\":"<<json(list[i].name)<<",\"flow\":\""<<(list[i].flow==eCapture?"input":"output")<<"\"}";}out<<"]}";return out.str();}
int wmain(int argc,wchar_t** argv){
    std::string result;int code=0;fs::path report;
    try{
        hr(CoInitializeEx(nullptr,COINIT_MULTITHREADED),"Initialize Windows audio setup");
        std::wstring action=argc>1?argv[1]:L"--status";
        if(argc>3)report=argv[3];
        if(action==L"--install"){
            if(argc<3)throw std::runtime_error("Driver package path required");const auto previous=audioDefaults();bool reboot=install(argv[2]);
            for(int i=0;i<50;i++){if(endpoints().size()>=2)break;Sleep(200);}
            std::string warning;
            try{restoreDefaults(previous);}catch(const std::exception&){warning="The microphone was created, but Windows audio defaults could not be restored. Check the default playback and recording devices in Windows Settings.";}
            if(!reboot){try{setBuffer(3072,true);}catch(const std::exception&){if(warning.empty())warning="The microphone was created. Driver buffering will use its current defaults until Windows can open the buffer control interface.";}}
            result=status(reboot);
            if(!warning.empty()){result.pop_back();result+=",\"warning\":"+json(std::wstring(warning.begin(),warning.end()))+"}";}
        }else if(action==L"--remove"){result=status(remove());}
        else if(action==L"--verify"){if(argc<3)throw std::runtime_error("Driver package path required");verify(argv[2]);result="{\"package_verified\":true}";}
        else if(action==L"--inspect"){endpoints(true);result=status();}
        else if(action==L"--status")result=status();
        else throw std::runtime_error("Unsupported setup action");
    }catch(const std::exception& e){std::string message=e.what();result="{\"error\":"+json(std::wstring(message.begin(),message.end()))+"}";code=1;}
    if(!report.empty()){std::ofstream file(report,std::ios::binary);file<<result;}
    std::cout<<result<<std::endl;CoUninitialize();return code;
}
