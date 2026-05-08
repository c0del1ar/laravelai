FROM golang:1.22-alpine AS build

ENV CGO_ENABLED=0
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY tools/ytmp3 ./tools/ytmp3
RUN go build -trimpath -ldflags="-s -w" -o /out/tool-runner ./cmd/tool-runner
RUN go build -trimpath -ldflags="-s -w" -o /out/ytmp3 ./tools/ytmp3

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg tini unzip \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir --upgrade yt-dlp \
    && curl -fsSL https://deno.land/install.sh -o /tmp/install_deno.sh \
    && DENO_INSTALL=/usr/local sh /tmp/install_deno.sh -y \
    && rm -f /tmp/install_deno.sh \
    && ln -sf /usr/bin/tini /sbin/tini \
    && deno --version \
    && yt-dlp --version
WORKDIR /app
COPY --from=build /out/tool-runner /usr/local/bin/tool-runner
COPY --from=build /out/ytmp3 /app/bin/ytmp3
COPY config ./config
COPY tools ./tools
RUN chmod +x /app/tools/examples/echo.sh /app/bin/ytmp3 && mkdir -p /app/data/ytmp3

ENV CLI_TOOL_RUNNER_ADDR=:37000
ENV CLI_TOOL_RUNNER_BASE_DIR=/app
ENV CLI_TOOL_RUNNER_CONFIG=/app/config/tools.example.json

EXPOSE 37000
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["tool-runner"]
