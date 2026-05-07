FROM golang:1.22-alpine AS build

WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
RUN go build -trimpath -ldflags="-s -w" -o /out/tool-runner ./cmd/tool-runner

FROM alpine:3.20

RUN apk add --no-cache ca-certificates tini
WORKDIR /app
COPY --from=build /out/tool-runner /usr/local/bin/tool-runner
COPY config ./config
COPY tools ./tools
RUN chmod +x /app/tools/examples/echo.sh

ENV CLI_TOOL_RUNNER_ADDR=:37000
ENV CLI_TOOL_RUNNER_BASE_DIR=/app
ENV CLI_TOOL_RUNNER_CONFIG=/app/config/tools.example.json

EXPOSE 37000
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["tool-runner"]
