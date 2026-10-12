# Clear Mic

A local Windows voice microphone app. Clear Mic combines RNNoise, WebRTC automatic volume, optional speaker echo cancellation, gentle compression and a peak limiter. No account, subscription, cloud inference, or GPU is required.

Version 1.5 adds a dedicated Singing preset. It also preserves the unmodified voice through the echo stage while speakers are quiet, adds adjustable noise strength, and matches preview loudness for easier listening comparisons. The app can create a dedicated Windows virtual microphone. The Electron interface and native audio process run locally; the interface uses software rendering and pauses meter updates when hidden in the tray.

## Download and use

Download the Windows ZIP from this repository's **Releases**, extract the entire folder, and run **ClearMic.exe**. Python and build tools are not required for the release.

1. Press **Create microphone**, then approve the Windows administrator prompt.
2. Choose your physical microphone. Clear Mic selects its new playback feed automatically.
3. Press **Turn on microphone**.
4. In Steam, a game, or your calling app, select the paired virtual **recording** endpoint as its microphone.

If using speakers, enable **Speaker echo cancellation** and choose the physical playback device actually playing your games/calls. Leave it off with headphones. Stop the microphone before changing those routing controls. AEC reduces playback leaking into the mic; it does not remove your own voice's room reflections.

In your game, select **CABLE Output (Clear Mic (VB-Audio Virtual Cable))**. The app sends processed audio to **Speakers (Clear Mic (VB-Audio Virtual Cable))**. These are two ends of the newly created device. Setup restores the existing Windows playback and recording defaults if Windows selects the newly created cable; it reports a warning if restoration is unavailable. A restart may be required by Windows; Clear Mic never restarts the PC automatically.

The microphone uses the unmodified, Microsoft-signed **VB-CABLE driver by VB-Audio**, bundled under the vendor's [distribution terms](https://vb-audio.com/Services/licensing.htm). VB-CABLE is proprietary donationware: it needs no subscription or cloud service, and [donations to its developer](https://vb-audio.com/Cable/) are welcome. The application source and RNNoise are open source; the bundled driver is not.

If ordinary VB-CABLE is already installed, Clear Mic preserves it and declines to create a second instance of that same driver. Select the existing cable instead. Existing Steam or other virtual endpoints remain available as alternatives. Setup checks pinned driver checksums and creates only `ROOT\CLEARMIC\0000`; removal targets only that owned device and keeps shared driver packages intact. Settings contains **Remove microphone** and the vendor's buffer control panel.

The app starts stopped. Settings and device names are remembered. Close-to-tray keeps audio running; choose **Quit** from the tray or Settings to stop and exit. Automatic microphone start and Windows sign-in launch are optional settings, both off by default. Keep the extracted app folder in a stable location before enabling sign-in launch.

## Speech controls

The default **Natural speech** preset is intentionally gentle:

| Stage | Default |
|---|---|
| Input trim | 0 dB |
| Speaker echo cancellation | Optional WebRTC AEC3, physical 48 kHz stereo playback reference |
| High-pass rumble reduction | 70 Hz, second-order |
| Noise removal | RNNoise, 48 kHz mono, 90% strength |
| Automatic volume | WebRTC AGC2; 18 dB maximum boost, speech/noise safeguards |
| Presence EQ | Neutral; adjustable ±3 dB at 2.8 kHz |
| Compressor | RMS detector, −20 dB threshold, 2:1 ratio, 6 dB soft knee |
| Compressor timing | 10 ms attack, 150 ms release |
| Makeup boost | 0 dB; automatic volume supplies adaptive gain |
| Output trim | 0 dB |
| Limiter | −1 dB sample-peak ceiling, 2 ms lookahead, 80 ms release |

**Noise strength** trades isolation for voice detail. Natural speech uses 90%; lower it if speech sounds overprocessed, or use 100% for the previous maximum RNNoise suppression. A lower strength also lets through more keyboard/background noise. The original and denoised paths are aligned to the same 20 ms RNNoise delay; this control adds no extra delay. Use **Even speech** for more level control or **Noise removal only** to hear RNNoise without voice shaping. High-pass, automatic volume, compression, and limiting can be disabled independently. Sliders and presets apply while audio is running. Automatic volume settles over several seconds and does not change the Windows or hardware microphone gain. Existing custom tuning is retained; shipped presets are upgraded to the new defaults.

**Singing** preserves held notes and vocal dynamics by starting with speech noise suppression, automatic volume and compression off. It keeps a gentle 40 Hz rumble cut, neutral EQ and the peak limiter. Set a fixed **Input trim** in Settings if needed, and retain headroom for louder notes. Compression can be enabled manually; the preset prepares a gentle 1.5:1 ratio with 25 ms attack and 250 ms release.

For a backing track played on this PC, keep **Speaker echo cancellation** on and select the physical speakers playing that track. AEC uses their playback reference to reduce bleed; it is not general music/vocal source separation, and separation is imperfect during simultaneous singing and playback. Music from a phone, external instrument, or another uncaptured source may still enter the microphone. With noise removal off, room/background noise is retained; enabling RNNoise may damage held notes or quiet singing because it is designed for speech. With headphones, AEC can be off as well, giving the Singing preset only the limiter's 2 ms DSP lookahead plus device buffers.

