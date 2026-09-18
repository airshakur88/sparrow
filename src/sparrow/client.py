                                                        

                                                   

                                                                              
                                                          
                                                                            
                                                                           
                                                                         

                                                                            
                                                                    
   

from __future__ import annotations

import json
import random
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from ._version import __version__
from .errors import ProviderHTTPError
from .models import EmbedReply, Provider, Reply, TranscribeReply
from .plugins import registered_adapters

Message = dict[str, str]

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
                                                                             
                                                   
_THINKING_HINTS = (
    "glm-4.7",
    "-r1",
    "reasoning",
    "thinking",
    "magistral",
    "deepseek-r1",
    "nemotron",
    "gpt-oss",                                                                     
    "gemini-3.6",
    "gemini-3.7",
)
_THINKING_FLOOR = 4096                                                                


def _is_thinking(model: str) -> bool:
    m = model.lower()
    return any(h in m for h in _THINKING_HINTS)


_OPENCODE_USER_AGENT = f"opencode/sparrow/{__version__}"


def _opencode_headers(session_id: str | None = None) -> dict[str, str]:
                                                                          
    sid = session_id or str(uuid.uuid4())
    return {
        "User-Agent": _OPENCODE_USER_AGENT,
        "x-opencode-project": "sparrow",
        "x-opencode-session": sid,
        "x-opencode-request": str(uuid.uuid4()),
        "x-opencode-client": "sparrow",
    }


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _content_text(content) -> str:
                                                                               
                                                                               
                                                          
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


@dataclass
class HTTPResult:
    status: int
    body: dict
    text: str
    headers: dict | None = None


PostFn = Callable[[str, dict, dict, float], HTTPResult]

StreamPostFn = Callable[
    [str, dict, dict, float],
    "tuple[int, Iterable[str]] | tuple[int, dict, Iterable[str]]",
]

_USER_AGENT = f"sparrow/{__version__} (+https://github.com/airshakur88/sparrow)"

_CONNECT_TIMEOUT = 10.0                                                                
                                                                                 
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024          
                                                                           
                                                                       
_MAX_STREAM_LINE_CHARS = 1 * 1024 * 1024
_MAX_TRANSPORT_ATTEMPTS = 2
_RETRY_BACKOFF_S = 0.2
_shared = None                                                                   
_shared_lock = threading.Lock()


def _client():
                                                                                  
                                                                              
                                                                
    global _shared
    if _shared is None:                                              
        with _shared_lock:
            if _shared is None:                                           
                import atexit

                import httpx

                _shared = httpx.Client(
                    headers={"User-Agent": _USER_AGENT},
                    limits=httpx.Limits(
                        max_keepalive_connections=20, max_connections=100, keepalive_expiry=30.0
                    ),
                                                                                      
                                                                                      
                                                                                       
                                                                          
                    follow_redirects=False,
                )
                atexit.register(_shared.close)
    return _shared


def _timeout(timeout: float):
    import httpx

    return httpx.Timeout(timeout, connect=min(_CONNECT_TIMEOUT, timeout))


def default_post(
    url: str,
    headers: dict,
    json_body: dict,
    timeout: float,
    *,
    max_attempts: int | None = None,
) -> HTTPResult:
                                                     

                                                                                   
                                                                                     
                                                                                      
                                                                                      
                  
    import httpx

    deadline = time.monotonic() + timeout
    attempt_limit = (
        _MAX_TRANSPORT_ATTEMPTS if max_attempts is None else max(1, int(max_attempts))
    )
    last_exc: httpx.HTTPError | None = None
    last_result: HTTPResult | None = None
    for attempt in range(attempt_limit):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = _post_once(url, headers, json_body, remaining, deadline)
        except httpx.HTTPError as exc:
            last_exc = exc
            if not _retryable_transport_error(exc, httpx):
                raise
            if attempt + 1 >= attempt_limit:
                raise
            delay = _retry_delay(None, attempt, deadline)
            if delay is None:
                raise
            time.sleep(delay)
            continue
        last_result = result
        if _retryable(result.status) and attempt + 1 < attempt_limit:
            delay = _retry_delay(result, attempt, deadline)
            if delay is not None:
                time.sleep(delay)
                continue
        return result
    if last_exc is not None:                                           
        raise last_exc
    if last_result is not None:
        return last_result
    raise ProviderHTTPError(502, "transport retry loop exhausted", retryable=True)


