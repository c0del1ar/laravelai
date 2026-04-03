# Website Laravel + internal AI bridge

Pola yang dipakai:

- Browser -> Laravel `/api/ai/chat`
- Laravel -> FastAPI internal (`http://ai_fastapi:8008`)
- OpenClaw (WA/Telegram/Discord) -> FastAPI internal (`http://ai_fastapi:8008/v1/openclaw`)
- FastAPI -> Laravel internal search (`http://laravel_franken:8000/api/internal/ai/search`)
- FastAPI -> Groq API (LLM response)

## Langkah cepat

1. Buat shared bridge sekali di host:
   ```bash
   docker network create ai_bridge_local
   ```

2. Di project Laravel:
   - pakai `website/docker-compose.with-ai-bridge.yml`
   - tambahkan isi `website/.env.ai.example` ke `.env`
   - copy file controller/service/config/route snippet ke project Laravel

3. Di project AI terpisah:
   - copy folder `ai-stack/`
   - `cp .env.example .env`
   - pastikan `AI_SHARED_NETWORK` sama dengan `AI_SHARED_NETWORK` di project Laravel
   - pastikan `SEARCH_API_URL=http://laravel_franken:8000/api/internal/ai/search`
   - samakan `SEARCH_API_KEY` dengan `AI_INTERNAL_SEARCH_KEY` di Laravel
   - set `OPENCLAW_WEBHOOK_KEY` (opsional tapi disarankan, untuk header `X-OpenClaw-Key`)
   - jika mau jalankan OpenClaw container di stack ini, set `OPENCLAW_IMAGE` sesuai image OpenClaw yang kamu pakai
   - `docker compose up -d --build`

4. Jalankan website compose.
5. (Opsional) Jalankan OpenClaw terpisah: `docker compose --profile openclaw up -d`

## Catatan

- FastAPI **tidak dipublish** ke host. Ia hanya `expose: 8008` di Docker network.
- LLM dipanggil dari FastAPI ke Groq API, jadi `GROQ_API_KEY` wajib diisi di `ai-stack/.env`.
- Browser user hanya bicara ke route Laravel, jadi tidak perlu CORS untuk AI stack.
- `config/ai_catalog.php` perlu kamu sesuaikan dengan model Laravel yang benar.

## Browser / frontend

Frontend cukup panggil:

```js
fetch('/api/ai/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, history })
})
```

## OpenClaw ke AI core (tanpa Laravel)

Endpoint AI untuk OpenClaw:

```http
POST /v1/openclaw
X-OpenClaw-Key: <OPENCLAW_WEBHOOK_KEY>
Content-Type: application/json
```

Endpoint ini ada di container FastAPI (`ai_fastapi:8008`), jadi alurnya langsung:
`OpenClaw -> ai_fastapi (/v1/openclaw) -> Groq + search website`.

Payload minimum:

```json
{
  "message": "Halo, ada promo apa?"
}
```

Field lain yang juga didukung untuk kompatibilitas:

- pesan: `text`, `content`, `data.message`, `data.text`, `event.message.text`
- user id: `user_id`, `sender_id`, `from`, `user.id`, `sender.id`, `data.user_id`, `data.sender_id`
- riwayat: `history` atau `messages` (`[{role: user|assistant, content|text: "..."}]`)

Response sukses akan mengirim `reply`, `text`, `message`, dan `response` (isi sama) + payload `ai` mentah.

## Penting

Pack ini dibuat untuk jadi baseline produksi kecil. Mapping model Laravel (`Tool`, `Product`, `Post`, `Page`) kemungkinan perlu kamu sesuaikan dengan project aslimu.
