# Voice processing decisions

Clear Mic 1.9 defaults to full-band DPDFNet-2 with optional stereo WebRTC AEC. No matched Discord listening comparison or end-to-end Discord latency measurement has been completed.

## Streaming and preview stability (1.9.1)

The sound defaults, weights and DSP delay are retained while the user evaluates the new 48 kHz path. The iteration addresses concrete runtime defects: a rejected nonfinite frame previously advanced the dry delay ring and could poison subsequent audio; native live echo entry lacked the offline shape/contiguity/finite checks. Invalid capture buffers now fail before reference reads/native state changes. Valid live/offline echo frames remain identical.

FFT synthesis, finite checks and blend ramps reuse buffers. On 1000 full-band synthetic frames the optimized default 65% output matched 1.9 bit for bit. Zero-strength output is now bit-exact to the aligned original. This equivalence test establishes unchanged numerical output on its fixture, not a general perceptual rating. Short shared-host speed measurements are not evidence of a reliable performance gain.

Preview comparisons cache unchanged processing settings, retain captured source identity and reject a speaker reference from a different selected device. Starting another recording invalidates the old preview, including when the new recording fails. Earlier playback stops before preparing the next comparison. The saved Processed WAV continues to track current playback/settings; speaker-reference audio stays in RAM.

Live telemetry derives fixed DSP delay from the active processing components, including model/AEC, RNNoise where applicable, gate and limiter. Frame compute includes configuration, audio processing and statistics preparation. Calls exceeding their 10 ms budget are counted separately. Snapshots publish atomically. Preview flushing and trimming use the same actual component delays rather than a second hardcoded table. These values exclude Windows, driver and Discord buffers.

The paced benchmark now warms on one chronological second and measures the following ten seconds. Previously it replayed the warmup prefix into already advanced state. Upper-band echo regressions also cover synthetic 8.5–18 kHz near-end bursts over low-frequency speaker music; the older speech fixture alone could not detect losses there. Some upper-band AEC attenuation remains, so defaults have not been retuned without a listening result.

Final stability checks passed 109 source regressions and all interface checks, including compact-window layout. A 60-second real-callback soak used actual Fullband/AEC/shaping code with synthetic endpoints and prerecorded signals under six busy CPU processes: 6,000 measured callbacks, 11 control changes, reference gaps, p99 3.35 ms, max 3.91 ms, zero calls over 10 ms or completions past the next slot. Private memory changed -0.10 MiB during the measured run. Eight additional start/stop cycles completed cleanly; private memory changed 1.02 MiB across them. This does not prove a permanent absence of leaks.

