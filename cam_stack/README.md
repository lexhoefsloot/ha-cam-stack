# Camera Stack (DFR1154)

Bundelt drie processen voor de DFR1154 ESP32-S3 camera in één HA add-on:

* **nginx** — serveert de viewer-pagina op `:8080` en proxiet `/cam/*`,
  `/api/audio.aac`, `/api/levels.json`, `/api/stream.mjpeg`.
* **Python audio-proxy** (`proxy.py`) — pulled `/audio.wav` van de cam, encodet
  AAC voor `<audio>`-clients, en computeert RMS+peak in een 5-min ring-buffer
  voor de level-grafiek. Watchdog: als de PCM-feed >15s stilvalt → kill ffmpeg
  → runner-loop herstart.
* **go2rtc** — geeft WebRTC + HLS + MJPEG-proxy op `:1984` (`dfr1154` =
  video, `dfr1154_audio` = audio).

## Configuratie

Alles is via de Configuration-tab te zetten:

| Optie | Default | Wat |
|---|---|---|
| `cam_ip` | `192.168.2.104` | IP van de DFR1154 |
| `cam_audio_port` | `82` | Cam audio.wav httpd port |
| `cam_stream_port` | `81` | Cam MJPEG-stream httpd port |
| `cam_control_port` | `80` | Cam control httpd port (`/light`, `/jpg`, `/ir`) |
| `audio_gain_db` | `12` | ffmpeg `volume=NdB` op de AAC-encode |
| `watchdog_stall_s` | `15` | Hoeveel sec zonder levels → restart ffmpeg |
| `watchdog_startup_grace_s` | `30` | Grace-period na ffmpeg-spawn |
| `log_level` | `info` | s6/bashio log-verbosity |

## Poorten

| Poort | Wat |
|---|---|
| 8080 | viewer-pagina + audio AAC + levels JSON |
| 1984 | go2rtc API + WebRTC signalling |
| 8554 | RTSP (optioneel) |
| 8555 | WebRTC TCP-fallback |

## Migratie vanaf losse containers

De stack draait nu nog als drie aparte `docker run` containers
(`audio-proxy`, `cam-viewer`, `go2rtc`). Voordat je deze add-on start:

```bash
docker stop audio-proxy cam-viewer go2rtc
docker rm   audio-proxy cam-viewer go2rtc
```

De configs in `/homeassistant/audio-proxy/`, `/homeassistant/cam-viewer/`,
`/homeassistant/go2rtc/` mag je houden als referentie of weggooien — de
add-on heeft eigen kopieën onder `rootfs/opt/`.

## Snelle smoke-test

```bash
# Vanuit een SSH addon-shell of LAN:
curl -s http://homeassistant.local:8080/api/levels.json | head -c 200
curl -s -m 4 http://homeassistant.local:8080/api/audio.aac > /tmp/test.aac
ffprobe /tmp/test.aac     # moet AAC ADTS, 16 kHz mono melden
```
