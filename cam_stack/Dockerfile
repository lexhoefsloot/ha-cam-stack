ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:17.2.2
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ARG BUILD_ARCH=aarch64

# Runtime deps
RUN apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    ffmpeg \
    curl \
    ca-certificates \
    gettext \
 && pip3 install --break-system-packages --no-cache-dir aiohttp

# go2rtc binary — pick arch-correct release asset
RUN case "${BUILD_ARCH}" in \
        aarch64) GO2RTC_ARCH="arm64";; \
        amd64)   GO2RTC_ARCH="amd64";; \
        armv7)   GO2RTC_ARCH="arm";; \
        *)       echo "unsupported arch: ${BUILD_ARCH}" >&2; exit 1;; \
    esac \
 && curl -fsSL "https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_${GO2RTC_ARCH}" \
        -o /usr/local/bin/go2rtc \
 && chmod +x /usr/local/bin/go2rtc \
 && /usr/local/bin/go2rtc --version

# Copy rootfs (services + configs + scripts)
COPY rootfs /

# Make sure s6 service runners + cont-init scripts are executable
RUN chmod +x /etc/cont-init.d/*.sh /etc/services.d/*/run

LABEL \
    io.hass.name="Camera Stack (DFR1154)" \
    io.hass.description="nginx + audio-proxy + go2rtc" \
    io.hass.type="addon" \
    io.hass.arch="aarch64|amd64"
