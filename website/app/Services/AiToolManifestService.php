<?php

namespace App\Services;

use App\Models\Tool;

class AiToolManifestService
{
    public function listTools(int $limit = 100): array
    {
        $tools = Tool::query()
            ->where('is_active', true)
            ->orderBy('sort_order')
            ->orderBy('name')
            ->limit(max(1, min($limit, 300)))
            ->get();

        return $tools->map(fn (Tool $tool) => $this->buildManifest($tool))->values()->all();
    }

    public function getToolBySlug(string $slug): ?array
    {
        $tool = Tool::query()
            ->where('slug', $slug)
            ->where('is_active', true)
            ->first();

        if (! $tool) {
            return null;
        }

        return $this->buildManifest($tool);
    }

    public function buildManifest(Tool $tool): array
    {
        $schema = is_array($tool->input_schema) ? $tool->input_schema : [];
        $fields = is_array($schema['fields'] ?? null) ? $schema['fields'] : [];
        $settings = is_array($tool->settings) ? $tool->settings : [];

        $fieldSpecs = array_values(array_filter(array_map(function (array $field) {
            $key = (string) ($field['key'] ?? '');
            if ($key === '') {
                return null;
            }

            $rawOptions = is_array($field['options'] ?? null) ? $field['options'] : [];
            $options = array_values(array_filter(array_map(function ($option) {
                if (! is_array($option)) {
                    return null;
                }

                return [
                    'value' => (string) ($option['value'] ?? ''),
                    'label' => (string) ($option['label'] ?? ''),
                    'hint' => (string) ($option['hint'] ?? ''),
                ];
            }, $rawOptions)));

            return [
                'key' => $key,
                'label' => (string) ($field['label'] ?? $key),
                'type' => (string) ($field['type'] ?? 'text'),
                'required' => (bool) ($field['required'] ?? false),
                'placeholder' => (string) ($field['placeholder'] ?? ''),
                'hint' => (string) ($field['hint'] ?? ''),
                'default' => $field['default'] ?? null,
                'trigger_estimate' => (bool) ($field['trigger_estimate'] ?? false),
                'accept' => (string) ($field['accept'] ?? ''),
                'unit' => (string) ($field['unit'] ?? ''),
                'options' => $options,
            ];
        }, $fields)));

        $steps = $this->buildSteps($tool, $fieldSpecs, $settings);
        $playbook = $this->buildPlaybook($tool, $fieldSpecs, $settings, $steps);
        $playbookI18n = $this->buildPlaybookI18n($tool, $playbook, $settings);

        $outputExplained = (string) data_get($settings, 'ai_manifest.output_explained', '');
        if ($outputExplained === '') {
            $outputExplained = 'After execution, review the generated result area. For noredirect, output usually includes iframe preview, source code, and raw HTML.';
        }

        $faq = data_get($settings, 'ai_manifest.faq', []);
        if (! is_array($faq) || $faq === []) {
            $faq = [
                [
                    'q' => 'Kenapa tool tidak jalan?',
                    'a' => 'Pastikan semua field wajib terisi dan format input valid.',
                ],
                [
                    'q' => 'Kenapa hasil kosong?',
                    'a' => 'Coba input lain, pastikan URL/teks target benar, lalu jalankan ulang.',
                ],
            ];
        }

        $errorCases = data_get($settings, 'ai_manifest.error_cases', []);
        if (! is_array($errorCases) || $errorCases === []) {
            $errorCases = [
                'Validation failed: field wajib belum terisi atau format tidak valid.',
                'Insufficient tokens: top up token atau gunakan tool gratis.',
                'Tool processing failed: coba lagi dengan input lebih sederhana.',
            ];
        }

        return [
            'type' => 'tool',
            'slug' => (string) $tool->slug,
            'name' => (string) $tool->name,
            'url' => (string) $tool->url,
            'description' => (string) ($tool->description ?? ''),
            'category' => (string) ($tool->category?->name ?? ''),
            'pricing' => [
                'pricing_type' => (string) ($tool->pricing_type ?? ''),
                'price_label' => (string) ($tool->price_label ?? ''),
                'token_unit' => (string) ($tool->token_unit ?? ''),
                'token_cost' => (int) ($tool->token_cost ?? 0),
                'token_rate' => (int) ($tool->token_rate ?? 0),
            ],
            'input_schema' => [
                'fields' => $fieldSpecs,
            ],
            'steps' => $steps,
            'playbook' => $playbook,
            'playbook_i18n' => $playbookI18n,
            'output_explained' => $outputExplained,
            'faq' => $faq,
            'error_cases' => $errorCases,
            'updated_at' => optional($tool->updated_at)->toAtomString(),
        ];
    }