def _post_once(
    url: str, headers: dict, json_body: dict, timeout: float, deadline: float
) -> HTTPResult:
    with _client().stream(
        "POST", url, headers=headers, json=json_body, timeout=_timeout(timeout)
    ) as resp:
        raw, text = _read_capped_response(resp.iter_bytes(), deadline, timeout)
        status = resp.status_code
        headers = dict(getattr(resp, "headers", {}) or {})
    return _json_result(status, raw, text, headers=headers)


def _read_capped_response(chunks, deadline: float, timeout: float) -> tuple[bytes, str]:
    out: list[bytes] = []
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise ProviderHTTPError(
                502, f"upstream response exceeded {_MAX_RESPONSE_BYTES} bytes", retryable=True
            )
        if time.monotonic() > deadline:
            raise ProviderHTTPError(504, f"upstream exceeded {timeout:.0f}s deadline", retryable=True)
        out.append(chunk)
    raw = b"".join(out)
    return raw, raw.decode("utf-8", "replace")


def _json_result(status: int, raw: bytes, text: str, headers: dict | None = None) -> HTTPResult:
    try:
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            body = {}
    except (json.JSONDecodeError, ValueError):
        body = {}
    return HTTPResult(status=status, body=body, text=text, headers=headers)


def _header(headers: dict | None, name: str) -> str | None:
    if not headers:
        return None
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    low = name.lower()
    for key, value in headers.items():
        if str(key).lower() == low:
            return str(value)
    return None


def _retry_after_seconds(headers: dict | None) -> float | None:
    raw = _header(headers, "Retry-After")
    if raw:
        raw = raw.strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except (TypeError, ValueError, OSError):
            pass

                                                                      
                                                                           
                                                                               
    reset = _header(headers, "RateLimit-Reset")
    if reset:
        try:
            return max(0.0, float(reset.strip()))
        except ValueError:
            pass
    legacy = _header(headers, "X-RateLimit-Reset")
    if legacy:
        try:
            value = float(legacy.strip())
        except ValueError:
            return None
        if value >= 1_000_000_000:
            return max(0.0, value - time.time())
        return max(0.0, value)
    return None


def _retry_delay(result: HTTPResult | None, attempt: int, deadline: float) -> float | None:
    return _retry_delay_monotonic(result, attempt, deadline, time.monotonic)


def _retry_delay_monotonic(
    result: HTTPResult | None, attempt: int, deadline: float, now
) -> float | None:
    base = _retry_after_seconds(result.headers if result is not None else None)
    return _retry_delay_seconds(base, attempt, deadline, now)


def _retry_delay_seconds(
    retry_after: float | None, attempt: int, deadline: float, now
) -> float | None:
                                                                               
    base = retry_after
    if base is None:
        base = _RETRY_BACKOFF_S * (attempt + 1)
    jitter = random.uniform(0.0, min(0.1, base * 0.1)) if base > 0 else 0.0
    delay = base + jitter
    return delay if now() + delay < deadline else None


def _retryable_transport_error(exc, httpx) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))


def _retryable_transport_exception(exc: Exception) -> bool:
    import httpx

    return _retryable_transport_error(exc, httpx)


def _is_local_pool_timeout(exc: Exception) -> bool:
                                                                                  
    import httpx

    return isinstance(exc, httpx.PoolTimeout)


