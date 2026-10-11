const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { version } = require('../desktop/package.json');
import('../desktop/node_modules/@electron/packager/dist/index.js').then(({ packager }) => packager({
  dir: path.join(root, 'desktop'), name: 'ClearMic', appVersion: version, platform: 'win32', arch: 'x64',
  out: path.join(root, 'dist'), overwrite: true, asar: true, prune: true,
  icon: path.join(root, 'assets', 'clear-mic.ico'),
  extraResource: [path.join(root, 'dist', 'ClearMicAudio'), path.join(root, 'assets'), path.join(root, 'THIRD_PARTY')],
  ignore: [/[\\/](?:node_modules|\.test)(?:[\\/]|$)/],
  win32metadata: { CompanyName: 'Clear Mic contributors', FileDescription: 'Clear Mic', ProductName: 'Clear Mic' }
})).then(paths => console.log(paths.join('\n'))).catch(error => { console.error(error); process.exit(1); });
