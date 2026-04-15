<?php

namespace App\Providers;

use App\Services\AiAutoIndexObserverRegistrar;
use Illuminate\Support\ServiceProvider;

class AiAutoIndexServiceProvider extends ServiceProvider
{
    public function boot(AiAutoIndexObserverRegistrar $registrar): void
    {
        $registrar->register();
    }
}
