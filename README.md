# Sparrow

Sparrow is an OpenAI-compatible gateway for free and configured LLM providers.

## Install

### Linux

Run in a terminal with `curl`:

```sh
curl -fsSL https://raw.githubusercontent.com/airshakur88/sparrow/main/install.sh | sh
```

The installer installs `uv` when needed, then installs Sparrow as a `uv` tool.
Open a new shell if the `sparrow` command is not immediately available.

### Windows

Run in PowerShell:

```powershell
irm https://raw.githubusercontent.com/airshakur88/sparrow/main/install.ps1 | iex
```

If PowerShell cannot find `sparrow` after installation, open a new PowerShell
window. The installer does not request or store API keys.

Check the installation:

```text
sparrow --version
```

## Configuration

Sparrow starts without configuration when a provider supports keyless access.
For authenticated providers, set environment variables or create:

```text
~/.config/sparrow/config.toml
```

On Windows, the same path is relative to your PowerShell home directory, for
example `$HOME\.config\sparrow\config.toml`.

Minimal example:

```toml
[keys]
GROQ_API_KEY = "your-key"

[settings]
routing = "fair"
cooldown_seconds = 60
```

### Multiple providers

Add one key for each provider you want to use. Sparrow can route between all
configured providers:

```toml
[keys]
GROQ_API_KEY = "groq-key"
CEREBRAS_API_KEY = "cerebras-key"
OPENROUTER_API_KEY = "openrouter-key"

[aliases]
"fast-model" = "groq/llama-3.3-70b-versatile"
"backup-model" = "cerebras/llama3.1-8b"
```

Use `sparrow providers` to see provider names and `sparrow models` to see the
available models. Set `routing = "fair"`, `"fast"`, or `"quality"` under
`[settings]` to control provider selection.

### Multiple API keys

For several accounts or keys from the same provider, declare credential slots.
Each slot refers to an environment variable, so the secret itself stays out
of the configuration file:

```toml
[[credentials]]
provider = "groq"
id = "account-a"
env_var = "GROQ_API_KEY_1"
quota_group = "groq-account-a"
enabled = true

[[credentials]]
provider = "groq"
id = "account-b"
env_var = "GROQ_API_KEY_2"
quota_group = "groq-account-b"
enabled = true
```

Set the values in a `.env` file in the directory where you start Sparrow:

```dotenv
GROQ_API_KEY_1=first-key
GROQ_API_KEY_2=second-key
CEREBRAS_API_KEY=cerebras-key
```

Load the file before starting Sparrow. Linux:

```sh
set -a; . ./.env; set +a
sparrow start --port 8080
```

Windows PowerShell:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)\s*=\s*(.*)\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
sparrow start --port 8080
```

Keep `.env` private and add it to `.gitignore`.

Use a distinct `id` and `quota_group` for each account. Sparrow tracks their
health and cooldowns independently, then selects an available credential.

Environment variables take precedence over values in `config.toml`. Never
commit real credentials to the repository. See [`config.md`](config.md) for
provider keys, aliases, and multiple credential slots.

## Usage

```sh
sparrow providers
sparrow models
sparrow ask "Explain how DNS works"
sparrow start --port 8080
```

The local HTTP gateway is available at `http://127.0.0.1:8080` by default.

## MCP

To run Sparrow as an MCP server over stdio:

```sh
sparrow mcp
```

## Catalog

The built-in catalog currently contains 21 providers and 180 models (167
enabled by default). Keyless providers can work without credentials; other
providers require their corresponding API key.

