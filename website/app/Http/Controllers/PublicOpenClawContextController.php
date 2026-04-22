<?php

namespace App\Http\Controllers;

use App\Services\AiStructuredCatalogService;
use App\Services\AiToolManifestService;
use App\Services\AiWebsiteSearchService;
use App\Services\AiProductManifestService;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class PublicOpenClawContextController extends Controller
{
    public function __invoke(
        Request $request,
        AiWebsiteSearchService $searchService,
        AiStructuredCatalogService $catalogService,
        AiToolManifestService $toolService,
        AiProductManifestService $productService
    ) {
        if (! $this->isAuthorized($request)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $query = trim((string) $request->query('q', ''));
        $limit = max(1, min((int) $request->query('limit', 8), 20));

        $searchItems = [];
        if ($query !== '') {
            $searchItems = array_slice($searchService->search($query), 0, $limit);
        }

        $catalogItems = array_slice($catalogService->listCatalog($limit * 3, $query), 0, $limit);
        $productItems = array_slice($productService->listProducts($limit), 0, $limit);
        $toolItems = array_slice($toolService->listTools($limit), 0, $limit);
        $assistant = $this->assistantProfile();

        return response()->json([
            'query' => $query,
            'generated_at' => now()->toAtomString(),
            'assistant_profile' => $assistant,
            'site_context' => [
                'search' => $searchItems,
                'catalog' => $catalogItems,
                'products' => $productItems,
                'tools' => $toolItems,
            ],
            'response_policy' => [
                'identity' => [
                    'id' => 'Jika user tanya "siapa kamu?", jawab identitas dari assistant_profile.identity_answer.id. Jangan bilang unfinished/not configured.',
                    'en' => 'If user asks "who are you?", answer using assistant_profile.identity_answer.en. Never claim unfinished/not configured.',
                ],
                'job' => [
                    'id' => 'Peran utama: customer service website. Fokus bantu navigasi halaman, tools, pricing, produk, artikel, dan kontak.',
                    'en' => 'Primary role: website customer service. Focus on pages, tools, pricing, products, articles, and contact guidance.',
                ],
                'style' => [
                    'id' => 'Gunakan gaya bicara sesuai assistant_profile.style.',
                    'en' => 'Use speaking style from assistant_profile.style.',
                ],
            ],
            'usage_hint' => [
                'id' => 'Gunakan data ini sebagai grounding jawaban CS website. Hindari asumsi di luar data.',
                'en' => 'Use this data for website customer-service grounding. Avoid assumptions outside this data.',
            ],
        ]);
    }

    private function isAuthorized(Request $request): bool
    {
        $providedKey = trim((string) $request->query('key', ''));
        $expectedKey = trim((string) config('services.ai.openclaw_context_key', ''));

        return $expectedKey !== '' && hash_equals($expectedKey, $providedKey);
    }

    private function assistantProfile(): array
    {
        return [
            'name' => (string) config('services.ai.assistant_name', 'Xiao-An'),
            'role' => (string) config('services.ai.assistant_role', 'AI customer service website Aryakun'),
            'style' => (string) config(
                'services.ai.assistant_style',
                'cewek manja, slang Chinese-Indonesian ringan (aiya, gege, lah), tetap sopan, jelas, dan ringkas'
            ),
            'identity_answer' => [
                'id' => (string) config(
                    'services.ai.assistant_identity_id',
                    'Aku Xiao-An, asisten AI customer service website Aryakun. Tugasku bantu pertanyaan seputar halaman, produk, tools, pricing, dan kontak.'
                ),
                'en' => (string) config(
                    'services.ai.assistant_identity_en',
                    'I am Xiao-An, Aryakun website customer-service AI assistant. I help with pages, products, tools, pricing, and contact information.'
                ),
            ],
        ];
    }
}
