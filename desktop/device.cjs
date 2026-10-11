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
  controls() {
    const panel = spawn(path.join(this.package,'VBCABLE_ControlPanel.exe'),[],{detached:true,stdio:'ignore'});
    return new Promise((resolve,reject)=>{panel.once('error',reject);panel.once('spawn',()=>{panel.unref();resolve(true);});});
  }
  async change(action) {
    if (this.busy) throw new Error('Virtual microphone setup is already running.');
    this.busy = true;
    const report = path.join(this.dataDir, 'logs', `device-setup-${crypto.randomUUID()}.json`);
    try {
      const current=await this.status();
      if (action==='--install'&&current.foreign_vbcable) throw new Error('VB-CABLE is already installed outside Clear Mic. Clear Mic will leave that device untouched.');
      if (action==='--remove'&&!current.installed) return current;
      if (action==='--install') await this.run(['--verify', this.package]);
      // Windows file names cannot contain quotes; quote paths for CreateProcess.
      const quote = value => '"' + value.replace(/(\\+)$/, '$1$1') + '"';
      const args = [action, this.package, report].map(quote).join(' ');
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
