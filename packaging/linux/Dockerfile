# Image de build (option --docker de build.sh) : Ubuntu 22.04 = glibc 2.35, donc
# l'executable compile tourne sur Debian 12+, Ubuntu 22.04+, Fedora 36+, RHEL 9+.
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl sudo build-essential patchelf dpkg-dev rpm xz-utils python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /usr/local/bin/
