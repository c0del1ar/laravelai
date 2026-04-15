<?php

namespace App\Http\Controllers;

use App\Services\AiIndexBridgeService;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class InternalAiIndexController extends Controller
{
    public function __invoke(Request $request, AiIndexBridgeService $indexBridge)
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

        $result = $indexBridge->push($payload['paths'] ?? [], $payload['urls'] ?? []);
        return response()->json($result['body'] ?? ['ok' => false], (int) ($result['status'] ?? 500));
    }
}
