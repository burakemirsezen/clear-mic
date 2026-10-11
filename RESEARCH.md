# Voice processing decisions

Clear Mic 1.3 retains RNNoise and adds WebRTC AGC2 and optional AEC3. This is a practical CPU baseline for a Windows speech microphone. It has not been shown to outperform Discord in a matched listening test.

## Volume

WebRTC's [AGC2 implementation](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/agc2/adaptive_digital_gain_controller.cc) waits for consecutive confident speech frames before increasing gain, estimates speech headroom, limits gain using estimated noise, and smooths changes. Its [configuration API](https://webrtc.googlesource.com/src/+/refs/heads/main/api/audio/audio_processing.h) specifies adaptive gain after echo cancellation and noise suppression.

Clear Mic uses 6 dB headroom, at most 18 dB adaptive boost, 6 dB initial gain, 3 dB/s gain changes and a −50 dBFS estimated output-noise limit. These are conservative engineering choices for a dedicated microphone, not an industry loudness standard. The estimate is not a guaranteed noise ceiling. The final −1 dBFS sample-peak limiter remains active. Fixed makeup gain in Natural speech is reduced from 2 dB to 0 dB to avoid stacking boosts.

A checksum-pinned upstream spoken test clip, repeated for convergence and tested at three input levels 18 dB apart, produced final output RMS levels within 1 dB in the development test. This tests leveling, not perceptual speech quality. Quiet speech below the model's reliable detection range and excessively noisy input still need proper microphone gain and placement.

## Speaker isolation

[WebRTC AEC3](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/aec3/echo_canceller3.cc) consumes the playback reference separately from the microphone. Clear Mic captures the selected physical playback endpoint using [WASAPI loopback](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording). Windows converts that reference to 48 kHz stereo; both channels are supplied to AEC3 rather than averaged, because a mono average can cancel opposing stereo content.

Playback packets are kept in a bounded eight-frame queue. Live processing drains available render frames before each microphone block; it does not assume the speaker and microphone clocks produce one packet each at the same instant. Stale playback is discarded, silence is supplied when playback is idle, and a disconnected reference stops the route with an error. Dropped reference frames and discontinuities are exposed in backend diagnostics. This is a first implementation, not a claim of perfect clock synchronization or immunity to every Windows sound effect.

Echo cancellation is off by default in the public release; enable it for speakers and select the endpoint actually playing the game/call. It is unnecessary with headphones. Reference and microphone audio are not saved during live use. Explicit five-second previews retain their reference in memory so Processed can include AEC; only original and processed microphone WAVs are saved locally.

AEC3 adds approximately 430 samples / 9 ms of measured impulse delay at 48 kHz in this build, beyond RNNoise and limiter delay. A deterministic delayed-stereo echo test measured about 35 dB attenuation after convergence. That number describes the synthetic test, not this user's room or Discord.

## Room reflections and evaluation

Removing speaker echo does not remove the room's reflections of the speaker's own voice. [Shure's microphone guidance](https://www.shure.com/en-US/docs/education/Microphone-Techniques-for-Recording) supports improving direct sound through placement. Dedicated dereverberation is a different processing task. We have not enabled an additional dereverberation model in this release: preserving speech detail and predictable CPU use takes priority until matched recordings show a benefit.

Microsoft's [ICASSP 2022 AEC Challenge paper](https://www.microsoft.com/en-us/research/uploads/prod/2022/07/0009107.pdf) evaluates near-end speech, far-end echo and simultaneous speech separately; simple echo-reduction scores correlate poorly with perceived quality. Clear Mic tests clipping, silence/noise gain, delayed independent stereo echo, near-end preservation and preview alignment. `scripts/measure_voice.py` reports a deterministic double-talk stress case separately, including roughly 3 dB near-end attenuation in that deliberately difficult synthetic case. These regression metrics are not listening scores.

Before claiming a win against Discord: use the same input clips, match perceived output loudness, and compare voice detail, consonant/onset preservation, background noise and double-talk independently. Include changing speaker volume, long silence, keyboard transients and gaming load. RNNoise remains the noise-removal model; a quiet output by itself does not establish better voice quality.

## Reproducibility

The standalone WebRTC extractions are checksum-pinned in `webrtc.lock.json`. Their small compatibility shims and Microsoft compiler fixes are documented in source/build scripts. The algorithm implementations come from WebRTC; the extraction repositories are community maintained, not official WebRTC binary distributions. No field trials are enabled. Supplemental upstream and bundled FFT/JsonCpp notices are retained in `THIRD_PARTY`.

Run `python scripts/measure_voice.py report.json` for synthetic measurements and `python -m unittest discover -s tests -v` for regressions. These scripts do not open audio devices or send audio anywhere. Total microphone latency also includes Windows and VB-CABLE buffers and the receiving application.
