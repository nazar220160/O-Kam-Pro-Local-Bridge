# Frigate wizard RTSP probe adapter

Frigate's wizard can time out before its retry from UDP to TCP and default FFmpeg analysis complete. This optional derivative image changes only metadata probes and snapshot capture: RTSP uses TCP immediately, bounded analysis, and the existing subprocess timeout. Snapshot capture is limited to eight seconds. For bridge lens URLs, JPEG previews first use the authenticated cached ONVIF snapshot, avoiding a wait for another RTSP keyframe. Set `FRIGATE_OKAM_ONVIF_PORT` in Frigate if the bridge ONVIF listener uses a port other than 8899. Non-RTSP inputs and runtime recording/detection commands are preserved.

Build from the project root, selecting your existing Frigate image (including any existing custom fixes):

```sh
docker build -f integrations/frigate/Dockerfile \
  --build-arg FRIGATE_BASE_IMAGE=YOUR_EXISTING_FRIGATE_IMAGE \
  -t frigate:okam-probes .
```

Set the `frigate` service image in your Frigate Compose installation to `frigate:okam-probes`, then recreate that service. Back up its Compose configuration first; preserve its existing mounts, devices, environment and detection configuration. This is a separate optional change to Frigate, not required to start the bridge.

Verified against the installed Frigate 0.18.1 utility layout. The build rejects unsupported source layouts instead of guessing. Rebuild the adapter when updating the Frigate base image. This is a locally maintained compatibility patch, not an upstream Frigate release. To roll back, restore the prior service image and recreate Frigate.

A shorter probe does not fix unreachable cameras or packet loss. Check RTSP port conflicts, source availability and actual decoder errors independently. Live bridge audio requires the camera's supported G.711 A-law stream; microphone capability alone is not proof that audio packets are arriving.
