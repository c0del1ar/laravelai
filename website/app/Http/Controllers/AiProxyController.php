<?php

namespace App\Http\Controllers;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Symfony\Component\HttpFoundation\Response;

class AiProxyController extends Controller
{
    public function __invoke(Request $request)
    {
        $payload = $request->validate([
            'message' => ['required', 'string', 'max:4000'],
            'history' => ['sometimes', 'array'],
            'history.*.role' => ['required_with:history', 'in:user,assistant'],
            'history.*.content' => ['required_with:history', 'string', 'max:4000'],
            'user_id' => ['nullable', 'string', 'max:128'],
        ]);

        $baseUrl = rtrim((string) config('services.ai.base_url'), '/');
        $timeout = (int) config('services.ai.timeout', 90);

        try {
            $response = Http::timeout($timeout)
                ->acceptJson()
                ->post($baseUrl . '/v1/chat', $payload);

            return response()->json(
                $response->json() ?? ['error' => 'AI service returned empty body'],
                $response->status()
            );
        } catch (ConnectionException $e) {
            Log::error('AI proxy connection failed', ['message' => $e->getMessage()]);

            return response()->json([
                'error' => 'AI service unavailable',
                'detail' => 'Laravel tidak bisa terhubung ke AI API internal.',
            ], Response::HTTP_BAD_GATEWAY);
        }
    }
}
