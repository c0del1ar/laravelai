<?php

namespace App\Http\Controllers;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Symfony\Component\HttpFoundation\Response;

class InternalAiIndexController extends Controller
{
    public function __invoke(Request $request)
    {
        $providedKey = (string) $request->header('X-Search-Key', '');
        $expectedKey = (string) config('services.ai.internal_search_key', '');
        if ($expectedKey === '' || ! hash_equals($expectedKey, $providedKey)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $payload = $request->validate([
            'paths' => ['sometimes', 'array'],
            'paths.*' => ['string', 'max:255'],
            'urls' => ['sometimes', 'array'],
            'urls.*' => ['string', 'max:2000'],
        ]);

        $baseUrl = rtrim((string) config('services.ai.base_url', ''), '/');
        $endpoint = (string) config('services.ai.index_endpoint', '/admin/index/changed');
        $timeout = (int) config('services.ai.timeout', 20);
        $indexKey = (string) config('services.ai.internal_index_key', '');

        if ($baseUrl === '') {
            return response()->json(['error' => 'AI base URL not configured'], Response::HTTP_BAD_REQUEST);
        }

        try {
            $response = Http::timeout($timeout)
                ->acceptJson()
                ->withHeaders([
                    'X-Index-Key' => $indexKey,
                ])
                ->post($baseUrl . $endpoint, $payload);

            return response()->json($response->json() ?? ['ok' => false], $response->status());
        } catch (ConnectionException $e) {
            return response()->json([
                'error' => 'AI index service unavailable',
                'detail' => $e->getMessage(),
            ], Response::HTTP_BAD_GATEWAY);
        }
    }
}
