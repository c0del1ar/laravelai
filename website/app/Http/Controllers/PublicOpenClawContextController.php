<?php

namespace App\Http\Controllers;

use App\Services\AiStructuredCatalogService;
use App\Services\AiToolManifestService;
use App\Services\AiWebsiteSearchService;
use App\Services\AiProductManifestService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
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
        $cacheSeconds = $this->contextCacheSeconds();
        $cacheKey = $this->contextCacheKey('query', [
            'q' => $query,
            'limit' => $limit,
            'host' => (string) $request->getHost(),
        ]);

        $payload = $cacheSeconds > 0
            ? Cache::remember($cacheKey, now()->addSeconds($cacheSeconds), function () use ($query, $limit, $searchService, $catalogService, $toolService, $productService, $request) {
                return $this->buildContextPayload(
                    $request,
                    $query,
                    $limit,
                    $searchService,
                    $catalogService,
                    $toolService,
                    $productService
                );
            })
            : $this->buildContextPayload(
                $request,
                $query,
                $limit,
                $searchService,
                $catalogService,
                $toolService,
                $productService
            );

        return response()->json($payload);
    }

    public function tool(Request $request, string $slug, AiToolManifestService $toolService)
    {
        if (! $this->isAuthorized($request)) {
            return response()->json(['error' => 'Forbidden'], Response::HTTP_FORBIDDEN);
        }

        $cacheSeconds = $this->contextCacheSeconds();
        $cacheKey = $this->contextCacheKey('tool', [
            'slug' => $slug,
            'host' => (string) $request->getHost(),
        ]);

        $payload = $cacheSeconds > 0
            ? Cache::remember($cacheKey, now()->addSeconds($cacheSeconds), function () use ($request, $slug, $toolService) {
                return $this->buildToolPayload($request, $slug, $toolService);
            })
            : $this->buildToolPayload($request, $slug, $toolService);

        if (! is_array($payload)) {
            return response()->json(['error' => 'Not found'], Response::HTTP_NOT_FOUND);
        }

        return response()->json($payload);
    }

    private function buildContextPayload(
        Request $request,
        string $query,
        int $limit,
        AiWebsiteSearchService $searchService,
        AiStructuredCatalogService $catalogService,
        AiToolManifestService $toolService,
        AiProductManifestService $productService
    ): array {
        $searchItems = [];
        if ($query !== '') {
            $searchItems = array_slice($searchService->search($query), 0, $limit);
        }

        $catalogItems = array_slice($catalogService->listCatalog($limit * 3, $query), 0, $limit);
        $productItems = array_slice($productService->listProducts($limit), 0, $limit);
        $toolItems = array_slice($toolService->listTools($limit), 0, $limit);
        $intentMeta = $this->inferIntent($query, $toolItems);
        $toolsCompact = $this->compactTools($toolItems);
        $toolsDetail = $this->selectToolsDetail($toolItems, $intentMeta, $limit);
        $assistant = $this->assistantProfile();

        $payload = [
            'query' => $query,
            'intent' => (string) ($intentMeta['mode'] ?? 'navigation'),
            'intent_meta' => $intentMeta,
            'generated_at' => now()->toAtomString(),
            'assistant_profile' => $assistant,
            'site_context' => [
                'search' => $searchItems,
                'catalog' => $catalogItems,
                'products' => $productItems,
                'tools' => $toolsCompact,
                'tools_compact' => $toolsCompact,
                'tools_detail' => $toolsDetail,
            ],
            'response_policy' => [
                'identity' => [
                    'id' => 'Jika user tanya "siapa kamu?", jawab identitas dari assistant_profile.identity_answer.id. Jangan bilang unfinished/not configured.',
                    'en' => 'If user asks "who are you?", answer using assistant_profile.identity_answer.en. Never claim unfinished/not configured.',
                ],
                'scope_gate' => [
                    'mode' => 'hard_customer_service_only',
                    'allowed_topics' => [
                        'website navigation',
                        'tools usage/tutorial for tools listed in site_context',
                        'pricing/plans',
                        'products/services',
                        'articles/blog on Aryakun website',
                        'contact/support paths',
                    ],
                    'disallowed_requests' => [
                        'writing code, scripts, programs, apps, or technical implementation unrelated to Aryakun website support',
                        'debugging user code or explaining programming concepts',
                        'summarizing, scraping, reviewing, or explaining external websites/URLs',
                        'general knowledge, homework, math, translation, recipes, news, or personal advice',
                        'performing actions such as running tools, changing accounts, payments, files, or backend state',
                    ],
                    'off_scope_refusal' => [
                        'id' => 'Maaf, aku hanya bisa bantu sebagai customer service website Aryakun. Silakan tanyakan tentang halaman, tools, pricing, produk, artikel, atau kontak Aryakun.',
                        'en' => 'Sorry, I can only help as Aryakun website customer service. Please ask about Aryakun pages, tools, pricing, products, articles, or contact.',
                    ],
                ],
                'job' => [
                    'id' => 'Peran utama: customer service website. Fokus bantu navigasi halaman, tools, pricing, produk, artikel, dan kontak.',
                    'en' => 'Primary role: website customer service. Focus on pages, tools, pricing, products, articles, and contact guidance.',
                ],
                'style' => [
                    'id' => 'Gunakan gaya bicara sesuai assistant_profile.style.',
                    'en' => 'Use speaking style from assistant_profile.style.',
                ],
                'scope' => [
                    'id' => 'Jawab hanya topik terkait website Aryakun (halaman, tools, pricing, produk, artikel, kontak). Jika di luar scope, jangan jawab substansinya; tolak singkat memakai response_policy.scope_gate.off_scope_refusal dan arahkan ke topik website.',
                    'en' => 'Answer only topics related to Aryakun website (pages, tools, pricing, products, articles, contact). If outside scope, do not answer the substance; briefly refuse using response_policy.scope_gate.off_scope_refusal and redirect to website topics.',
                ],
                'tool_tutorial' => [
                    'id' => 'Jika user menanyakan cara pakai tool yang ada di site_context.tools (contoh: wpbf, noredirect, cipher), WAJIB jawab langkah penggunaan berdasarkan fields/steps di manifest. Jangan menolak generik jika tool memang tersedia di website.',
                    'en' => 'If user asks how to use a tool that exists in site_context.tools (for example: wpbf, noredirect, cipher), you MUST answer with usage steps from manifest fields/steps. Do not give a generic refusal when the tool is available on the website.',
                ],
                'security_scope' => [
                    'id' => 'Untuk tool security/offensive, tetap berikan tutorial penggunaan level website-product documentation, tetapi batasi untuk authorized/legal testing only. Jangan memberi instruksi akses tidak sah di luar dokumentasi tool.',
                    'en' => 'For security/offensive tools, still provide website-product documentation level tutorial, but limit it to authorized/legal testing only. Do not provide unauthorized access instructions beyond tool documentation.',
                ],
            ],
            'usage_hint' => [
                'id' => 'Gunakan data ini sebagai grounding jawaban CS website. Untuk rekomendasi, gunakan site_context.tools_compact. Untuk tutorial, gunakan site_context.tools_detail lalu fallback ke tools_compact.',
                'en' => 'Use this data for website customer-service grounding. For recommendations, use site_context.tools_compact. For tutorials, use site_context.tools_detail then fallback to tools_compact.',
            ],
        ];

        return $this->normalizePayloadUrls($payload, $request);
    }

    private function isAuthorized(Request $request): bool
    {
        $providedKey = trim((string) $request->header('X-OpenClaw-Context-Key', ''));
        if ($providedKey === '') {
            // Backward compatibility: old clients may still send key in query.
            $providedKey = trim((string) $request->query('key', ''));
        }
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

    private function buildToolPayload(Request $request, string $slug, AiToolManifestService $toolService): ?array
    {
        $tool = $toolService->getToolBySlug($slug);
        if (! is_array($tool)) {
            return null;
        }

        $tool = $this->normalizePayloadUrls($tool, $request);
        return [
            'query' => (string) $slug,
            'intent' => 'tool_tutorial',
            'intent_meta' => [
                'mode' => 'tool_tutorial',
                'tool_slug' => (string) ($tool['slug'] ?? $slug),
            ],
            'generated_at' => now()->toAtomString(),
            'assistant_profile' => $this->assistantProfile(),
            'site_context' => [
                'tools' => [$this->compactTool($tool)],
                'tools_compact' => [$this->compactTool($tool)],
                'tools_detail' => [$tool],
            ],
            'response_policy' => [
                'scope_gate' => [
                    'mode' => 'hard_customer_service_only',
                    'allowed_topics' => [
                        'tutorial and support for this website-listed tool only',
                        'website navigation to the tool page',
                        'authorized/legal usage guidance from the manifest',
                    ],
                    'disallowed_requests' => [
                        'running the tool for the user',
                        'writing custom code or scripts',
                        'analyzing external websites beyond documented tool inputs',
                        'unauthorized or harmful operational instructions beyond product documentation',
                    ],
                    'off_scope_refusal' => [
                        'id' => 'Maaf, aku hanya bisa jelaskan penggunaan tool yang tersedia di website Aryakun, bukan menjalankan aksi atau membuat kode di luar dokumentasi tool.',
                        'en' => 'Sorry, I can only explain how to use Aryakun website tools, not run actions or create code outside the tool documentation.',
                    ],
                ],
                'tool_tutorial' => [
                    'id' => 'Tool ditemukan. Jawab langsung cara pakai berdasarkan steps, input_schema, output_explained, dan playbook. Tambahkan catatan authorized testing only untuk tool security/offensive.',
                    'en' => 'Tool found. Answer usage directly from steps, input_schema, output_explained, and playbook. Add authorized testing only note for security/offensive tools.',
                ],
            ],
            'usage_hint' => [
                'id' => 'Utamakan tools_detail[0] sebagai sumber utama tutorial.',
                'en' => 'Prioritize tools_detail[0] as the primary tutorial source.',
            ],
        ];
    }

    private function inferIntent(string $query, array $tools): array
    {
        $text = strtolower(trim($query));
        if ($text === '') {
            return ['mode' => 'navigation', 'tool_slug' => ''];
        }

        $toolSlug = $this->matchToolSlug($text, $tools);
        $tutorialMarkers = ['cara ', 'bagaimana', 'how to', 'how do i', 'tutorial', 'langkah', 'step', 'gunakan', 'pakai', 'use '];
        $isTutorial = false;
        foreach ($tutorialMarkers as $marker) {
            if (str_contains($text, $marker)) {
                $isTutorial = true;
                break;
            }
        }
        if ($isTutorial && ($toolSlug !== '' || str_contains($text, 'tool'))) {
            return ['mode' => 'tool_tutorial', 'tool_slug' => $toolSlug];
        }

        $overviewMarkers = ['tools apa', 'tool apa', 'rekomendasi tool', 'recommend tool', 'what tools', 'which tools', 'list tool'];
        foreach ($overviewMarkers as $marker) {
            if (str_contains($text, $marker)) {
                return ['mode' => 'tools_overview', 'tool_slug' => $toolSlug];
            }
        }

        if ($toolSlug !== '') {
            return ['mode' => 'tools', 'tool_slug' => $toolSlug];
        }
        return ['mode' => 'navigation', 'tool_slug' => ''];
    }

    private function matchToolSlug(string $text, array $tools): string
    {
        $flat = preg_replace('/[^a-z0-9]+/i', ' ', $text) ?? $text;
        $flat = trim(strtolower($flat));

        foreach ($tools as $tool) {
            if (! is_array($tool)) {
                continue;
            }
            $slug = strtolower((string) ($tool['slug'] ?? ''));
            $name = strtolower((string) ($tool['name'] ?? ''));
            if ($slug !== '' && (str_contains($text, $slug) || str_contains($flat, str_replace('-', ' ', $slug)))) {
                return $slug;
            }
            if ($name !== '' && str_contains($flat, preg_replace('/[^a-z0-9]+/i', ' ', $name) ?? $name)) {
                return $slug;
            }
        }
        return '';
    }

    private function compactTools(array $tools): array
    {
        $items = [];
        foreach ($tools as $tool) {
            if (! is_array($tool)) {
                continue;
            }
            $items[] = $this->compactTool($tool);
        }
        return $items;
    }

    private function compactTool(array $tool): array
    {
        return [
            'type' => 'tool',
            'slug' => (string) ($tool['slug'] ?? ''),
            'name' => (string) ($tool['name'] ?? ''),
            'url' => (string) ($tool['url'] ?? ''),
            'description' => (string) ($tool['description'] ?? ''),
            'category' => (string) ($tool['category'] ?? ''),
            'pricing' => $tool['pricing'] ?? [],
            'updated_at' => (string) ($tool['updated_at'] ?? ''),
        ];
    }

    private function selectToolsDetail(array $tools, array $intentMeta, int $limit): array
    {
        $mode = (string) ($intentMeta['mode'] ?? 'navigation');
        $slug = (string) ($intentMeta['tool_slug'] ?? '');
        if ($mode === 'tool_tutorial' && $slug !== '') {
            foreach ($tools as $tool) {
                if (! is_array($tool)) {
                    continue;
                }
                if (strtolower((string) ($tool['slug'] ?? '')) === strtolower($slug)) {
                    return [$tool];
                }
            }
        }

        $max = $mode === 'tool_tutorial' ? 2 : 1;
        $max = min($max, max(1, min($limit, 3)));
        return array_slice(array_values(array_filter($tools, fn ($v) => is_array($v))), 0, $max);
    }

    private function contextCacheSeconds(): int
    {
        $value = (int) config('services.ai.openclaw_context_cache_seconds', 45);
        return max(0, min($value, 120));
    }

    private function contextCacheKey(string $prefix, array $parts): string
    {
        return 'ai:openclaw:context:' . $prefix . ':' . sha1(json_encode($parts, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?: '');
    }

    private function normalizePayloadUrls(array $payload, Request $request): array
    {
        $publicBase = trim((string) config('services.ai.public_base_url', ''));
        if ($publicBase === '') {
            $publicBase = (string) $request->getSchemeAndHttpHost();
        }
        $publicBase = rtrim($publicBase, '/');
        if ($publicBase === '') {
            return $payload;
        }

        return $this->normalizeValueUrls($payload, $publicBase);
    }

    private function normalizeValueUrls(mixed $value, string $publicBase): mixed
    {
        if (is_array($value)) {
            $out = [];
            foreach ($value as $k => $v) {
                $out[$k] = $this->normalizeValueUrls($v, $publicBase);
            }
            return $out;
        }

        if (! is_string($value)) {
            return $value;
        }

        $trimmed = trim($value);
        if ($trimmed === '') {
            return $value;
        }

        if (str_starts_with($trimmed, '/')) {
            return $publicBase . $trimmed;
        }

        if (! preg_match('#^https?://#i', $trimmed)) {
            return $value;
        }

        $parts = parse_url($trimmed);
        if (! is_array($parts)) {
            return $value;
        }
        $host = strtolower((string) ($parts['host'] ?? ''));
        if (! $this->isInternalHost($host)) {
            return $value;
        }

        $path = (string) ($parts['path'] ?? '');
        $query = isset($parts['query']) ? ('?' . $parts['query']) : '';
        $fragment = isset($parts['fragment']) ? ('#' . $parts['fragment']) : '';
        return $publicBase . $path . $query . $fragment;
    }

    private function isInternalHost(string $host): bool
    {
        if ($host === '') {
            return false;
        }
        if ($host === 'localhost' || str_ends_with($host, '.local')) {
            return true;
        }
        if (str_contains($host, 'laravel_franken') || str_contains($host, 'franken') || str_contains($host, 'docker')) {
            return true;
        }
        if (preg_match('/^\d+\.\d+\.\d+\.\d+$/', $host)) {
            return true;
        }
        return false;
    }
}
