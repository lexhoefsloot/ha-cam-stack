# Changelog

## 0.1.0

Initial release. Bundelt:

* nginx viewer-pagina (was: `/homeassistant/cam-viewer/`)
* Python audio-proxy met watchdog (was: `/homeassistant/audio-proxy/`)
* go2rtc met dfr1154 + dfr1154_audio streams (was: `/homeassistant/go2rtc/`)

Migreert losse `docker run` containers naar één HA add-on. Alle configs nu
via add-on options ipv hard-coded.
