# ha-cam-stack

Home Assistant **custom add-on repository** voor de camper-stack.

## Inhoud

| Add-on | Slug | Wat het doet |
|---|---|---|
| [Camera Stack](./cam_stack/README.md) | `cam_stack` | nginx-viewer + Python audio-proxy + go2rtc voor de DFR1154 ESP32-S3 camera, in één container |

## Installeren in Home Assistant

1. Push deze repo naar GitHub (privé mag).
2. In Home Assistant → **Settings → Add-ons → ⋮ (rechtsboven) → Repositories**.
3. Plak de Git-URL `https://github.com/lexhoefsloot/ha-cam-stack` en klik **Add**.
4. De add-on(s) verschijnen onderaan de add-on store. Klik **Install** op *Camera Stack*.
5. Onder **Configuration** kies je `cam_ip`, gain, watchdog-thresholds, etc.
6. **Start** → check de logs.

## Bij eerste installatie: stop de oude losse containers

De stack draait nu nog als losse `docker run` containers (`audio-proxy`,
`cam-viewer`, `go2rtc`). Die binden poorten 8080/8090/1984 — de add-on kan
niet starten zolang die nog draaien. Eenmalig:

```bash
docker stop audio-proxy cam-viewer go2rtc
docker rm   audio-proxy cam-viewer go2rtc
```

Daarna is de add-on de enige beheerder. Logs / start / stop voortaan via de
HA UI.

## Disaster recovery

* Repo is op GitHub → kloon terug, voeg toe als custom repo, installeer.
* `cam_stack/config.yaml` bevat de HA add-on metadata, `Dockerfile` bouwt
  de container, `rootfs/` bevat alle runtime-configs en scripts.
