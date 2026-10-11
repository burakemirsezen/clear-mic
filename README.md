# Clear Mic

A local Windows voice microphone app. Clear Mic runs RNNoise on the CPU, then gives speech consistent volume with gentle compression and a peak limiter. No account, subscription, cloud inference, or GPU is required.

## Download and use

Download the Windows ZIP from this repository's **Releases**, extract the entire folder, and run **ClearMic.exe**. Python and build tools are not required for the release.

1. Choose your physical microphone.
2. Choose an **existing virtual playback endpoint** as the output.
3. Press **Start microphone**.
4. In Steam, a game, or your calling app, select the paired virtual **recording** endpoint as its microphone.

For example, `Speakers (Steam Streaming Microphone)` may pair with `Microphone (Steam Streaming Microphone)`. With a virtual cable, its playback side often contains `CABLE Input`, and the receiving app selects `CABLE Output`. Availability depends on installed drivers. Clear Mic processes and routes audio; it **does not install a virtual audio driver** or change your Windows default devices.

The app starts stopped. Settings and device names are remembered. Close-to-tray keeps audio running; choose **Quit** from the tray or Settings to stop and exit. Automatic microphone start and Windows sign-in launch are optional settings, both off by default. Keep the extracted app folder in a stable location before enabling sign-in launch.

## Speech controls

The default **Natural speech** preset is intentionally gentle:

| Stage | Default |
|---|---|
| Input trim | 0 dB |
| High-pass rumble reduction | 70 Hz, second-order |
| Noise removal | RNNoise, 48 kHz mono |
| Presence EQ | Neutral; adjustable ±3 dB at 2.8 kHz |
| Compressor | RMS detector, −20 dB threshold, 2:1 ratio, 6 dB soft knee |
| Compressor timing | 10 ms attack, 150 ms release |
| Makeup boost | 2 dB |
| Output trim | 0 dB |
| Limiter | −1 dB sample-peak ceiling, 2 ms lookahead, 80 ms release |

Use **Even speech** for more level control or **Noise removal only** to hear RNNoise without voice shaping. High-pass, compression, and limiting can be disabled independently. Sliders and presets apply while audio is running.

The limiter protects digital output peaks; it is not an oversampled intersample true-peak limiter. A microphone that clips before software processing needs lower hardware gain. No gate is added, so quiet word beginnings are not deliberately cut by another threshold stage.

On the Voice tab, **Record 5s preview** captures only after pressing the button. Compare **Original** and **Processed** on the playback device selected in Settings. Replaying Processed uses the current settings. Stop live routing before preview recording. Short preview recordings and settings stay under `%LOCALAPPDATA%\ClearMic`; live audio is never saved. Open that folder from Settings to inspect or delete previews.

## Latency and performance

All processing is native CPU code using AVX2. RNNoise processes 480-sample / 10 ms frames. The peak limiter adds exactly 96 samples / 2 ms of lookahead. RNNoise's own framing and Windows/virtual-driver buffering add further delay. Actual end-to-end delay depends on the devices and receiving application; filter-call processing time is not the full microphone latency.

Meters report input and output levels, compressor/limiter gain reduction, processing time, audio warnings, and input clipping. Saved device names are resolved against the current WASAPI inventory rather than assuming permanent device numbers. Windows COM is initialized on audio background threads. No exclusive-mode capture is used.

This Windows build requires Windows 10/11 x64 and an AVX2-capable CPU. An unsupported CPU is detected before inference starts. The downloadable executable is unsigned.

## Build from source

Install Python 3.14 x64 and Visual Studio C++ x64 build tools, then:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe scripts\fetch_rnnoise.py
scripts\build_native.cmd
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe main.py
```

Create the portable Windows ZIP:

```powershell
.venv\Scripts\python.exe scripts\package.py
```

Source and model downloads come from official Xiph sources and are pinned by commit and SHA-256 in `rnnoise.lock.json`. Builds use local MSVC. There are no proprietary Discord/Krisp libraries in this project.

For a synthetic processing check without microphone capture:

```powershell
.venv\Scripts\python.exe main.py --self-test
# Or, with the packaged application:
.\ClearMic.exe --self-test
```

Results are written to the app data folder's `self-test.json`. Tests cover high-pass response, compression, limiter peak ceilings, exact lookahead, transparent bypass, and invalid input. Temporary test settings can be isolated using `CLEARMIC_DATA_DIR`.

## Licensing

Application source: MIT. RNNoise and its model source use the upstream BSD-style notices retained in `THIRD_PARTY/RNNoise-COPYING`. Python, NumPy, sounddevice/PortAudio, soundfile/libsndfile, Pillow, and pystray retain their own licenses. Distribution notices are included with the app.

Built around [Xiph RNNoise](https://github.com/xiph/rnnoise) and [python-sounddevice](https://python-sounddevice.readthedocs.io/).
