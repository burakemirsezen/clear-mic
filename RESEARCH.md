# Voice processing decisions

Clear Mic 1.5 retains RNNoise and adds WebRTC AGC2 and optional AEC3. This is a practical CPU baseline for a Windows speech microphone. It has not been shown to outperform Discord in a matched listening test.

## Preserve speech detail

Version 1.4 adds a time-aligned original/denoised blend. Natural speech uses 90% denoised output and 10% original signal after input trim and high-pass filtering; Noise removal only retains 100% RNNoise. Strength changes ramp over 20 ms to avoid clicks. Both paths retain RNNoise's measured 960-sample / 20 ms delay, so the control adds no latency. More original signal preserves detail but also retains more background noise; this is a tradeoff, not a free improvement or a guarantee of noise attenuation.

This is an engineering adaptation of a common attenuation-limit approach: [DeepFilterNet's implementation](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/libDF/src/tract.rs) limits attenuation by mixing the original and enhanced spectra. Clear Mic uses an aligned time-domain blend with RNNoise instead. [DeepFilterNet research](https://arxiv.org/abs/2305.08227) makes it a candidate for a future model comparison; that model is not bundled here and no quality claim is transferred from its paper to this app.

Noise suppression, automatic gain and echo suppression must be assessed separately. The preview's optional loudness matching raises or lowers Original to the processed speech RMS using the same active regions, bounded by a sample-peak ceiling and 18 dB gain cap. Saved recordings and the actual live stream are unchanged. Loudness matching is approximate, not a perceptual loudness standard.

## Singing

RNNoise's [original paper](https://arxiv.org/abs/1709.08243) addresses speech enhancement; it does not establish faithful singing reconstruction. Clear Mic therefore does not treat the speech preset as a general vocal recording chain. [RFC 7874 section 4](https://www.rfc-editor.org/rfc/rfc7874.html#section-4) recommends manual rather than automatic gain for music applications. Our Singing preset is an engineering application of that principle: AGC2, RNNoise and compression start disabled; input trim remains manual, with a 40 Hz high-pass and −1 dBFS sample-peak limiter. Optional compression is prepared at 1.5:1, 25 ms attack and 250 ms release. No speech gate or speech-confidence rule determines whether a note survives.

The existing physical-speaker AEC reference can include PC backing music. This can reduce playback bleed but is not blind source separation or perfect stem extraction. AEC3 is built for communication audio and still requires a listening check for sustained singing during loud accompaniment. The Singing preset does not change the selected speaker endpoint or the AEC toggle. External music without a captured reference cannot be reliably subtracted; background noise remains when RNNoise is off. The preset has synthetic sustained-note/vibrato, level-dynamics and timing regressions, not a human singing quality benchmark.

## Volume

WebRTC's [AGC2 implementation](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/agc2/adaptive_digital_gain_controller.cc) waits for consecutive confident speech frames before increasing gain, estimates speech headroom, limits gain using estimated noise, and smooths changes. Its [configuration API](https://webrtc.googlesource.com/src/+/refs/heads/main/api/audio/audio_processing.h) specifies adaptive gain after echo cancellation and noise suppression.

Clear Mic uses 6 dB headroom, at most 18 dB adaptive boost, 6 dB initial gain, 3 dB/s gain changes and a −50 dBFS estimated output-noise limit. These are conservative engineering choices for a dedicated microphone, not an industry loudness standard. The estimate is not a guaranteed noise ceiling. The final −1 dBFS sample-peak limiter remains active. Fixed makeup gain in Natural speech is reduced from 2 dB to 0 dB to avoid stacking boosts.

A checksum-pinned upstream spoken test clip, repeated for convergence and tested at three input levels 18 dB apart, produced final output RMS levels within 1 dB in the development test. This tests leveling, not perceptual speech quality. Quiet speech below the model's reliable detection range and excessively noisy input still need proper microphone gain and placement.

## Speaker isolation

[WebRTC AEC3](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/aec3/echo_canceller3.cc) consumes the playback reference separately from the microphone. Clear Mic captures the selected physical playback endpoint using [WASAPI loopback](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording). Windows converts that reference to 48 kHz stereo; both channels are supplied to AEC3 rather than averaged, because a mono average can cancel opposing stereo content.

Playback packets are kept in a bounded eight-frame queue. Live processing drains available render frames before each microphone block; it does not assume the speaker and microphone clocks produce one packet each at the same instant. Stale playback is discarded, silence is supplied when playback is idle, and a disconnected reference stops the route with an error. Dropped reference frames and discontinuities are exposed in backend diagnostics. This is a first implementation, not a claim of perfect clock synchronization or immunity to every Windows sound effect.

Echo cancellation is off by default in the public release; enable it for speakers and select the endpoint actually playing the game/call. It is unnecessary with headphones. Reference and microphone audio are not saved during live use. Explicit five-second previews retain their reference in memory so Processed can include AEC; only original and processed microphone WAVs are saved locally.

When speaker reference exceeds −50 dBFS sample peak, Clear Mic fades into AEC over 10 ms. It holds that path for 700 ms after the last active reference block to cover playback reflections, then fades back over 50 ms to the original microphone delayed by 430 samples. AEC keeps running to retain its adaptation state. The quiet path now reproduces input samples exactly; the delay stays fixed across transitions. A local route check exposed a reference background around −56 dBFS that would keep a lower threshold continuously engaged. The −50 dB threshold and tail duration are engineering choices, not universal acoustic guarantees. Very quiet playback below the threshold may pass through; sufficiently loud background playback can keep AEC engaged. This does not bypass RNNoise or downstream voice filters. The UI reports the actual echo-processing state, including the held tail.

AEC3 adds approximately 430 samples / 9 ms of measured impulse delay at 48 kHz in this build, beyond RNNoise and limiter delay. A deterministic delayed-stereo echo test measured about 35 dB attenuation after convergence. That number describes the synthetic test, not this user's room or Discord.

## Room reflections and evaluation

Removing speaker echo does not remove the room's reflections of the speaker's own voice. [Shure's microphone guidance](https://www.shure.com/en-US/docs/education/Microphone-Techniques-for-Recording) supports improving direct sound through placement. Dedicated dereverberation is a different processing task. We have not enabled an additional dereverberation model in this release: preserving speech detail and predictable CPU use takes priority until matched recordings show a benefit.

Microsoft's [ICASSP 2022 AEC Challenge paper](https://www.microsoft.com/en-us/research/uploads/prod/2022/07/0009107.pdf) evaluates near-end speech, far-end echo and simultaneous speech separately; simple echo-reduction scores correlate poorly with perceived quality. Clear Mic tests clipping, silence/noise gain, delayed independent stereo echo, near-end preservation and preview alignment. `scripts/measure_voice.py` reports a deterministic double-talk stress case separately, including roughly 3 dB near-end attenuation in that deliberately difficult synthetic case. These regression metrics are not listening scores.

Before claiming a win against Discord: use the same input clips, match perceived output loudness, and compare voice detail, consonant/onset preservation, background noise and double-talk independently. Include changing speaker volume, long silence, keyboard transients and gaming load. RNNoise remains the noise-removal model; a quiet output by itself does not establish better voice quality.

## Reproducibility

The standalone WebRTC extractions are checksum-pinned in `webrtc.lock.json`. Their small compatibility shims and Microsoft compiler fixes are documented in source/build scripts. The algorithm implementations come from WebRTC; the extraction repositories are community maintained, not official WebRTC binary distributions. No field trials are enabled. Supplemental upstream and bundled FFT/JsonCpp notices are retained in `THIRD_PARTY`.

Run `python scripts/measure_voice.py report.json` for synthetic measurements and `python -m unittest discover -s tests -v` for regressions. These scripts do not open audio devices or send audio anywhere. Total microphone latency also includes Windows and VB-CABLE buffers and the receiving application.
