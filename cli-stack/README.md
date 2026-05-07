# CLI Stack Tool Runner

Sidecar HTTP service untuk command bot seperti `/tool ytmp3 <url>`, `/tool tiktok <url>`, atau tool media lain yang dipakai OpenClaw. Service ini sengaja dipisah dari `ai-stack` dan Laravel.

## Rekomendasi Arsitektur

Gunakan Go untuk API runner dan command orchestration. Untuk pekerjaan berat seperti download/transcode, Go tetap memanggil binary yang memang kuat di domain itu, misalnya `yt-dlp`, `ffmpeg`, atau executable custom. Bottleneck downloader biasanya network dan encode media, bukan bahasa API wrapper.

Flow:

```text
WhatsApp -> OpenClaw plugin /tool -> http://cli_tool_runner:37000/run -> allowlisted command -> reply
```

## Setup

```bash
cd cli-stack
cp .env.example .env
cp config/tools.example.json config/tools.json
docker compose up -d --build
```

Service memakai network Docker yang sama dengan `ai-stack`:

```env
AI_SHARED_NETWORK=ai_bridge_local
```

Dari plugin OpenClaw, panggil internal URL:

```http
POST http://cli_tool_runner:37000/run
Content-Type: application/json
```

Payload:

```json
{
  "tool": "echo",
  "args": {
    "text": "hello"
  },
  "request_id": "wa-message-id"
}
```

Response:

```json
{
  "ok": true,
  "tool": "echo",
  "duration_ms": 4,
  "exit_code": 0,
  "message": "hello",
  "stdout": "hello"
}
```

## Local Test

```bash
go run ./cmd/tool-runner
```

Di terminal lain:

```bash
curl -sS http://localhost:37000/health
curl -sS -H "Content-Type: application/json" \
  -d '{"tool":"echo","args":{"text":"hello"}}' \
  http://localhost:37000/run
```

Untuk integrasi OpenClaw internal, biarkan `CLI_TOOL_RUNNER_KEY` kosong karena plugin `/tool` tidak mengirim header auth. Batasi akses lewat Docker network internal. Jika service dipublish ke host/public network, pasang auth di layer reverse proxy atau firewall.

## Menambah Tool

Tambahkan executable di `tools/`, lalu daftarkan ke `config/tools.json`.

### Menambah Tool Go

Untuk tool yang ditulis dengan Go, simpan source di subdirektori sendiri, lalu build menjadi binary di `cli-stack/tools/`.

Contoh struktur:

```text
cli-stack/
  tools/
    ytmp3/
      go.mod
      main.go
    ytmp3
```

Contoh `cli-stack/tools/ytmp3/main.go`:

```go
package main

import (
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "missing url")
		os.Exit(1)
	}

	url := os.Args[1]
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{
		"message": "Tool ytmp3 menerima URL",
		"data": map[string]any{
			"url": url,
		},
	})
}
```

Build binary:

```bash
cd cli-stack/tools/ytmp3
go build -o ../ytmp3 .
```

Daftarkan binary itu di `config/tools.json`:

```json
{
  "tools": {
    "ytmp3": {
      "name": "YouTube MP3 Downloader",
      "description": "Download audio dari URL.",
      "command": "tools/ytmp3",
      "args": ["{{url}}"],
      "required": ["url"],
      "patterns": {
        "url": "^https?://.+$"
      },
      "timeout_seconds": 180,
      "max_output_bytes": 65536,
      "output_json": true
    }
  }
}
```

Setelah config berubah, restart container:

```bash
docker compose restart cli_tool_runner
```

Test langsung:

```bash
curl -sS -H "Content-Type: application/json" \
  -d '{"tool":"ytmp3","args":{"url":"https://example.com/watch?v=test"}}' \
  http://localhost:37000/run
```

Contoh:

```json
{
  "tools": {
    "ytmp3": {
      "name": "YouTube MP3 Downloader",
      "description": "Download audio dari URL yang valid.",
      "command": "tools/ytmp3",
      "args": ["{{url}}"],
      "required": ["url"],
      "patterns": {
        "url": "^https?://.+$"
      },
      "timeout_seconds": 180,
      "max_output_bytes": 65536,
      "output_json": true
    }
  }
}
```

Untuk `output_json: true`, executable harus print JSON:

```json
{
  "message": "Done",
  "files": [
    {
      "path": "/app/data/result.mp3",
      "name": "result.mp3",
      "mime": "audio/mpeg",
      "caption": "Audio selesai diproses"
    }
  ],
  "data": {}
}
```

## Guardrail

Runner ini hanya menjalankan tool yang ada di `config/tools.json`, tidak memakai shell interpolation, argumen divalidasi dengan regex, punya timeout, dan output dibatasi. Untuk downloader publik, tetap tambahkan rate limit di plugin OpenClaw atau reverse proxy, batas ukuran file, serta aturan konten yang boleh diproses.
