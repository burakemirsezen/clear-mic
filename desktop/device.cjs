const { execFile, spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

class VirtualDevice {
  constructor(resources, dataDir) {
    this.helper = path.join(resources, 'ClearMicDeviceSetup.exe');
    this.package = path.join(resources, 'vbcable');
    this.dataDir = dataDir;
    this.busy = false;
  }
  run(args) {
    return new Promise((resolve, reject) => execFile(this.helper, args, { windowsHide:true, timeout:15000 }, (error, stdout) => {
      try { const result=JSON.parse(stdout); if (result.error) reject(new Error(result.error)); else resolve(result); }
      catch { reject(error || new Error('Could not read virtual microphone setup status.')); }
    }));
  }
  status() { return this.run(['--status']); }
  install() { return this.change('--install'); }
  remove() { return this.change('--remove'); }
  setBuffer(samples) {
    if (![1536,2048,3072,7168].includes(samples)) return Promise.reject(new Error('Unsupported virtual microphone buffer size.'));
    return this.change('--set-buffer', String(samples));
  }
  controls() {
    const panel = spawn(path.join(this.package,'VBCABLE_ControlPanel.exe'),[],{detached:true,stdio:'ignore'});
    return new Promise((resolve,reject)=>{panel.once('error',reject);panel.once('spawn',()=>{panel.unref();resolve(true);});});
  }
  async change(action, argument) {
    if (this.busy) throw new Error('Virtual microphone setup is already running.');
    this.busy = true;
    const report = path.join(this.dataDir, 'logs', `device-setup-${crypto.randomUUID()}.json`);
    try {
      const current=await this.status();
      if (action==='--install'&&current.foreign_vbcable) throw new Error('VB-CABLE is already installed outside Clear Mic. Clear Mic will leave that device untouched.');
      if (action==='--remove'&&!current.installed) return current;
      if (action==='--set-buffer'&&(!current.installed||!current.buffer_samples)) throw new Error('Create the Clear Mic microphone first. Windows may need a restart before its buffer can be changed.');
      if (action==='--set-buffer'&&current.buffer_samples===Number(argument)) return current;
      if (action==='--install') await this.run(['--verify', this.package]);
      // Windows file names cannot contain quotes; quote paths for CreateProcess.
      const quote = value => '"' + value.replace(/(\\+)$/, '$1$1') + '"';
      const args = [action, argument ?? this.package, report].map(quote).join(' ');
      const script = "$ErrorActionPreference='Stop'; try { $p=Start-Process -FilePath $env:CLEARMIC_DEVICE_HELPER -ArgumentList $env:CLEARMIC_DEVICE_ARGS -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode } catch { exit 1223 }";
      await new Promise((resolve, reject) => {
        const process=spawn(path.join(global.process.env.SystemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe'),['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,stdio:'ignore',env:{...global.process.env,CLEARMIC_DEVICE_HELPER:this.helper,CLEARMIC_DEVICE_ARGS:args}});
        process.on('error',reject);process.on('exit',code=>code===0?resolve():reject(new Error(code===1223?'Windows administrator permission was cancelled.':`Virtual microphone setup failed (${code}).`)));
      }).catch(error=>{
        if(fs.existsSync(report)){const result=JSON.parse(fs.readFileSync(report,'utf8'));if(result.error)throw new Error(result.error);}
        throw error;
      });
      const result=JSON.parse(fs.readFileSync(report,'utf8'));
      if(result.error)throw new Error(result.error);
      return result;
    } finally { this.busy=false; }
  }
}
module.exports = { VirtualDevice };
