<?php

namespace App\Http\Controllers;

use App\Services\AiWebsiteSearchService;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class InternalAiSearchController extends Controller
{
    public function __invoke(Request $request, AiWebsiteSearchService $searchService)
    {
        $providedKey = (string) $request->header('X-Search-Key', '');
        $expectedKey = (string) config('services.ai.internal_search_key', '');

        if ($expectedKey === '' || ! hash_equals($expectedKey, $providedKey)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $query = trim((string) $request->query('q', ''));
        if ($query === '') {
            return response()->json(['query' => $query, 'items' => []]);
        }

        return response()->json([
            'query' => $query,
            'items' => $searchService->search($query),
        ]);
    }
}
