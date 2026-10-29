# Jetson DCVC demo design

See ../../requirements.md for confirmed user requirements. The user confirmed all questions and requested continuous implementation without further routine approvals.

## Approach

Python and Gradio control a background worker; camera capture keeps a bounded latest-frame queue. The encoder batches eight frames for upstream HT-S and sends actual compressed bytes, not reconstructed images. TCP with length-prefixed, validated metadata is the initial reliable wired transport. The receiver loads its own models and decodes independently. UI preview transport is separate from the compressed network stream.

A single giant UI callback would make pause, cleanup, and diagnosis fragile. A microservice framework would add unnecessary deployment work. A few Python modules and two entry points are the chosen implementation approach (engineering decision).

Start in local round-trip mode using a synthetic moving pattern or camera. Synthetic input is clearly labelled; no synthetic throughput or substitute codec may be presented as DCVC performance. Missing extensions/weights must disable codec start with an actionable error. A separate capture-only check may work without weights.

## Environment and compatibility

Miniforge uses Python 3.10 and a Jetson-compatible NVIDIA wheel matching CUDA 12.6, initially matching the working system Torch. Upstream metadata requires >=3.12; validate import/compile compatibility before patching this declaration locally. Any upstream patch is stored and explained. Never replace system Torch or CUDA. Do not change network or power settings automatically.

## State and metrics

Idle -> starting -> running -> paused -> starting -> running; stop releases resources; errors are visible and retryable. Pause drops pending unencoded input; resume creates fresh codec state. Configuration changes restart the stream. Configuration is validated before GPU or camera allocation. Worker errors release resources. Stop during startup must not create a late live stream.

Count capture, encoded, decoded, and browser-rendered frames separately. Use wall-clock monotonic throughput windows including idle stalls; report bitrate over actual elapsed time. Display CPU codec timing and total pipeline timing separately. Cross-host one-way latency requires synchronized clocks or explicit uncertainty; local round-trip uses one clock. Do not label host completion latency as browser display latency.

## Delivery and validation

Launch script opens the local browser; UI has Chinese labels, start/pause/resume/end/quit, refresh devices, settings and report export. First milestone is a runnable UI plus actual codec build/benchmark evidence. Two-machine and USB acceptance remain pending until hardware is available. 640x360 at 30fps and <=500ms are targets, not established results. Minimize abstractions; extend through clear modules only.