class _StreamLines:
                                                                              
                                                                                  
                                                                                 
                                         

    def __init__(
        self,
        cm,
        resp,
        deadline: float | None = None,
        max_line_chars: int = _MAX_STREAM_LINE_CHARS,
    ):
        self._cm, self._resp = cm, resp
        self._closed = False
        self._deadline = deadline                                                
        self._max_line_chars = max_line_chars

    def __iter__(self) -> Iterator[str]:
                                                                                    
                                                                                 
                                                                                     
                                                                                   
                                                                              
        parts: list[str] = []
        buffered_chars = 0
        try:
            for chunk in self._resp.iter_text():
                if self._deadline is not None and time.monotonic() > self._deadline:
                    raise ProviderHTTPError(
                        504, "upstream exceeded stream deadline", retryable=True
                    )
                if not chunk:
                    continue
                start = 0
                while True:
                    newline = chunk.find("\n", start)
                    end = len(chunk) if newline < 0 else newline
                    segment_chars = end - start
                    if segment_chars > self._max_line_chars - buffered_chars:
                        raise ProviderHTTPError(
                            502,
                            f"upstream stream line exceeded {self._max_line_chars} characters",
                            retryable=True,
                        )
                    if segment_chars:
                        parts.append(chunk[start:end])
                        buffered_chars += segment_chars
                    if newline < 0:
                        break
                    line = "".join(parts).rstrip("\r")
                    parts = []
                    buffered_chars = 0
                    start = newline + 1
                    yield line
            if parts:
                yield "".join(parts).rstrip("\r")
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._cm.__exit__(None, None, None)                                       
        except Exception:                                      
            pass


def default_stream_post(url: str, headers: dict, json_body: dict, timeout: float):
                                                                               
    deadline = time.monotonic() + timeout
    cm = _client().stream("POST", url, headers=headers, json=json_body, timeout=_timeout(timeout))
    try:
        resp = cm.__enter__()
    except BaseException:                                                      
        cm.__exit__(*sys.exc_info())
        raise
    return (
        resp.status_code,
        dict(getattr(resp, "headers", {}) or {}),
        _StreamLines(cm, resp, deadline=deadline),
    )


def stream_call(
    provider: Provider,
    model: str,
    messages: list[Message],
    *,
    api_key: str | None,
    env: dict[str, str],
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: float = 90.0,
    stream_post: StreamPostFn = default_stream_post,
    usage_callback: Callable[[dict], None] | None = None,
) -> Iterator[str]:
                                                           

                                                                                
                                                                             
                                                                                  
       
    base_url = provider.base_url
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.id == "opencode":
        headers.update(_opencode_headers())
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    opened = stream_post(url, headers, body, timeout)
    if len(opened) == 2:
        status, line_iter = opened
        response_headers = None
    else:
        status, response_headers, line_iter = opened
    close = getattr(line_iter, "close", lambda: None)
    if status != 200:
                                                                                  
                                                                                  
        parts: list[str] = []
        total = 0
        try:
            for chunk in line_iter:
                parts.append(chunk)
                total += len(chunk)
                if total >= 500:
                    break
        except Exception:                                                       
            pass
        finally:
            close()
        err_body = "".join(parts)[:500]
        try:
            parsed_error = json.loads(err_body)
        except (json.JSONDecodeError, ValueError, RecursionError):
            parsed_error = {}
        raise _provider_http_error(
            HTTPResult(
                status=status,
                body=parsed_error if isinstance(parsed_error, dict) else {},
                text=err_body or f"HTTP {status}",
                headers=response_headers,
            )
        )
    done = False
    try:
        for line in line_iter:
            if not line:
                continue
            if line.startswith("data:"):
                line = line[len("data:") :]
            line = line.strip()
            if not line or line == "[DONE]":
                if line == "[DONE]":
                    done = True
                    break
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            error = obj.get("error")
            if isinstance(error, dict):
                status = error.get("code") or error.get("status") or 502
                try:
                    status = int(status)
                except (TypeError, ValueError):
                    status = 502
                raise ProviderHTTPError(
                    status,
                    str(error.get("message") or error),
                    retryable=_retryable(status),
                )
            usage = obj.get("usage")
            if isinstance(usage, dict) and usage_callback is not None:
                usage_callback(usage)
            choices = obj.get("choices") or [{}]
            finish_reason = choices[0].get("finish_reason") if choices else None
            if finish_reason in {"error", "failed"}:
                raise ProviderHTTPError(
                    502,
                    f"stream finished with {finish_reason}",
                    retryable=True,
                )
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                yield delta
        if not done:
            raise ProviderHTTPError(
                502,
                "stream ended before [DONE]",
                retryable=True,
            )
    finally:
        close()