The original normal-priority synthetic runner had zero compute overruns but 16 next-slot misses from scheduling/wakeup delay. Its baseline report is retained. The final harness scopes MMCSS Audio registration to its own callback runner and reverts it on exit, matching the task requested by the bundled shared-WASAPI [PortAudio v19.7.0 source](https://raw.githubusercontent.com/PortAudio/portaudio/v19.7.0/src/hostapi/wasapi/pa_win_wasapi.c). PortAudio attempts registration in the real callback but does not propagate boost failures; actual device-thread registration was not verified. No application-wide or real-time process priority change was made. Python's high-resolution sleep can still [overrun due to scheduling](https://docs.python.org/3.14/library/time.html#time.sleep).

`scripts/soak_audio.py report.json --seconds 60 --workers 6` reproduces the driver-free stability harness. It does not open microphone, speaker, virtual-driver or Discord endpoints. Neither this soak nor packaged interface/self-tests establish end-to-end Discord latency or subjective voice quality in the user's room.

## Full-band voice fidelity correction (1.9)

The user's real 48 kHz recording exposed a gap in the 1.8 evaluation: its speech fixture was originally 16 kHz, so it could not detect lost high-frequency detail. The saved 1.8 Processed preview lost roughly 81 dB in the 8–12 kHz band versus Original. Measured relative to 300–1000 Hz gain, this was about 86 dB. The user confirmed Original had clear voice with music bleed, while Processed was muffled. This is a processing defect; adding treble EQ cannot reconstruct the missing bandwidth.

The replacement uses the official [Ceva-IP DPDFNet](https://github.com/ceva-ip/DPDFNet) 48 kHz DPDFNet-2 ONNX model. Pinned weights, revision and SHA-256 are in `fullband.lock.json`; the streaming analysis/state initialization derives from the Apache-2.0 upstream package. DPDFNet-8 was also evaluated locally on the user's recording. It took substantially more CPU without preserving more upper voice-band energy, so model size was not used as a quality ranking. No microphone audio was uploaded.

Inference uses CPU ONNX Runtime with two intra-operation threads, sequential execution and idle spinning disabled. A causal 960-sample Vorbis-window STFT advances by 480 samples, retains recurrent state and reconstructs through overlap-add. The observed microphone-to-denoiser delay is 2400 samples (50 ms): model lookahead/synthesis 40 ms plus causal analysis framing 10 ms. A 2400-sample dry path aligns the original signal before the default 65% wet blend. Strength changes ramp over up to 20 ms. This blend retains some background noise in exchange for voice detail. It cannot guarantee perfect voice/music separation.

Stereo AEC runs first using the same physical playback reference as Classic and defaults to Natural voice mode. The full-band model receives the echo-reduced mic; it is a denoiser, not a two-input echo model. RNNoise is disabled for this path. The model delay plus AEC's measured 430 samples, limiter's 96 and optional gate's 240 is 61/66 ms of fixed DSP delay. Device, OS, driver and Discord buffering are additional. A faster inference call does not remove model lookahead.

Tests cover transparent zero-strength alignment through the last partial frame, real-model bandwidth above 8 kHz, exact weighted mixing, complete preview flush with AEC/gate/limiter, input validation and preview audio/settings persistence. `scripts/measure_fullband.py` measures the complete echo + full-band + default shaping chain in real-time-paced 10 ms calls, optionally with four busy CPU processes. It does not open a microphone. Saved user-preview comparisons lack the original playback reference (which was retained only in the old app's RAM), so those comparisons exercise denoising without AEC and cannot establish speaker-music suppression in the actual room. New in-app previews retain that reference for the full comparison.

On this Ryzen 5 7600X, the final paced full chain with four busy CPU processes and the gate enabled took p99 3.48 ms and maximum 5.15 ms per 10 ms call. No processing or next-slot scheduling deadlines were missed in the ten-second run; average CPU consumption was 0.35 core equivalents. The normal run peaked at 3.44 ms. The portable build passed its own frozen full-band self-test and interface/persistence checks. These short controlled tests do not guarantee every gaming or driver workload.

The sections below document earlier versions; their 16 kHz models and historical performance numbers do not describe the 1.9 default.

## Neural quality and Discord latency (1.8)

Two candidates from the [LocalVQE project](https://github.com/localai-org/LocalVQE) are bundled: v1.3 joint echo/noise/reverb enhancement and v1.4-AEC echo-only. Source and GGML revisions plus model SHA-256 values are pinned in `neural.lock.json`. The native CPU build was verified on Windows/MSVC with AVX2. No model is trained, downloaded or inferred in the cloud at runtime. Existing profiles keep Classic until the user explicitly selects a neural engine.

The app's stream remains 48 kHz, 480-sample blocks. A native adapter downsamples microphone and mixed playback reference to 16 kHz with 193-tap Blackman-windowed low-pass filters, gathers 256-sample model hops, and reconstructs 48 kHz output through the same filter. It preallocates all rings and resampler buffers. Fixed delay is 1728 samples / 36 ms: 16 ms synthesis + 16 ms hop adaptation + two 2 ms FIR delays. The peak limiter and optional gate add their own 2/5 ms. Classic NR/AEC are bypassed in neural modes; downstream shaping is retained. Preview compensation removes the fixed delay without truncating the original recording length.

Initial two-thread measurements on the Ryzen 5 7600X showed the larger model taking about 4.3 ms per native 16 ms hop, while echo-only took about 1.2 ms. The echo-only model preserved more voice in the music test despite having fewer parameters; model size was not treated as a quality score. In the complete resampled pipeline, music-plus-voice SI-SDR was approximately 10 dB for joint cleanup and 15 dB for echo-only, compared with 6.64 dB for Classic Natural voice AEC. These compare identical pinned speech with deterministic simulated speaker paths; they are not a real-room listening result. The joint model also suppressed quiet-only keyboard/background noise; echo-only intentionally retains it.

The runtime uses up to four threads for joint cleanup and two for echo-only. `scripts/measure_neural.py report.json --samples comparison --stress` measures the actual adapter + shaping calls, reports p95/p99/max, and tests joint cleanup while four temporary CPU-heavy processes run. The report explicitly excludes Windows stream, virtual-driver, Discord and network delay. Staying inside a 10 ms processing deadline does not establish a particular end-to-end Discord latency or guarantee performance during every game.

The paced test initially exposed occasional 30+ ms outliers hidden by throughput-style benchmarking. Clear Mic now supplies persistent inference worker pools with idle polling disabled and above-normal worker priority. An existing higher PortAudio/MMCSS priority is preserved; the context's owning thread priority is restored on close. The four-thread joint model's final real-time-paced test with four CPU-heavy processes measured p99 4.16 ms, maximum 4.51 ms, zero callbacks over 10 ms and zero completions past the next callback slot. It consumed about 0.72 CPU-core equivalents over ten seconds of audio. The two-thread comparison still had one 10.14 ms call, so the measured four-thread setup is used for joint cleanup on this PC. These observations are a controlled scheduling test, not a guarantee against every driver/DPC or gaming workload.

Both models have 16 kHz bandwidth and a mono reference. The classic stereo/full-band path remains useful for singing, high-frequency detail, or playback with stereo content that cancels in a mono mix. Neural processing remains an option to compare on the same preview; a quiet output alone is not evidence of better voice quality.

## Quiet-noise threshold (1.7)

The new gate measures sample peaks after the noise-removal stage, before AGC/EQ/compression/output gain. A fixed 240-sample delay lets a 48-sample opening ramp finish before a detected onset reaches the output. The default opening threshold is −45 dBFS, with 6 dB hysteresis, 150 ms hold and a linear 120 ms release to exact silence. It is off by default in all presets and does not change the samples or timeline while bypassed. Preview alignment and the native latency query include its 240-sample delay when enabled. The native ABI is checked before configuration to reject mismatched old binaries safely.

Tests cover subthreshold impulsive clicks, above-threshold onset preservation, hold/release timing, hysteresis, output-gain independence, threshold changes, bypass, preview length/alignment, bounds and old-settings defaults. The gate does not distinguish speech from a keyboard click of the same level. Clicks that exceed the opening threshold or overlap speech can pass; thresholding also risks attenuating very quiet speech and singing. The live Gate input readout uses the detector's pre-AGC peak level so users can tune against their own microphone, rather than assuming one threshold works in every room.

## Voice fidelity during speaker playback (1.6)

Real speech over a simulated musical playback reference exposed a failure that the earlier harmonic-tone double-talk test missed: the default residual suppressor could remove much of the near-end voice. The new Natural voice mode keeps the adaptive linear echo filter and raises residual suppression's echo-to-near-end masking thresholds, particularly in the high bands. Near-end detection responds sooner and stays engaged longer; suppression recovers from deep attenuation faster. Both mono and stereo render configurations receive this tuning. Strong isolation retains the upstream default settings used by 1.5.

`scripts/measure_echo_quality.py` uses the checksum-pinned upstream `near.wav` and `far.wav`, deterministic musical chords, a 50 ms speaker path and two delayed reflections. Speech begins after four seconds of convergence. Scores discard the first six seconds and account for the measured 430-sample AEC delay. The comparison uses the complete output against the clean voice target; it does not subtract an independent echo-only output to hide residual noise. Levels, input signals and alignment are identical across modes.

| Simulated music + real speech | Strong isolation (1.5) | Natural voice (1.6) |
|---|---:|---:|
| Nominal voice: projected voice gain | −9.69 dB | −1.73 dB |
| Nominal voice: scale-invariant signal-to-distortion ratio | −2.17 dB | 6.64 dB |
| Quiet voice: projected voice gain | −18.13 dB | −2.51 dB |
| Quiet voice: scale-invariant signal-to-distortion ratio | −7.29 dB | 4.49 dB |
| Echo-only attenuation after convergence | 62.62 dB | 59.51 dB |

These scores show improvement in controlled regressions, not a perceptual quality rating or a measurement in the user's room. A gentler residual suppressor can retain more speaker bleed, especially with nonlinear distortion, poor reference alignment or loud playback. Noise removal/AGC/compression are separate stages; changing this echo mode does not change their settings. Existing user tuning is preserved. The quiet-speaker path stays sample-exact and uses the same fixed delay in both modes. New tests cover real speech during music, quiet voice, competing speech, echo reduction and persisted mode selection.

Run `python scripts/measure_echo_quality.py report.json --samples comparison` to generate same-gain, same-timeline Target / Strong / Natural WAV files for a listening comparison. The speech fixture is supplied with the pinned WebRTC extraction; no microphone audio is captured or uploaded.

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

Before claiming a win against Discord: use the same input clips, match perceived output loudness, and compare voice detail, consonant/onset preservation, background noise and double-talk independently. Include changing speaker volume, long silence, keyboard transients and gaming load. Classic uses RNNoise; a quiet output by itself does not establish better voice quality.

## Reproducibility

The standalone WebRTC extractions are checksum-pinned in `webrtc.lock.json`. Their small compatibility shims and Microsoft compiler fixes are documented in source/build scripts. The algorithm implementations come from WebRTC; the extraction repositories are community maintained, not official WebRTC binary distributions. No field trials are enabled. Supplemental upstream and bundled FFT/JsonCpp notices are retained in `THIRD_PARTY`.

Run `python scripts/measure_voice.py report.json` for synthetic measurements and `python -m unittest discover -s tests -v` for regressions. These scripts do not open audio devices or send audio anywhere. Total microphone latency also includes Windows and VB-CABLE buffers and the receiving application.
