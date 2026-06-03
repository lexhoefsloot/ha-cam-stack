#!/usr/bin/with-contenv bashio
# Render runtime configs from templates using add-on options.
set -euo pipefail

export CAM_IP="$(bashio::config 'cam_ip')"
export CAM_AUDIO_PORT="$(bashio::config 'cam_audio_port')"
export CAM_STREAM_PORT="$(bashio::config 'cam_stream_port')"
export CAM_CONTROL_PORT="$(bashio::config 'cam_control_port')"
export LOG_LEVEL="$(bashio::config 'log_level')"

bashio::log.info "Rendering configs for CAM_IP=${CAM_IP}"

mkdir -p /etc/nginx/http.d /var/www
envsubst '${CAM_IP} ${CAM_CONTROL_PORT}' \
    < /opt/nginx.conf.template \
    > /etc/nginx/nginx.conf

envsubst '${CAM_IP} ${CAM_STREAM_PORT} ${CAM_AUDIO_PORT} ${LOG_LEVEL}' \
    < /opt/go2rtc.yaml.template \
    > /etc/go2rtc.yaml

# Move static viewer into nginx docroot
install -m 0644 /opt/index.html /var/www/index.html

bashio::log.info "Templates rendered."
