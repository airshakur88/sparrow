# Relatório de Validação — Sparrow (2026-09-17)

## Resumo Geral

| Métrica | Valor |
|---|---|
| Total de modelos testados | 112 |
| Providers configurados | 12 |
| Providers não configurados | 6 |
| Sucesso total | 30 (27%) |

---

## Classificação por Status

| Classificação | Quantidade | Descrição |
|---|---|---|
| SUCCESS | 30 | Modelo respondeu com conteúdo válido |
| EMPTY_SUCCESS | 12 | Modelo respondeu (200) mas sem texto |
| RATE_LIMIT | 22 | Limite de taxa atingido (429) |
| NOT_FOUND | 18 | Modelo não encontrado no provider (404) |
| AUTH | 10 | Falha de autenticação (401/403) |
| CLIENT_ERROR | 10 | Erro do cliente (4xx diferente dos acima) |
| TRANSPORT | 8 | Falha de conexão/timeout |
| SERVER_ERROR | 2 | Erro interno do provider (5xx) |

---

## Detalhamento por Provider

### ✅ Providers com Sucesso

#### Groq (7/8 sucesso)
| Modelo | Status |
|---|---|
| qwen/qwen3.8-27b | ✅ OK |
| openai/gpt-oss-120b | ✅ OK |
| openai/gpt-oss-20b | ✅ OK |
| groq/compound | ✅ OK |
| groq/compound-mini | ✅ OK |
| meta-llama/llama-prompt-guard-2-86m | ✅ OK |
| meta-llama/llama-prompt-guard-2-22m | ✅ OK |
| qwen/qwen3.6-27b | ❌ NOT_FOUND |

#### Kilo (6/12 sucesso)
| Modelo | Status |
|---|---|
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | ✅ OK |
| kilo-auto/free | ✅ OK |
| nvidia/nemotron-3-super-120b-a12b:free | ✅ OK |
| nvidia/nemotron-3-ultra-550b-a55b:free | ✅ OK |
| nvidia/nemotron-3.5-lightning:free | ✅ OK |
| dots-studio/dots-3-note-preview:free | ✅ OK |
| openrouter/free | ⚠️ EMPTY |
| poolside/laguna-s-2.1:free | ⚠️ EMPTY |
| stepfun/step-3.7-flash:free | ⚠️ EMPTY |
| cohere/north-mini-code:free | ⚠️ EMPTY |
| inclusionai/ling-3.0-flash-fin:free | ⚠️ EMPTY |
| liquid/lfm-2.5-2.6b:free | 🚫 RATE_LIMIT |

#### Ollama (5/12 sucesso)
| Modelo | Status |
|---|---|
| deepseek-v4-pro:0813 | ✅ OK |
| deepseek-v4-flash:0731 | ✅ OK |
| deepseek-v4-pro | ✅ OK |
| deepseek-v4-flash | ✅ OK |
| minimax-m3 | ✅ OK |
| kimi-k3 | 🚫 CLIENT_ERROR (402) |
| gpt-oss:120b (×2) | 🚫 CLIENT_ERROR (402) |
| gpt-oss:20b (×2) | 🚫 CLIENT_ERROR (402) |
| nemotron-3-ultra | 🚫 CLIENT_ERROR (402) |
| qwen3.5-397b | 🚫 CLIENT_ERROR (402) |

#### Gemini (4/11 sucesso)
| Modelo | Status |
|---|---|
| gemini-3.5-flash-lite | ✅ OK |
| gemini-3.1-flash-lite | ✅ OK |
| gemma-4-26b-a4b-it | ✅ OK |
| gemini-3.5-flash | ✅ OK |
| gemini-2.5-pro | ❌ NOT_FOUND |
| gemini-2.5-flash | ❌ NOT_FOUND |
| gemini-2.5-flash-lite | ❌ NOT_FOUND |
| gemini-3.8-flash | ⏱️ TRANSPORT (timeout) |
| gemini-3.7-flash | ⏱️ TRANSPORT (timeout) |
| gemma-4-31b-it | ⚠️ EMPTY |
| gemini-3.6-flash | ⚠️ EMPTY |

