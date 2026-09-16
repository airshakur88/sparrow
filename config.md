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
# proxy_key = "secret"
```
