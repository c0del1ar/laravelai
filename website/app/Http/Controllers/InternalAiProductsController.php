<?php

namespace App\Http\Controllers;

use App\Services\AiProductManifestService;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class InternalAiProductsController extends Controller
{
    public function __construct(private AiProductManifestService $manifestService)
    {
    }

    public function index(Request $request)
    {
        if (! $this->isAuthorized($request)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $limit = (int) $request->query('limit', 100);

        return response()->json([
            'items' => $this->manifestService->listProducts($limit),
        ]);
    }

    public function show(Request $request, string $slug)
    {
        if (! $this->isAuthorized($request)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $item = $this->manifestService->getProductBySlug($slug);
        if (! $item) {
            return response()->json(['error' => 'Not found'], Response::HTTP_NOT_FOUND);
        }

        return response()->json($item);
    }

    private function isAuthorized(Request $request): bool
    {
        $providedKey = (string) $request->header('X-Search-Key', '');
        $expectedKey = (string) config('services.ai.internal_search_key', '');

        return $expectedKey !== '' && hash_equals($expectedKey, $providedKey);
    }
}