The limiter protects digital output peaks; it is not an oversampled intersample true-peak limiter. A microphone that clips before software processing needs lower hardware gain. No gate is added, so quiet word beginnings are not deliberately cut by another threshold stage.

On the Voice page, **Record 5 seconds** captures only after pressing the button. Compare **Original** and **Processed** on the playback device selected in Settings. Replaying Processed uses the current settings. **Match comparison volume** adjusts Original playback to the processed speech level, subject to a peak ceiling and 18 dB gain cap; switch it off to hear the microphone's actual input level. It does not alter saved recordings or the live microphone. With echo cancellation enabled, the preview also captures a speaker reference that stays in memory; the saved files contain only original/processed microphone audio. Record a new preview if enabling AEC after an ordinary preview. Stop live routing before preview recording. Short preview recordings and settings stay under `%LOCALAPPDATA%\ClearMic`; live audio is never saved. Open that folder from Settings to inspect or delete previews.

## Latency and performance

All processing is native CPU code using AVX2. RNNoise processes 480-sample / 10 ms frames. The peak limiter adds exactly 96 samples / 2 ms of lookahead. Optional AEC3 adds approximately 430 samples / 9 ms of measured impulse delay at 48 kHz in this build. RNNoise's own framing and Windows/virtual-driver buffering add further delay. Actual end-to-end delay depends on the devices and receiving application; filter-call processing time is not the full microphone latency.

Setup saves a conservative 3072-sample current VB-CABLE buffer when its control interface is available. Otherwise it reports that the microphone is created with the driver's current defaults. That number is a driver setting, not a measurement of total latency. On the development PC, shared-WASAPI synthetic loopback measured approximately **110–145 ms** across runs, including Windows stream buffering. A live FIFINE → RNNoise → virtual device check ran without audio warnings, with about **0.5 ms** average processing per frame. These measurements do not include a receiving game's buffering or network delay. Use **Driver controls** in Settings if an application needs a larger buffer; consult the bundled vendor manual before reducing it.

The new full chain with AEC ran at approximately 0.5–0.7 ms per 10 ms frame on the development Ryzen 7600X, with zero audio warnings during live routing. Synthetic stereo echo attenuation was approximately 35 dB after convergence. These measurements do not prove superiority to Discord or predict every room. [Research decisions and test limitations](RESEARCH.md) explain the implementation and evaluation.

Meters report input/output sample peaks, effective automatic gain, compressor/limiter reduction, processing time, warnings and input clipping. Speaker reference status is visible; dropped reference packets and discontinuities are available in backend diagnostics. Device names are resolved against the current WASAPI inventory. Windows COM is initialized on audio threads. No exclusive-mode capture is used. If the owned cable's stereo feed rejects playback, Clear Mic can use the compatible 16-channel feed of that same cable without changing the microphone selected in your game.

This Windows build requires Windows 10/11 x64 and an AVX2-capable CPU. An unsupported CPU is detected before inference starts. The downloadable executable is unsigned.

## Build from source

Install Python 3.14 x64, Node.js 22.12 or newer, and Visual Studio C++ x64 build tools, then:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe scripts\fetch_rnnoise.py
.venv\Scripts\python.exe scripts\fetch_webrtc.py
scripts\build_webrtc.cmd
scripts\build_native.cmd
.venv\Scripts\python.exe scripts\fetch_vbcable.py
scripts\build_device_setup.cmd
.venv\Scripts\python.exe -m unittest discover -s tests -v
npm ci --prefix desktop
npm start --prefix desktop
```

Create the portable Windows ZIP:

```powershell
.venv\Scripts\python.exe scripts\package.py
```

RNNoise source/model downloads come from official Xiph sources, pinned in `rnnoise.lock.json`. Community standalone extractions of WebRTC AEC3/AGC2 are pinned by source ZIP checksum and commit in `webrtc.lock.json`; Clear Mic adds small C bridges and reproducible MSVC fixes. The complete original VB-CABLE package is pinned in `vbcable.lock.json` and retained unchanged; it is downloaded during the build and is not committed to Git. Builds use local MSVC and CMake bundled with Visual Studio 2022. There are no Discord/Krisp libraries in this project.

For a synthetic processing check without microphone capture:

```powershell
.venv\Scripts\python.exe backend.py --self-test
# Or, with the packaged application:
.\resources\ClearMicAudio\ClearMicAudio.exe --self-test
```

Results are written to the app data folder's `self-test.json`. Tests cover high-pass response, compression, limiter peak ceilings, exact lookahead, transparent bypass, and invalid input. Temporary test settings can be isolated using `CLEARMIC_DATA_DIR`.

## Licensing

Application source: MIT. RNNoise and its model source use the upstream BSD-style notices retained in `THIRD_PARTY/RNNoise-COPYING`. WebRTC component licenses, patent grant and supplemental FFT/JsonCpp notices are retained in `THIRD_PARTY`. VB-CABLE has separate proprietary donationware terms, documented in `THIRD_PARTY/VB-CABLE-NOTICE.md`, the unchanged vendor package, and the vendor's current licensing page. Electron/Chromium, Python, NumPy, sounddevice/PortAudio, soundfile/libsndfile, and Pillow retain their own licenses. Distribution notices are included with the app.

Built around [Xiph RNNoise](https://github.com/xiph/rnnoise) and [python-sounddevice](https://python-sounddevice.readthedocs.io/).