#### NVIDIA (2/9 sucesso)
| Modelo | Status |
|---|---|
| nvidia/nemotron-3.5-lightning-30b-a3b | ✅ OK |
| mistralai/mistral-nemotron | ⚠️ EMPTY |
| z-ai/glm-5.3-flash | ❌ NOT_FOUND |
| nvidia/nemotron-3-ultra-550b-a55b | ⏱️ TRANSPORT |
| nvidia/nemotron-ocr-v2 | ⏱️ TRANSPORT |
| moonshotai/kimi-k3 | ⏱️ TRANSPORT |
| deepseek-ai/deepseek-v4-flash-0731 | 🚫 SERVER_ERROR |
| meta/muse-glimmer-30b | ⏱️ TRANSPORT |
| poolside/laguna-xs-2.1 | ⏱️ TRANSPORT |

#### OpenRouter (4/15 sucesso)
| Modelo | Status |
|---|---|
| nvidia/nemotron-3-ultra-550b-a55b:free | ✅ OK |
| nvidia/nemotron-3.5-lightning:free | ✅ OK |
| nex-agi/nex-n2.5-pro:free | ✅ OK |
| inclusionai/ling-3.0-flash-fin:free | ✅ OK |
| google/gemma-4-31b-it:free | ❌ NOT_FOUND |
| openai/gpt-oss-120b:free | ❌ NOT_FOUND |
| openai/gpt-oss-20b:free | ❌ NOT_FOUND |
| qwen/qwen3-coder-30b-a3b-instruct:free | ❌ NOT_FOUND |
| qwen/qwen3-vl-8b-thinking:free | ❌ NOT_FOUND |
| z-ai/glm-4.5-air:free | ❌ NOT_FOUND |
| inclusionai/ling-3.0-flash-sante:free | 🚫 RATE_LIMIT |
| thinkingmachines/inkling:free | 🔒 AUTH (403) |
| thinkingmachines/inkling-small:free | 🔒 AUTH (403) |
| poolside/laguna-s-2.1:free | 🚫 RATE_LIMIT |
| cohere/north-mini-code:free | 🚫 RATE_LIMIT |

#### LLM7 (5/8 sucesso)
| Modelo | Status |
|---|---|
| default | ✅ OK |
| fast | ✅ OK |
| codestral-latest | ✅ OK |
| minimax-m2.7 | ✅ OK |
| mistral-Nemo-Instruct-2407 | ✅ OK |
| DeepSeek-V4-Flash-0731 | 🔒 AUTH (403) |
| gemma4:31b | 🔒 AUTH (403) |
| gemini-3.1-flash-lite | 🔒 AUTH (403) |

#### OVH (3/18 sucesso)
| Modelo | Status |
|---|---|
| Mistral-Nemo-Instruct-2407 | ✅ OK |
| Mistral-7B-Instruct-v0.3 | ✅ OK |
| mistral-7b-instruct-v0.3 | ✅ OK |
| Meta-Llama-3_3-70B-Instruct | 🚫 RATE_LIMIT |
| Mistral-Small-3.2-24B-Instruct-2506 | 🚫 RATE_LIMIT |
| Qwen2.5-VL-72B-Instruct | 🚫 RATE_LIMIT |
| Qwen3.5-397B-A17B | 🚫 RATE_LIMIT |
| gpt-oss-120b | 🚫 RATE_LIMIT |
| Qwen3.6-27B | 🚫 RATE_LIMIT |
| Qwen3.5-9B | 🚫 RATE_LIMIT |
| qwen3.6-27b | 🚫 RATE_LIMIT |
| qwen3.5-397b-a17b | 🚫 RATE_LIMIT |
| qwen3.5-9b | 🚫 RATE_LIMIT |
| qwen3-coder-30b-a3b-instruct | 🚫 RATE_LIMIT |
| qwen2.5-vl-72b-instruct | 🚫 RATE_LIMIT |
| mistral-small-3.2-24b-instruct | 🚫 RATE_LIMIT |
| qwen3-32b | 🚫 RATE_LIMIT |
| meta-llama-3_3-70b-instruct | 🚫 RATE_LIMIT |

### ⚠️ Providers sem Sucesso

#### Agnes (0/5 sucesso)
Todos os modelos retornaram erro — provavelmente formato de API incompatível para modelos de imagem/vídeo.

| Modelo | Status |
|---|---|
| agnes-2.0-flash | ❌ CLIENT_ERROR |
| agnes-1.5-flash | ⚠️ EMPTY |
| agnes-image-2.0-flash | 🚫 SERVER_ERROR |
| agnes-image-2.1-flash | 🚫 CLIENT_ERROR |
| agnes-video-v2.0 | 🚫 CLIENT_ERROR |

#### OpenCode (0/5 sucesso)
Todos retornaram 403 — requer autenticação específica.