    private function buildSteps(Tool $tool, array $fields, array $settings): array
    {
        $customSteps = data_get($settings, 'ai_manifest.steps', []);
        if (is_array($customSteps) && $customSteps !== []) {
            return array_values(array_map(fn ($v) => (string) $v, $customSteps));
        }

        $steps = [
            'Open the tool page: ' . $tool->url,
        ];

        if ($fields === []) {
            $steps[] = 'No input field is required. Click execute directly.';
        } else {
            foreach ($fields as $idx => $field) {
                $requiredText = $field['required'] ? ' (required)' : ' (optional)';
                $hint = trim((string) ($field['hint'] ?? ''));
                $label = trim((string) ($field['label'] ?? $field['key']));
                $line = 'Fill field #' . ($idx + 1) . ': ' . $label . $requiredText;
                if ($hint !== '') {
                    $line .= ' — ' . $hint;
                }
                $steps[] = $line;
            }
        }

        $steps[] = 'Click execute/process to run the tool.';
        $steps[] = 'Review the output section and copy/download the result as needed.';

        return $steps;
    }

    private function buildPlaybook(Tool $tool, array $fields, array $settings, array $steps): array
    {
        $fromSettings = data_get($settings, 'ai_playbook', []);
        $fromSettings = is_array($fromSettings) ? $fromSettings : [];

        $whatItDoes = (string) ($fromSettings['what_it_does'] ?? '');
        if ($whatItDoes === '') {
            $whatItDoes = (string) ($tool->description ?? '');
        }

        $inputTips = $fromSettings['input_tips'] ?? [];
        if (! is_array($inputTips) || $inputTips === []) {
            $inputTips = $this->defaultInputTips($fields);
        } else {
            $inputTips = array_values(array_map(fn ($v) => (string) $v, $inputTips));
        }

        $exampleInput = $fromSettings['example_input'] ?? [];
        $exampleInput = is_array($exampleInput) ? $exampleInput : [];

        $troubleshooting = $fromSettings['troubleshooting'] ?? [];
        if (! is_array($troubleshooting) || $troubleshooting === []) {
            $troubleshooting = [
                'Pastikan field wajib terisi sesuai format.',
                'Jika hasil kosong, coba input lebih spesifik.',
                'Jika proses gagal, refresh halaman dan ulangi dengan data baru.',
            ];
        } else {
            $troubleshooting = array_values(array_map(fn ($v) => (string) $v, $troubleshooting));
        }

        $shortcut = $fromSettings['shortcut'] ?? [];
        $shortcut = is_array($shortcut) ? $shortcut : [];

        return [
            'what_it_does' => $whatItDoes,
            'steps' => $steps,
            'input_tips' => $inputTips,
            'example_input' => $exampleInput,
            'troubleshooting' => $troubleshooting,
            'shortcut' => $shortcut,
        ];
    }

    private function defaultInputTips(array $fields): array
    {
        $tips = [];
        foreach ($fields as $field) {
            $label = trim((string) ($field['label'] ?? $field['key'] ?? 'Input'));
            $type = trim((string) ($field['type'] ?? 'text'));
            $required = (bool) ($field['required'] ?? false);
            $tip = $label . ': gunakan format ' . $type;
            if ($required) {
                $tip .= ' dan wajib diisi';
            }
            $tips[] = $tip . '.';
            if (count($tips) >= 8) {
                break;
            }
        }

        return $tips;
    }

    private function buildPlaybookI18n(Tool $tool, array $playbook, array $settings): array
    {
        $fromSettings = data_get($settings, 'ai_playbook_i18n', []);
        $fromSettings = is_array($fromSettings) ? $fromSettings : [];

        $id = is_array($fromSettings['id'] ?? null) ? $fromSettings['id'] : [];
        $en = is_array($fromSettings['en'] ?? null) ? $fromSettings['en'] : [];

        $whatId = trim((string) ($id['what_it_does'] ?? ''));
        if ($whatId === '') {
            $whatId = trim((string) ($playbook['what_it_does'] ?? ''));
        }

        $whatEn = trim((string) ($en['what_it_does'] ?? ''));
        if ($whatEn === '') {
            $whatEn = trim((string) ($playbook['what_it_does'] ?? ''));
            if ($whatEn === '') {
                $whatEn = trim((string) ($tool->description ?? ''));
            }
        }

        $inputTipsId = $this->stringListOrFallback($id['input_tips'] ?? null, $playbook['input_tips'] ?? []);
        $inputTipsEn = $this->stringListOrFallback($en['input_tips'] ?? null, $playbook['input_tips'] ?? []);

        $troubleshootId = $this->stringListOrFallback($id['troubleshooting'] ?? null, $playbook['troubleshooting'] ?? []);
        $troubleshootEn = $this->stringListOrFallback($en['troubleshooting'] ?? null, $playbook['troubleshooting'] ?? []);

        return [
            'id' => [
                'what_it_does' => $whatId,
                'input_tips' => $inputTipsId,
                'troubleshooting' => $troubleshootId,
            ],
            'en' => [
                'what_it_does' => $whatEn,
                'input_tips' => $inputTipsEn,
                'troubleshooting' => $troubleshootEn,
            ],
        ];
    }

    private function stringListOrFallback(mixed $primary, mixed $fallback): array
    {
        $candidate = is_array($primary) ? $primary : [];
        $candidate = array_values(array_filter(array_map(fn ($v) => trim((string) $v), $candidate), fn ($v) => $v !== ''));
        if ($candidate !== []) {
            return $candidate;
        }

        $backup = is_array($fallback) ? $fallback : [];
        return array_values(array_filter(array_map(fn ($v) => trim((string) $v), $backup), fn ($v) => $v !== ''));
    }
}
