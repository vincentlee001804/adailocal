import os
from pathlib import Path

from flask import Flask, request, redirect, url_for, render_template_string


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Keys that this UI will manage. Other keys in .env will be preserved.
MANAGED_KEYS = [
    # Feishu webhook bot (simple mode)
    "FEISHU_WEBHOOK_URL",
    "FEISHU_WEBHOOK_URL_2",
    "FEISHU_WEBHOOK_URL_3",
    "FEISHU_WEBHOOK_SECRET",
    # Feishu app mode (token API)
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_CHAT_ID",
    # News sending behaviour
    "MAX_PUSH_PER_CYCLE",
    "SEND_INTERVAL_SEC",
    "ONE_SHOT",
    "COLLECT_INTERVAL_SEC",
    "USE_APP_API",
    # AI / LLM configuration
    "USE_AI_SUMMARY",
    "GEMINI_API_KEY",
    "MIMO_API_KEY",
    "MIMO_API_BASE",
    "MIMO_MODEL",
    # Bitable logging
    "BITABLE_APP_TOKEN",
    "BITABLE_TABLE_ID",
    # Misc
    "SENT_NEWS_PATH",
    "TEST_WEBHOOKS",
]


def _load_env_lines():
    """Return the existing .env lines (or an empty list)."""
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8").splitlines()
    return []


def _parse_env(lines):
    """Parse KEY=VALUE pairs from .env-style content."""
    data = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _write_env(old_lines, file_env, new_values):
    """
    Merge new_values into existing .env content.

    - Preserve comments and unknown keys.
    - Update or append managed keys present in MANAGED_KEYS.
    """
    managed = set(MANAGED_KEYS)
    merged_env = dict(file_env)
    merged_env.update(new_values)

    result_lines = []
    seen_managed = set()

    for line in old_lines:
        raw = line.rstrip("\n")
        stripped = raw.strip()

        # Preserve comments / blanks as-is
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            result_lines.append(raw)
            continue

        key, _ = stripped.split("=", 1)
        key = key.strip()

        if key in managed:
            value = merged_env.get(key, "")
            result_lines.append(f"{key}={value}")
            seen_managed.add(key)
        else:
            # Unknown key – keep as-is
            result_lines.append(raw)

    # Append any managed keys that weren't present but now have a value
    for key in MANAGED_KEYS:
        if key in seen_managed:
            continue
        value = merged_env.get(key, "")
        if value != "":
            result_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(result_lines) + "\n", encoding="utf-8")


def _current_config():
    """
    Combine values from:
    - process env (highest priority)
    - .env file

    Returned dict only contains MANAGED_KEYS.
    """
    lines = _load_env_lines()
    file_env = _parse_env(lines)

    config = {}
    for key in MANAGED_KEYS:
        # Prefer real environment variables, then .env, else empty string
        config[key] = os.environ.get(key, file_env.get(key, ""))

    return config, lines, file_env


app = Flask(__name__)


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AdaiLocal Settings</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            brand: {
              50: '#eff6ff',
              100: '#dbeafe',
              500: '#3b82f6',
              600: '#2563eb',
              700: '#1d4ed8'
            }
          }
        }
      }
    }
  </script>
