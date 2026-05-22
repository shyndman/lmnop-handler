FROM ghcr.io/linuxserver/baseimage-kasmvnc:ubuntunoble

LABEL maintainer="scotty.hyndman@gmail.com" \
      org.opencontainers.image.authors="Scott Hyndman" \
      org.opencontainers.image.title="lmnop-handler" \
      org.opencontainers.image.description="Obsidian-backed FastMCP server with browser-accessible Obsidian"

ARG OBSIDIAN_VERSION=1.12.7
ARG TARGETARCH
ARG OBSIDIAN_ARCH_SUFFIX=${TARGETARCH#amd64}

ENV CUSTOM_PORT="8080" \
    CUSTOM_HTTPS_PORT="8443" \
    CUSTOM_USER="" \
    SUBFOLDER="" \
    TITLE="Obsidian v${OBSIDIAN_VERSION}" \
    FM_HOME="/vaults" \
    OBSIDIAN_AUTOSTART="false" \
    PYTHONUNBUFFERED="1" \
    UV_LINK_MODE="copy" \
    UV_PYTHON_INSTALL_DIR="/opt/uv/python"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN echo "**** install packages ****" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        dbus-x11 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libfuse2 \
        libgtk-3-0 \
        libnss3 \
        uuid-runtime \
        zlib1g-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/*

RUN echo "**** download obsidian ****" && \
    curl -L -o /tmp/obsidian.AppImage \
        "https://github.com/obsidianmd/obsidian-releases/releases/download/v${OBSIDIAN_VERSION}/Obsidian-${OBSIDIAN_VERSION}${OBSIDIAN_ARCH_SUFFIX:+-arm64}.AppImage" && \
    chmod +x /tmp/obsidian.AppImage && \
    /tmp/obsidian.AppImage --appimage-extract && \
    chmod -R a+rX /squashfs-root && \
    rm /tmp/obsidian.AppImage

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv python install 3.14

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --python 3.14

COPY . /app
COPY docker/root/ /

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --python 3.14 && \
    chmod +x \
        /defaults/autostart \
        /etc/cont-init.d/60-lmnop-config \
        /etc/cont-init.d/61-openboxcopy \
        /etc/services.d/lmnop-handler/run \
        /usr/local/bin/obsidian

EXPOSE 8000 8080 8443
VOLUME ["/config", "/vaults"]

HEALTHCHECK CMD /bin/sh -c 'if [ -z "$CUSTOM_USER" ] || [ -z "$PASSWORD" ]; then curl --fail http://localhost:"$CUSTOM_PORT"/ || exit 1; else curl --fail --user "$CUSTOM_USER:$PASSWORD" http://localhost:"$CUSTOM_PORT"/ || exit 1; fi'
