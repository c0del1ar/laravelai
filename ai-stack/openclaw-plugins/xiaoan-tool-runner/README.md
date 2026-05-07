# Xiao-An Tool Runner Plugin

OpenClaw native plugin untuk command `/tool`. Plugin ini tidak menjalankan shell langsung di container OpenClaw. Ia hanya meneruskan request ke sidecar `cli-stack`:

```text
WhatsApp /tool -> OpenClaw plugin -> http://cli_tool_runner:37000/run
```

## Environment

Plugin memakai default statis agar lolos guard installer OpenClaw:

```text
prefix: /tool
runner: http://cli_tool_runner:37000
timeout: 240000 ms
```

Karena guard OpenClaw memblokir kombinasi env access + network request di plugin, plugin ini tidak membaca API key dari env dan tidak mengirim header auth. Jalankan `cli-stack` di Docker network internal yang sama, lalu kosongkan `CLI_TOOL_RUNNER_KEY` untuk endpoint internal ini.

Catatan package metadata: plugin ini memakai `openclaw.extensions`. Jangan tambahkan `openclaw.hooks`, karena itu untuk hook pack OpenClaw dan bisa membuat installer/enable memakai jalur loader yang salah untuk plugin runtime ini.

## Command

List tool:

```text
/tool
```

Tool dengan satu required arg seperti `url` atau `text`:

```text
/tool ytmp3 https://example.com/video
/tool echo hello
```

Tool dengan argumen bernama:

```text
/tool convert url=https://example.com/video format=mp3
/tool echo text="hello world"
```

## Install

Dari `ai-stack`:

```bash
bash ./setup_openclaw_tool_runner.sh
```