| Provider | Available models |
|---|---|
| `pollinations` | `openai`, `openai-fast`, `gpt-oss` |
| `llm7` | `default`, `fast`, `codestral-latest`, `DeepSeek-V4-Flash-0731`, `minimax-m2.7`, `gemma4:31b`, `mistral-Nemo-Instruct-2407`, `gemini-3.1-flash-lite` |
| `ovh` | `Meta-Llama-3_3-70B-Instruct`, `Mistral-Small-3.2-24B-Instruct-2506`, `Mistral-Nemo-Instruct-2407`, `Qwen2.5-VL-72B-Instruct`, `Mistral-7B-Instruct-v0.3`, `Qwen3.5-397B-A17B`, `gpt-oss-120b`, `Qwen3.6-27B`, `Qwen3.5-9B`, `qwen3.6-27b`, `qwen3.5-397b-a17b`, `qwen3.5-9b`, `qwen3-coder-30b-a3b-instruct`, `qwen2.5-vl-72b-instruct`, `mistral-small-3.2-24b-instruct`, `mistral-7b-instruct-v0.3`, `qwen3-32b`, `meta-llama-3_3-70b-instruct` |
| `kilo` | `openrouter/free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `poolside/laguna-s-2.1:free`, `kilo-auto/free`, `stepfun/step-3.7-flash:free`, `nvidia/nemotron-3-super-120b-a12b:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `inclusionai/ling-3.0-flash-fin:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3.5-lightning:free` |
| `gemini` | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemma-4-31b-it`, `gemma-4-26b-a4b-it` |
| `groq` | `qwen/qwen3.8-27b`, `qwen/qwen3.6-27b`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `groq/compound`, `groq/compound-mini`, `meta-llama/llama-prompt-guard-2-86m`, `meta-llama/llama-prompt-guard-2-22m` |
| `nvidia` | `deepseek-ai/deepseek-v4-pro-0813`, `deepseek-ai/deepseek-v4-flash-0731`, `moonshotai/kimi-k3`, `moonshotai/kimi-k2.6`, `nvidia/nemotron-3-ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, `poolside/laguna-xs-2.1`, `poolside/laguna-s-2.1`, `01-ai/yi-large`, `openai/gpt-oss-20b`, `writer/palmyra-fin-70b-32k`, `nvidia/llama3-chatqa-1.5-70b`, `meta/llama-3.1-70b-instruct`, `qwen/qwen3-coder-30b-a3b-instruct`, `mistralai/mistral-large-2-instruct` |
| `openrouter` | `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `inclusionai/ling-3.0-flash-fin:free`, `inclusionai/ling-3.0-flash-sante:free`, `nex-agi/nex-n2.5-pro:free`, `thinkingmachines/inkling:free`, `thinkingmachines/inkling-small:free`, `poolside/laguna-s-2.1:free`, `cohere/north-mini-code:free`, `google/gemma-4-31b-it:free`, `openai/gpt-oss-120b:free`, `openai/gpt-oss-20b:free`, `qwen/qwen3-coder-30b-a3b-instruct:free`, `qwen/qwen3-vl-8b-thinking:free`, `z-ai/glm-4.5-air:free` |
| `ollama` | `deepseek-v4-pro:0813`, `deepseek-v4-flash:0731`, `deepseek-v4-pro`, `deepseek-v4-flash`, `minimax-m3`, `kimi-k3`, `gpt-oss:120b`, `gpt-oss:20b`, `gpt-oss-120b`, `gpt-oss-20b`, `nemotron-3-ultra`, `qwen3.5-397b` |
| `github_models` | `gpt-5`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `o4-mini`, `deepseek-r1`, `llama-4-scout-17b-16e-instruct`, `llama-3.3-70b-instruct`, `mistral-small-3.1`, `Phi-4`, `Mistral-large-2411`, `AI21-Jamba-1.5-Large` |
| `kilo_code` | `tencent/hy3:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `stepfun/step-3.7-flash:free`, `nvidia/nemotron-3.5-lightning:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free`, `cohere/north-mini-code:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-super-120b-a12b:free` |
| `modelscope` | `Qwen/Qwen3.8-Flash-Next`, `Qwen/Qwen3.8-27B`, `ZhipuAI/GLM-5.2`, `deepseek-ai/DeepSeek-V4-Pro`, `deepseek-ai/DeepSeek-V4-Pro-0813`, `deepseek-ai/DeepSeek-V4-Flash`, `deepseek-ai/DeepSeek-V4-Flash-0731`, `MiniMax/MiniMax-M3`, `Tencent-Hunyuan/Hy3`, `stepfun-ai/Step-3.7-Flash`, `Qwen/Qwen3.5-397B-A17B` |
| `cloudflare` | `@cf/qwen/qwen3.8-27b`, `@cf/moonshotai/kimi-k2.7-code`, `@cf/google/gemma-4-26b-a4b-it`, `@cf/zai-org/glm-4.7-flash`, `@cf/openai/gpt-oss-120b`, `@cf/nvidia/nemotron-3-120b-a12b`, `@cf/meta/llama-4-scout-17b-16e-instruct`, `@cf/mistralai/mistral-small-3.1-24b-instruct`, `@cf/deepseek-ai/deepseek-r1-distill-qwen-32b`, `@cf/openai/gpt-oss-20b` |
| `cohere` | `command-a-111b`, `command-a-reasoning`, `command-a-218b`, `command-r`, `command-r7b`, `command-a-vision`, `command-r7b-arabic`, `aya-expanse-32b`, `command-a-translate`, `aya-vision-32b` |
| `z_ai` | `glm-4.7`, `glm-4.6`, `glm-4.5-air` |
| `chutes` | `deepseek-ai/DeepSeek-R1`, `meta-llama/Meta-Llama-3.1-70B-Instruct` |
| `agnes` | `agnes-2.0-flash`, `agnes-1.5-flash`, `agnes-image-2.0-flash`, `agnes-image-2.1-flash`, `agnes-video-v2.0` |
| `aion` | `aion-labs/aion-2.0`, `aion-labs/aion-3.0`, `aion-labs/aion-3.0-mini`, `aion-labs/aion-rp-llama-3.1-8b` |
| `opencode` | `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`, `big-pickle`, `mimo-v2.5-free`, `ling-3.0-flash-fin-free`, `muse-spark-1.3-contributor-free` |
| `bai` | `GLM-5.3-Flash`, `Qwen3.8-Flash`, `MiMo-V2.5`, `Hy3` |
| `free_ai` | `dynamic-catalog` |

The catalog can change as providers update their APIs. Query the live local
catalog with `sparrow models --json`, or filter it with
`sparrow models --providers groq,openrouter`.

## Help

```sh
sparrow --help
sparrow doctor
```
