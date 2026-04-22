<?php

use App\Http\Controllers\AiProxyController;
use App\Http\Controllers\InternalAiCatalogController;
use App\Http\Controllers\InternalAiIndexController;
use App\Http\Controllers\InternalAiProductsController;
use App\Http\Controllers\InternalAiSearchController;
use App\Http\Controllers\InternalAiToolsController;
use App\Http\Controllers\PublicOpenClawContextController;
use Illuminate\Support\Facades\Route;

Route::post('/ai/chat', AiProxyController::class);
Route::get('/ai/openclaw/context', PublicOpenClawContextController::class);

// Endpoint ini dipakai oleh FastAPI dari docker network internal.
// Lindungi dengan header X-Search-Key.
Route::get('/internal/ai/search', InternalAiSearchController::class);
Route::get('/internal/ai/catalog', InternalAiCatalogController::class);
Route::get('/internal/ai/products', [InternalAiProductsController::class, 'index']);
Route::get('/internal/ai/products/{slug}', [InternalAiProductsController::class, 'show']);
Route::get('/internal/ai/tools', [InternalAiToolsController::class, 'index']);
Route::get('/internal/ai/tools/{slug}', [InternalAiToolsController::class, 'show']);
Route::post('/internal/ai/index/changed', InternalAiIndexController::class);
Route::post('/internal/ai/index/events', InternalAiIndexController::class);
