<?php
declare(strict_types=1);

return [
    'db_host' => 'localhost',
    'db_port' => 3306,
    'db_name' => 'pocketbrain',
    'db_user' => 'pocketbrain',
    'db_password' => '',
    'base_url' => 'https://peabrain.se',
    // Generate once with: php -r 'echo bin2hex(random_bytes(32)), PHP_EOL;'
    'app_key' => '',
    // Users add personal API keys in the dashboard. These are encrypted with app_key.
    // Keep app_key stable and back it up separately from the database.
    // Optional shared billing for users without a personal key; disabled by default.
    'allow_shared_openai_key' => false,
    'openai_api_key' => '',
    'openai_realtime_model' => 'gpt-realtime-2.1',
    'enable_weather' => true,
    'enable_web_search' => true,
    'openai_search_model' => 'gpt-5.4-mini',
    // Optional Open-Meteo subscription key for commercial hosting.
    'open_meteo_api_key' => '',
    // Public operator details for legal pages. Never put private contact data here.
    'legal_operator_name' => 'Peabrain Systems',
    'legal_contact_email' => 'info@peabrain.se',
    'legal_operator_address' => '',
    // Set true only after completing and reviewing the draft policies.
    'legal_documents_reviewed' => false,
];