</head>
<body class="min-h-screen bg-slate-950 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-50">
  <div class="max-w-6xl mx-auto px-4 py-8 lg:py-10">
    <header class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
      <div>
        <div class="inline-flex items-center gap-2 rounded-full bg-slate-900/80 px-3 py-1 border border-slate-800 shadow-sm mb-3">
          <span class="inline-flex h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_2px_rgba(52,211,153,0.65)]"></span>
          <span class="text-xs font-medium tracking-wide text-emerald-200">Local instance</span>
        </div>
        <h1 class="text-3xl md:text-4xl font-semibold tracking-tight text-slate-50">
          AdaiLocal Settings
        </h1>
        <p class="mt-2 text-sm md:text-base text-slate-300 max-w-2xl">
          Configure Feishu webhooks, API keys, AI behaviour and logging. Changes are written to
          <code class="px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-800 text-xs font-mono">.env</code>.
          Restart <code class="px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-800 text-xs font-mono">adailocal.py</code> to apply.
        </p>
      </div>
      <div class="flex flex-col items-start md:items-end gap-2">
        <div class="rounded-xl border border-slate-800 bg-slate-900/80 px-4 py-2 text-xs text-slate-300 shadow-sm">
          <div class="flex items-center gap-2">
            <span class="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
            <span class="font-medium">Status</span>
          </div>
          <p class="mt-1 text-[11px] text-slate-400">
            Edit settings safely. No need to touch Python code.
          </p>
        </div>
      </div>
    </header>

    {% if saved %}
      <div class="mb-5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100 shadow-[0_0_18px_rgba(16,185,129,0.25)] flex items-start gap-3">
        <span class="mt-0.5">✅</span>
        <div>
          <p class="font-medium">Settings saved.</p>
          <p class="text-emerald-200/90 text-xs mt-0.5">
            Your values were written to <code class="bg-slate-900/60 px-1 rounded border border-emerald-500/30">.env</code>.
            Please restart the bot process to load the new configuration.
          </p>
        </div>
      </div>
    {% endif %}

    <form method="post" action="{{ url_for('index') }}" class="space-y-6">
      <!-- Layout: responsive two-column stack of cards -->
      <div class="grid gap-6 lg:grid-cols-2">
        <!-- Feishu Webhook Bot -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
                Feishu Webhook Bot
              </h2>
              <p class="mt-1 text-xs text-slate-400">
                Simple mode – send cards via one or more Feishu webhook robot URLs.
              </p>
            </div>
            <span class="inline-flex items-center rounded-full bg-slate-800/60 px-2.5 py-1 text-[11px] text-slate-300 border border-slate-700">
              Webhook mode
            </span>
          </div>
          <div class="px-5 py-4 space-y-4">
            <div class="space-y-3">
              <div>
                <label for="FEISHU_WEBHOOK_URL" class="block text-xs font-medium text-slate-200">
                  Primary Webhook URL
                </label>
                <input
                  type="text"
                  id="FEISHU_WEBHOOK_URL"
                  name="FEISHU_WEBHOOK_URL"
                  value="{{ config.FEISHU_WEBHOOK_URL }}"
                  placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
                <p class="mt-1 text-[11px] text-slate-400">
                  Required for basic sending to a single group.
                </p>
              </div>
              <div class="grid gap-3 sm:grid-cols-2">
                <div>
                  <label for="FEISHU_WEBHOOK_URL_2" class="block text-xs font-medium text-slate-200">
                    Secondary Webhook URL
                  </label>
                  <input
                    type="text"
                    id="FEISHU_WEBHOOK_URL_2"
                    name="FEISHU_WEBHOOK_URL_2"
                    value="{{ config.FEISHU_WEBHOOK_URL_2 }}"
                    class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                  />
                  <p class="mt-1 text-[11px] text-slate-400">
                    Optional – mirror news to a second group.
                  </p>
                </div>
                <div>
                  <label for="FEISHU_WEBHOOK_URL_3" class="block text-xs font-medium text-slate-200">
                    Tertiary Webhook URL
                  </label>
                  <input
                    type="text"
                    id="FEISHU_WEBHOOK_URL_3"
                    name="FEISHU_WEBHOOK_URL_3"
                    value="{{ config.FEISHU_WEBHOOK_URL_3 }}"
                    class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                  />
                  <p class="mt-1 text-[11px] text-slate-400">
                    Optional – third destination group.
                  </p>
                </div>
              </div>
              <div class="grid gap-3 sm:grid-cols-2">
                <div>
                  <label for="FEISHU_WEBHOOK_SECRET" class="block text-xs font-medium text-slate-200">
                    Webhook Secret
                  </label>
                  <input
                    type="text"
                    id="FEISHU_WEBHOOK_SECRET"
                    name="FEISHU_WEBHOOK_SECRET"
                    value="{{ config.FEISHU_WEBHOOK_SECRET }}"
                    class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                  />
                  <p class="mt-1 text-[11px] text-slate-400">
                    Optional – configure if your robot uses a signing secret.
                  </p>
                </div>
                <div class="flex items-center gap-3 pt-5">
                  <label for="TEST_WEBHOOKS" class="text-xs font-medium text-slate-200">
                    Test Webhooks
                  </label>
                  <label class="relative inline-flex cursor-pointer items-center">
                    <input
                      type="checkbox"
                      id="TEST_WEBHOOKS"
                      name="TEST_WEBHOOKS"
                      value="1"
                      class="peer sr-only"
                      {% if config.TEST_WEBHOOKS == "1" %}checked{% endif %}
                    />
                    <div class="h-5 w-9 rounded-full bg-slate-700 transition peer-checked:bg-emerald-500/90">
                      <div class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-slate-200 shadow-sm transition-transform peer-checked:translate-x-4 peer-checked:bg-white"></div>
                    </div>
                  </label>
                  <p class="text-[11px] text-slate-400">
                    Allow connectivity tests when enabled.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Feishu App API -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
                Feishu App API (Token)
              </h2>
              <p class="mt-1 text-xs text-slate-400">
                Advanced mode – use Feishu app credentials instead of webhooks.
              </p>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-400">USE_APP_API</span>
              <label class="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  id="USE_APP_API"
                  name="USE_APP_API"
                  value="1"
                  class="peer sr-only"
                  {% if config.USE_APP_API == "1" %}checked{% endif %}
                />
                <div class="h-5 w-9 rounded-full bg-slate-700 transition peer-checked:bg-brand-600">
                  <div class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-slate-200 shadow-sm transition-transform peer-checked:translate-x-4 peer-checked:bg-white"></div>
                </div>
              </label>
            </div>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div>
              <label for="FEISHU_APP_ID" class="block text-xs font-medium text-slate-200">
                Feishu App ID
              </label>
              <input
                type="text"
                id="FEISHU_APP_ID"
                name="FEISHU_APP_ID"
                value="{{ config.FEISHU_APP_ID }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
            </div>
            <div>
              <label for="FEISHU_APP_SECRET" class="block text-xs font-medium text-slate-200">
                Feishu App Secret
              </label>
              <input
                type="text"
                id="FEISHU_APP_SECRET"
                name="FEISHU_APP_SECRET"
                value="{{ config.FEISHU_APP_SECRET }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
            </div>
            <div>
              <label for="FEISHU_CHAT_ID" class="block text-xs font-medium text-slate-200">
                Target Chat ID
              </label>
              <input
                type="text"
                id="FEISHU_CHAT_ID"
                name="FEISHU_CHAT_ID"
                value="{{ config.FEISHU_CHAT_ID }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
              <p class="mt-1 text-[11px] text-slate-400">
                Group chat ID for API-based sending.
              </p>
            </div>
          </div>
        </section>
      </div>

      <!-- Second row: AI / Behaviour -->
      <div class="grid gap-6 lg:grid-cols-2">
        <!-- AI & LLM -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
                AI &amp; LLM Settings
              </h2>
              <p class="mt-1 text-xs text-slate-400">
                Control summarisation and LLM providers for Chinese titles and summaries.
              </p>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-400">USE_AI_SUMMARY</span>
              <label class="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  id="USE_AI_SUMMARY"
                  name="USE_AI_SUMMARY"
                  value="1"
                  class="peer sr-only"
                  {% if config.USE_AI_SUMMARY == "1" %}checked{% endif %}
                />
                <div class="h-5 w-9 rounded-full bg-slate-700 transition peer-checked:bg-brand-600">
                  <div class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-slate-200 shadow-sm transition-transform peer-checked:translate-x-4 peer-checked:bg-white"></div>
                </div>
              </label>
            </div>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div>
              <label for="GEMINI_API_KEY" class="block text-xs font-medium text-slate-200">
                Google Gemini API Key
              </label>
              <input
                type="text"
                id="GEMINI_API_KEY"
                name="GEMINI_API_KEY"
                value="{{ config.GEMINI_API_KEY }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
              <p class="mt-1 text-[11px] text-slate-400">
                Optional – used when Gemini is selected for summarisation.
              </p>
            </div>
            <div>
              <label for="MIMO_API_KEY" class="block text-xs font-medium text-slate-200">
                Xiaomi MiMo API Key
              </label>
              <input
                type="text"
                id="MIMO_API_KEY"
                name="MIMO_API_KEY"
                value="{{ config.MIMO_API_KEY }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <label for="MIMO_API_BASE" class="block text-xs font-medium text-slate-200">
                  MiMo API Base
                </label>
                <input
                  type="text"
                  id="MIMO_API_BASE"
                  name="MIMO_API_BASE"
                  value="{{ config.MIMO_API_BASE or 'https://api.xiaomimimo.com/v1' }}"
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
              </div>
              <div>
                <label for="MIMO_MODEL" class="block text-xs font-medium text-slate-200">
                  MiMo Model
                </label>
                <input
                  type="text"
                  id="MIMO_MODEL"
                  name="MIMO_MODEL"
                  value="{{ config.MIMO_MODEL or 'mimo-v2-flash' }}"
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
              </div>
            </div>
          </div>
        </section>

        <!-- Behaviour -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
                Sending Behaviour
              </h2>
              <p class="mt-1 text-xs text-slate-400">
                Control how many messages are sent and how often the collector runs.
              </p>
            </div>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <label for="MAX_PUSH_PER_CYCLE" class="block text-xs font-medium text-slate-200">
                  Max Messages Per Cycle
                </label>
                <input
                  type="number"
                  id="MAX_PUSH_PER_CYCLE"
                  name="MAX_PUSH_PER_CYCLE"
                  min="1"
                  value="{{ config.MAX_PUSH_PER_CYCLE or '1' }}"
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
                <p class="mt-1 text-[11px] text-slate-400">
                  Default is 1. Increase to push more items in each run.
                </p>
              </div>
              <div>
                <label for="SEND_INTERVAL_SEC" class="block text-xs font-medium text-slate-200">
                  Interval Between Messages (seconds)
                </label>
                <input
                  type="number"
                  step="0.1"
                  id="SEND_INTERVAL_SEC"
                  name="SEND_INTERVAL_SEC"
                  min="0"
                  value="{{ config.SEND_INTERVAL_SEC or '1.0' }}"
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
              </div>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <label for="COLLECT_INTERVAL_SEC" class="block text-xs font-medium text-slate-200">
                  Loop Interval (seconds)
                </label>
                <input
                  type="number"
                  id="COLLECT_INTERVAL_SEC"
                  name="COLLECT_INTERVAL_SEC"
                  min="60"
                  value="{{ config.COLLECT_INTERVAL_SEC or '600' }}"
                  class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
                />
                <p class="mt-1 text-[11px] text-slate-400">
                  Default is 600 (10 minutes) between collection cycles.
                </p>
              </div>
              <div class="flex items-center gap-3 pt-5">
                <label for="ONE_SHOT" class="text-xs font-medium text-slate-200">
                  One-Shot Mode
                </label>
                <label class="relative inline-flex cursor-pointer items-center">
                  <input
                    type="checkbox"
                    id="ONE_SHOT"
                    name="ONE_SHOT"
                    value="1"
                    class="peer sr-only"
                    {% if config.ONE_SHOT == "1" %}checked{% endif %}
                  />
                  <div class="h-5 w-9 rounded-full bg-slate-700 transition peer-checked:bg-amber-500">
                    <div class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-slate-200 shadow-sm transition-transform peer-checked:translate-x-4 peer-checked:bg-white"></div>
                  </div>
                </label>
                <p class="text-[11px] text-slate-400">
                  Run once then exit instead of looping.
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- Third row: Bitable + Advanced -->
      <div class="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <!-- Bitable -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4 flex items-center justify-between gap-3">
            <div>
              <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
                Bitable Logging (Optional)
              </h2>
              <p class="mt-1 text-xs text-slate-400">
                Log sent news into Feishu Bitable. Leave blank to disable.
              </p>
            </div>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div>
              <label for="BITABLE_APP_TOKEN" class="block text-xs font-medium text-slate-200">
                Bitable App Token
              </label>
              <input
                type="text"
                id="BITABLE_APP_TOKEN"
                name="BITABLE_APP_TOKEN"
                value="{{ config.BITABLE_APP_TOKEN }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
            </div>
            <div>
              <label for="BITABLE_TABLE_ID" class="block text-xs font-medium text-slate-200">
                Bitable Table ID
              </label>
              <input
                type="text"
                id="BITABLE_TABLE_ID"
                name="BITABLE_TABLE_ID"
                value="{{ config.BITABLE_TABLE_ID }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
            </div>
          </div>
        </section>

        <!-- Advanced -->
        <section class="rounded-2xl border border-slate-800 bg-slate-900/80 shadow-[0_18px_45px_rgba(15,23,42,0.65)] backdrop-blur-sm">
          <div class="border-b border-slate-800 px-5 py-4">
            <h2 class="text-sm font-semibold tracking-wide text-slate-100 uppercase">
              Advanced
            </h2>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div>
              <label for="SENT_NEWS_PATH" class="block text-xs font-medium text-slate-200">
                Sent News Log Path
              </label>
              <input
                type="text"
                id="SENT_NEWS_PATH"
                name="SENT_NEWS_PATH"
                value="{{ config.SENT_NEWS_PATH }}"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/40 outline-none transition"
              />
              <p class="mt-1 text-[11px] text-slate-400">
                Optional custom file path for the persistent deduplication log.
              </p>
            </div>
          </div>
        </section>
      </div>

      <div class="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="submit"
          class="inline-flex items-center justify-center rounded-full bg-gradient-to-r from-brand-500 via-brand-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_14px_35px_rgba(59,130,246,0.55)] hover:brightness-110 hover:shadow-[0_18px_45px_rgba(59,130,246,0.65)] transition"
        >
          Save Settings
        </button>
        <p class="text-[11px] text-slate-400">
          Run with <code class="bg-slate-900/80 border border-slate-800 px-1 rounded font-mono text-[11px]">python settings_ui.py</code>
          and open <code class="bg-slate-900/80 border border-slate-800 px-1 rounded font-mono text-[11px]">http://127.0.0.1:5000</code> in your browser.
        </p>
      </div>
    </form>
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    config, lines, file_env = _current_config()

    if request.method == "POST":
        form = request.form
        new_values = {}

        # Text fields (direct mappings)
        text_keys = [
            "FEISHU_WEBHOOK_URL",
            "FEISHU_WEBHOOK_URL_2",
            "FEISHU_WEBHOOK_URL_3",
            "FEISHU_WEBHOOK_SECRET",
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_CHAT_ID",
            "MAX_PUSH_PER_CYCLE",
            "SEND_INTERVAL_SEC",
            "COLLECT_INTERVAL_SEC",
            "GEMINI_API_KEY",
            "MIMO_API_KEY",
            "MIMO_API_BASE",
            "MIMO_MODEL",
            "BITABLE_APP_TOKEN",
            "BITABLE_TABLE_ID",
            "SENT_NEWS_PATH",
        ]
        for key in text_keys:
            new_values[key] = form.get(key, "").strip()

        # Checkbox / boolean-like flags (store "1" or "0")
        bool_keys = [
            "USE_APP_API",
            "USE_AI_SUMMARY",
            "ONE_SHOT",
            "TEST_WEBHOOKS",
        ]
        for key in bool_keys:
            new_values[key] = "1" if form.get(key) else "0"

        _write_env(lines, file_env, new_values)

        # Refresh config view with new values
        config.update(new_values)
        return render_template_string(TEMPLATE, config=config, saved=True)

    return render_template_string(TEMPLATE, config=config, saved=False)


if __name__ == "__main__":
    # Bind only to localhost by default for safety.
    app.run(host="127.0.0.1", port=5000, debug=False)