def _retryable(status: int) -> bool:
                                                                     
                                                                               
                                                                   
    return status == 429 or status == 408 or 500 <= status < 600


def _err_message(result: HTTPResult) -> str:
    err = result.body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)
    if isinstance(err, str):
        return err
    return (result.text or "").strip()[:200] or "no body"


def _provider_http_error(result: HTTPResult) -> ProviderHTTPError:
                                                                           
    error = result.body.get("error") if isinstance(result.body, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    if not isinstance(error_type, str) or len(error_type) > 128:
        error_type = None
    return ProviderHTTPError(
        result.status,
        _err_message(result),
        retryable=_retryable(result.status),
        retry_after=_retry_after_seconds(result.headers),
        error_type=error_type,
    )


def _to_gemini_contents(messages: list[Message]) -> tuple[dict | None, list[dict]]:
                                                                         
    system: str | None = None
    contents: list[dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        text = _content_text(msg.get("content"))
        if role == "system":
            system = f"{system}\n{text}" if system else text
            continue
        gem_role = "model" if role == "assistant" else "user"
        contents.append({"role": gem_role, "parts": [{"text": text}]})
    system_instruction = {"parts": [{"text": system}]} if system else None
    return system_instruction, contents


def _gemini_generation_config(model: str, max_tokens: int, temperature: float) -> dict:
                                                                            

                                                                         
                                                                 
       
    config: dict = {"maxOutputTokens": max_tokens}
    if not model.startswith(("gemini-3.6-", "gemini-3.7-")):
        config["temperature"] = temperature
    return config


def _adapter_openai(
    provider,
    model,
    messages,
    *,
    api_key,
    env,
    max_tokens,
    temperature,
    timeout,
    tools,
    tool_choice,
    response_format,
    post,
) -> Reply:
    return _call_openai(
        provider,
        model,
        messages,
        api_key=api_key,
        env=env,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        tools=tools,
        tool_choice=tool_choice,
        response_format=response_format,
        post=post,
    )


def _adapter_gemini(
    provider,
    model,
    messages,
    *,
    api_key,
    env,
    max_tokens,
    temperature,
    timeout,
    tools,
    tool_choice,
    response_format,
    post,
) -> Reply:
                                                                              
                                                                
    if tools:
        raise ProviderHTTPError(400, "gemini adapter does not support tools", retryable=True)
    if response_format is not None:
        raise ProviderHTTPError(
            400,
            "gemini adapter does not support OpenAI response_format",
            retryable=True,
        )
    return _call_gemini(
        provider,
        model,
        messages,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        post=post,
    )


                                                                 
                                                                                 
_BUILTIN_ADAPTERS = {
    "openai": _adapter_openai,
    "gemini": _adapter_gemini,
}


def _resolve_adapter(name: str):
    custom = registered_adapters()
    if name in custom:
        return custom[name]
    return _BUILTIN_ADAPTERS.get(name, _adapter_openai)


def call(
    provider: Provider,
    model: str,
    messages: list[Message],
    *,
    api_key: str | None,
    env: dict[str, str],
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: float = 90.0,
    tools: list | None = None,
    tool_choice=None,
    response_format=None,
    enforce_thinking_floor: bool = True,
    post: PostFn = default_post,
) -> Reply:
                                                                          

                                                                         
                                                                              
                                                     
                                                                               
       
    if enforce_thinking_floor and _is_thinking(model) and max_tokens < _THINKING_FLOOR:
                                                                              
                                          
        max_tokens = _THINKING_FLOOR
    adapter = _resolve_adapter(provider.adapter)
    kwargs = {
        "api_key": api_key,
        "env": env,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
        "tools": tools,
        "tool_choice": tool_choice,
        "post": post,
    }
                                                                                    
                                                                                  
                                         
    if response_format is not None or adapter in _BUILTIN_ADAPTERS.values():
        kwargs["response_format"] = response_format
    return adapter(
        provider,
        model,
        messages,
        **kwargs,
    )


def _call_openai(
    provider: Provider,
    model: str,
    messages: list[Message],
    *,
    api_key: str | None,
    env: dict[str, str],
    max_tokens: int,
    temperature: float,
    timeout: float,
    tools: list | None = None,
    tool_choice=None,
    response_format=None,
    post: PostFn,
) -> Reply:
    base_url = provider.base_url

    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.id == "opencode":
        headers.update(_opencode_headers())
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:                                                                       
        body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
    if response_format is not None:
        body["response_format"] = response_format
    result = post(url, headers, body, timeout)
    if result.status != 200:
        raise _provider_http_error(result)

    choices = result.body.get("choices") or []
    if not choices:
        raise ProviderHTTPError(502, "no choices in response", retryable=True)
    if not isinstance(choices[0], dict):
        raise ProviderHTTPError(502, "malformed choice in response", retryable=True)
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise ProviderHTTPError(502, "malformed message in response", retryable=True)
    text = _strip_think(_content_text(message.get("content")))
    usage = result.body.get("usage") or {}
    return Reply(
        text=text,
        provider_id=provider.id,
        model=model,
        raw=result.body,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        message=message if isinstance(message, dict) else None,
    )


def embed(
    provider: Provider,
    model: str,
    inputs: list[str],
    *,
    api_key: str | None,
    env: dict[str, str],
    timeout: float = 90.0,
    post: PostFn = default_post,
) -> EmbedReply:
                                                                        
    base_url = provider.base_url
    url = f"{base_url}/embeddings"
    headers = {"Content-Type": "application/json"}
    if provider.id == "opencode":
        headers.update(_opencode_headers())
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "input": inputs, "encoding_format": "float"}
    if provider.id == "nvidia":
                                                                          
                                                                         
                                                                              
        body["input_type"] = "query"
    result = post(url, headers, body, timeout)
    if result.status != 200:
        raise _provider_http_error(result)
    data = result.body.get("data") or []
    if not data:
        raise ProviderHTTPError(502, "no embeddings in response", retryable=True)
    vectors = [row.get("embedding") or [] for row in data]
    if not all(vectors):
        raise ProviderHTTPError(502, "empty embedding vector", retryable=True)
    usage = result.body.get("usage") or {}
    return EmbedReply(
        vectors=vectors,
        provider_id=provider.id,
        model=model,
        prompt_tokens=usage.get("prompt_tokens"),
    )


                                                                                          
                                                                                              
MultipartPostFn = Callable[[str, dict, dict, dict, float], HTTPResult]


def default_multipart_post(
    url: str, headers: dict, files: dict, data: dict, timeout: float
) -> HTTPResult:
                                                                                            
                                                                                                
                                                                                       
                                                                                            
                                      
    import httpx

    deadline = time.monotonic() + timeout
    last_exc: httpx.HTTPError | None = None
    last_result: HTTPResult | None = None
    for attempt in range(_MAX_TRANSPORT_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = _multipart_once(url, headers, files, data, remaining, deadline)
        except httpx.HTTPError as exc:
            last_exc = exc
            if not _retryable_transport_error(exc, httpx):
                raise
            if attempt + 1 >= _MAX_TRANSPORT_ATTEMPTS:
                raise
            delay = _retry_delay(None, attempt, deadline)
            if delay is None:
                raise
            time.sleep(delay)
            continue
        last_result = result
        if _retryable(result.status) and attempt + 1 < _MAX_TRANSPORT_ATTEMPTS:
            delay = _retry_delay(result, attempt, deadline)
            if delay is not None:
                time.sleep(delay)
                continue
        return result
    if last_exc is not None:                                           
        raise last_exc
    if last_result is not None:
        return last_result
    raise ProviderHTTPError(502, "transport retry loop exhausted", retryable=True)


def _multipart_once(
    url: str, headers: dict, files: dict, data: dict, timeout: float, deadline: float
) -> HTTPResult:
    with _client().stream(
        "POST", url, headers=headers, files=files, data=data, timeout=_timeout(timeout)
    ) as resp:
        raw, text = _read_capped_response(resp.iter_bytes(), deadline, timeout)
        status = resp.status_code
        response_headers = dict(getattr(resp, "headers", {}) or {})
        ctype = _header(response_headers, "content-type") or ""
    if "application/json" in ctype:
        try:
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            body = {"text": text}                                                          
        if not isinstance(body, dict):                                        
            body = {}                                                                  
    else:
        body = {"text": text}                                                                
    return HTTPResult(status=status, body=body, text=text, headers=response_headers)


def transcribe(
    provider: Provider,
    model: str,
    audio: bytes,
    filename: str,
    *,
    api_key: str | None,
    env: dict[str, str],
    language: str | None = None,
    response_format: str = "json",
    timeout: float = 90.0,
    post: MultipartPostFn = default_multipart_post,
) -> TranscribeReply:
                                                                                           
    base_url = provider.base_url
    url = f"{base_url}/audio/transcriptions"
    headers = {}                                                                     
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    files = {"file": (filename or "audio", audio, "application/octet-stream")}
    data = {"model": model, "response_format": response_format}
    if language:
        data["language"] = language
    result = post(url, headers, files, data, timeout)
    if result.status != 200:
        raise _provider_http_error(result)
    body = result.body if isinstance(result.body, dict) else {}
    raw_text = body.get("text")
                                                                                         
                                                                                           
                                                                                     
    if not isinstance(raw_text, str):
        raise ProviderHTTPError(502, "malformed transcription response (no text)", retryable=True)
                                                                                                
                                                                                                    
    text = raw_text.strip()
    usage = body.get("usage") or {}
    return TranscribeReply(
        text=text,
        provider_id=provider.id,
        model=model,
        raw=body,
        prompt_tokens=usage.get("prompt_tokens"),
    )


def _call_gemini(
    provider: Provider,
    model: str,
    messages: list[Message],
    *,
    api_key: str | None,
    max_tokens: int,
    temperature: float,
    timeout: float,
    post: PostFn,
) -> Reply:
    system_instruction, contents = _to_gemini_contents(messages)
    url = f"{provider.base_url}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json"}
    if api_key:                                                               
        headers["x-goog-api-key"] = api_key
    body: dict = {
        "contents": contents,
        "generationConfig": _gemini_generation_config(model, max_tokens, temperature),
    }
    if system_instruction:
        body["systemInstruction"] = system_instruction

    result = post(url, headers, body, timeout)
    if result.status != 200:
        raise _provider_http_error(result)

    candidates = result.body.get("candidates") or []
    if not candidates:
        raise ProviderHTTPError(502, "no candidates in response", retryable=True)
    if not isinstance(candidates[0], dict):
        raise ProviderHTTPError(502, "malformed candidate in response", retryable=True)
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = _strip_think("".join(p.get("text") or "" for p in parts if isinstance(p, dict)))
    usage = result.body.get("usageMetadata") or {}
    return Reply(
        text=text,
        provider_id=provider.id,
        model=model,
        raw=result.body,
        prompt_tokens=usage.get("promptTokenCount"),
        completion_tokens=usage.get("candidatesTokenCount"),
    )
