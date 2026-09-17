# Sparrow Configuration Template

Copy the TOML block below to `~/.config/sparrow/config.toml`.
Everything is optional. Environment variables override values in this file.

```toml
[keys]
# Provider API keys use the same names as environment variables.
# GROQ_API_KEY = "gsk_..."
# CEREBRAS_API_KEY = "csk-..."

# Optional explicit credential slots.
# [[credentials]]
# provider = "groq"
# id = "primary"
# env_var = "GROQ_API_KEY"
# quota_group = "organization-main"
# enabled = true

# Multiple provider keys can be declared through provider tables.
# [providers.nvidia]
# enabled = true
# api_keys = [
#   { env = "NVIDIA_API_KEY_1" },
#   { env = "NVIDIA_API_KEY_2" },
#   { env = "NVIDIA_API_KEY_3" },
# ]

[aliases]
# Map model names to a provider, provider/model, or "auto".
# "gpt-4o-mini" = "groq/llama-3.3-70b-versatile"
# "my-fast-model" = "groq/llama-3.3-70b-versatile"

[settings]
# cooldown_seconds = 60
# routing = "fair"
# Valid routing values include fair, fast, quality, agent, spread, legacy,
# model, model-fast, apex, swift, and adaptive.
# Allow selected, normally credentialed providers to serve virtual models.
# virtual_providers = ["openai"]
# proxy_key = "secret"
```

To opt a configured paid provider into virtual models, add its catalog ID to
the global allowlist:

```toml
[settings]
virtual_providers = ["openai"]
```

This setting does not configure credentials or make a provider globally
available. The provider must already be in Sparrow's configured provider pool
through its normal credential configuration. Keyless providers remain eligible
without being listed, regardless of whether their catalog `billing` value is
`free` or `paid`. An allowlisted provider's models marked `requires_key = true`
remain excluded from virtual routing.

When `virtual_providers` is omitted or empty, virtual models remain keyless-only.

The setting is read when Sparrow creates its provider pool, so restart Sparrow
after changing it. Existing response-cache entries are not invalidated by an
allowlist change; with caching enabled, wait for the configured TTL or clear
the cache before checking route-selection changes. `sparrow doctor` reports
unknown provider IDs in this list as configuration diagnostics.