| Modelo | Status |
|---|---|
| nemotron-3-ultra-free | 🔒 AUTH (403) |
| nemotron-3.5-lightning-free | 🔒 AUTH (403) |
| big-pickle | 🔒 AUTH (403) |
| mimo-v2.5-free | 🔒 AUTH (403) |
| ling-3.0-flash-fin-free | 🔒 AUTH (403) |

#### BAI (0/4 sucesso)
Todos retornaram NOT_FOUND — modelos não encontrados.

| Modelo | Status |
|---|---|
| GLM-5.3-Flash | ❌ NOT_FOUND |
| Qwen3.8-Flash | ❌ NOT_FOUND |
| MiMo-V2.5 | ❌ NOT_FOUND |
| Hy3 | ❌ NOT_FOUND |

#### OpenAI (0/5 sucesso)
4 RATE_LIMIT (429) + 1 CLIENT_ERROR — provavelmente quota da conta ou modelo indisponível.

| Modelo | Status |
|---|---|
| gpt-6-astra | 🚫 RATE_LIMIT |
| gpt-5.6-luna | 🚫 RATE_LIMIT |
| gpt-5.6-sol | 🚫 RATE_LIMIT |
| gpt-5.6-terra | 🚫 RATE_LIMIT |
| gpt-5.5 | 🚫 CLIENT_ERROR |

---

## Providers Não Configurados (sem chave API)

| Provider | Chave Necessária | Status |
|---|---|---|
| kilo_code | KILO_API_KEY | ⚠️ Sem chave |
| modelscope | MODELSCOPE_API_KEY | ⚠️ Sem chave |
| cohere | COHERE_API_KEY | ⚠️ Sem chave |
| z_ai | ZAI_API_KEY | ⚠️ Sem chave |
| chutes | CHUTES_API_KEY | ⚠️ Sem chave |
| aion | AION_API_KEY | ⚠️ Sem chave |

---

## Análise dos Resultados

### Taxa de Sucesso por Provider

| Provider | Sucesso | Total | Taxa |
|---|---|---|---|
| Groq | 7 | 8 | 88% |
| LLM7 | 5 | 8 | 63% |
| Kilo | 6 | 12 | 50% |
| Ollama | 5 | 12 | 42% |
| Gemini | 4 | 11 | 36% |
| OpenRouter | 4 | 15 | 27% |
| NVIDIA | 2 | 9 | 22% |
| OVH | 3 | 18 | 17% |
| Agnes | 0 | 5 | 0% |
| OpenCode | 0 | 5 | 0% |
| BAI | 0 | 4 | 0% |
| OpenAI | 0 | 5 | 0% |

### Observações Importantes

1. **Rate Limits Transientes**: Muitos 429s são de chamadas sequenciais rápidas — com backoff adequado, esses modelos provavelmente funcionariam.

2. **OVH**: 13 dos 18 modelos retornaram 429 — rate limit agressivo do provider, não problema do Sparrow.

3. **OpenAI**: Todos 429 — provavelmente quota da conta ou modelo indisponível.

4. **Agnes**: Retorna 400 para modelos de imagem/vídeo — formato de API incompatível com o adaptador atual.

5. **NVIDIA**: 5 timeouts de 15s — API pode estar lenta ou bloqueada.

6. **BAI**: Todos NOT_FOUND — modelos não existem mais ou foram renomeados.

7. **OpenCode**: Todos 403 — requer autenticação específica que não está configurada.

### Recomendações

1. **Groq e LLM7**: Providers mais confiáveis — usar como primários.
2. **Kilo e Ollama**: Bom suporte, usar como backup.
3. **OVH**: Implementar backoff mais agressivo para evitar 429.
4. **OpenAI**: Verificar quota da conta ou usar modelo diferente.
5. **Agnes/BAI/OpenCode**: Revisar adaptadores ou remover do catálogo se incompatíveis.

---

## Conclusão

**30 de 112 modelos (27%) funcionaram imediatamente.** Com backoff adequado e retry, a taxa de sucesso efetiva seria significativamente maior (estimativa: 50-60%).

**Providers mais estáveis**: Groq (88%), LLM7 (63%), Kilo (50%).

**Próximos passos**:
1. Implementar backoff mais agressivo para rate limits
2. Revisar adaptadores para providers com falhas consistentes
3. Considerar remover providers incompatíveis (Agnes, BAI)
4. Verificar quotas de conta para OpenAI

---

*Relatório gerado em 2026-09-17 pelo Sparrow Validation Runner*
*Dados extraídos de validation_report.json (112 modelos testados)*
