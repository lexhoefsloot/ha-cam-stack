# Changelog

## 0.1.3

* Continuous recorder: the camera video (MJPEG stream copy from the local go2rtc
  restream, no transcoding) is written in 5-minute `.mkv` segments to
  `/share/camrec/`, kept for `record_hours` (default 24 h, ~45 GB). Oldest
  segments are also dropped when `/share` falls below `record_min_free_gb`.

## 0.1.1

* Fix memory/process leak in the audio-proxy: every ffmpeg restart (e.g. while
  the camera was offline) orphaned the decoder ffmpeg and its PCM reader task,
  leaking processes + asyncio transports until the add-on used gigabytes.
  Restarts now fully tear down the pipeline (cancel tasks, EOF + kill + **reap**
  both ffmpegs) before respawning, and the backoff resets after a healthy run.

## 0.1.0

Initial release. Bundelt:

* nginx viewer-pagina (was: `/homeassistant/cam-viewer/`)
* Python audio-proxy met watchdog (was: `/homeassistant/audio-proxy/`)
* go2rtc met dfr1154 + dfr1154_audio streams (was: `/homeassistant/go2rtc/`)

Migreert losse `docker run` containers naar één HA add-on. Alle configs nu
via add-on options ipv hard-coded.
