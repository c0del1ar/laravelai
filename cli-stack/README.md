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

## YouTube Cookies

Beberapa video YouTube menolak request tanpa sesi login dan `yt-dlp` akan mengembalikan error seperti `Sign in to confirm you're not a bot`. Untuk kasus itu, export cookies browser dalam format Netscape, lalu simpan di:

```text
cli-stack/cookies/youtube.cookies.txt
```

File cookies tidak di-commit. Direktori `cookies` sengaja di-mount writable karena `yt-dlp --cookies` dapat memperbarui cookie jar saat proses selesai. Setelah file dibuat atau diperbarui:

```bash
docker compose up -d --build --force-recreate
```

Tool `ytmp3` akan menormalisasi cookie export yang memakai spasi menjadi format Netscape tab-separated sebelum dipakai oleh `yt-dlp`. Jika setelah rebuild masih muncul `Sign in to confirm you're not a bot`, cookies sudah tidak valid/stale dan perlu diexport ulang dari browser yang sedang login.

Cookie yang valid untuk login YouTube biasanya memuat nama seperti `LOGIN_INFO`, `SID`, `SAPISID`, `__Secure-1PSID`, atau `__Secure-3PSID`. Jika file hanya berisi cookie visitor seperti `PREF`, `YSC`, `VISITOR_INFO1_LIVE`, dan token rollout, itu belum cukup untuk melewati validasi login.

Default path di container:

```env
YTMP3_COOKIES_FILE=/app/cookies/youtube.cookies.txt
```

## Menambah Tool

Tambahkan executable di `tools/`, lalu daftarkan ke `config/tools.json` untuk konfigurasi custom. Jika `config/tools.json` belum ada, runner otomatis memakai `config/tools.example.json`.

### Menambah Tool Go

Untuk tool yang ditulis dengan Go, simpan source di subdirektori sendiri, lalu build menjadi binary di `cli-stack/bin/`.

Contoh struktur:

```text
cli-stack/
  bin/
    ytmp3
  tools/
    ytmp3/
      main.go
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
go build -o ../../bin/ytmp3 .
```

Daftarkan binary itu di `config/tools.json`. Mulai dari contoh bawaan:

```bash
cp config/tools.example.json config/tools.json
```

Lalu edit entry tool-nya:

```json
{
  "tools": {
    "ytmp3": {
      "name": "YouTube MP3 Downloader",
      "description": "Download audio dari URL.",
      "command": "bin/ytmp3",
      "args": ["{{url}}"],
      "required": ["url"],
      "patterns": {
        "url": "^https?://(www\\.)?(youtube\\.com|youtu\\.be|music\\.youtube\\.com)/.+$"
      },
      "timeout_seconds": 300,
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
