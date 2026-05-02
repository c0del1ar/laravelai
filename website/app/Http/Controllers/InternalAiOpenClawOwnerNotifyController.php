<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Mail;
use Symfony\Component\HttpFoundation\Response;

class InternalAiOpenClawOwnerNotifyController extends Controller
{
    public function __invoke(Request $request)
    {
        $providedKey = (string) $request->header('X-Search-Key', '');
        $expectedKey = (string) config('services.ai.internal_search_key', '');
        if ($expectedKey === '' || ! hash_equals($expectedKey, $providedKey)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $payload = $request->validate([
            'channel' => ['required', 'string', 'max:100'],
            'sender_id' => ['required', 'string', 'max:255'],
            'sender_name' => ['nullable', 'string', 'max:255'],
            'conversation_id' => ['nullable', 'string', 'max:255'],
            'message_preview' => ['nullable', 'string', 'max:2000'],
            'received_at' => ['required', 'string', 'max:80'],
            'cooldown_seconds' => ['required', 'integer', 'min:1', 'max:604800'],
            'reminder_sent' => ['required', 'boolean'],
        ]);

        $recipient = trim((string) config('services.ai.owner_notify_email', ''));
        if ($recipient === '') {
            Log::warning('OpenClaw owner notify skipped: AI_OWNER_NOTIFY_EMAIL is empty');
            return response()->json([
                'ok' => true,
                'delivered' => false,
                'reason' => 'owner email not configured',
            ], Response::HTTP_ACCEPTED);
        }

        $subject = sprintf('[OpenClaw] New DM from %s', (string) $payload['sender_id']);
        $lines = [
            'OpenClaw native DM gate received a new non-prefix message outside cooldown.',
            '',
            'channel: '.$payload['channel'],
            'sender_id: '.$payload['sender_id'],
            'sender_name: '.((string) ($payload['sender_name'] ?? '')),
            'conversation_id: '.((string) ($payload['conversation_id'] ?? '')),
            'received_at: '.$payload['received_at'],
            'cooldown_seconds: '.((string) $payload['cooldown_seconds']),
            'reminder_sent: '.((bool) $payload['reminder_sent'] ? 'true' : 'false'),
            '',
            'message_preview:',
            (string) ($payload['message_preview'] ?? ''),
        ];
        $body = implode("\n", $lines);

        try {
            Mail::raw($body, static function ($message) use ($recipient, $subject): void {
                $message->to($recipient)->subject($subject);
            });
        } catch (\Throwable $error) {
            Log::warning('OpenClaw owner notify mail failed', [
                'error' => $error->getMessage(),
            ]);

            return response()->json([
                'ok' => true,
                'delivered' => false,
                'reason' => 'mail send failed',
            ], Response::HTTP_ACCEPTED);
        }

        return response()->json([
            'ok' => true,
            'delivered' => true,
        ]);
    }
}
