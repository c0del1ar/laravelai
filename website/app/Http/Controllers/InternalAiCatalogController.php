<?php

namespace App\Http\Controllers;

use App\Services\AiStructuredCatalogService;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class InternalAiCatalogController extends Controller
{
    public function __invoke(Request $request, AiStructuredCatalogService $catalogService)
    {
        $providedKey = (string) $request->header('X-Search-Key', '');
        $expectedKey = (string) config('services.ai.internal_search_key', '');
        if ($expectedKey === '' || ! hash_equals($expectedKey, $providedKey)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $limit = (int) $request->query('limit', 200);
        $query = trim((string) $request->query('q', ''));

        return response()->json([
            'query' => $query,
            'items' => $catalogService->listCatalog($limit, $query),
        ]);
    }
}
