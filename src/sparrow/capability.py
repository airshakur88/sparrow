                                                                             

                                                                            
                                                                                  
                                                                              
                                   

                                                                              
                                                                              
                                                                          
                                                                                  
                                                                                
                                  

                                                                                 
                                                                   
   

from __future__ import annotations

import bisect
import json
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from .context import estimate_input_tokens

_BUNDLED_SCORES = Path(__file__).with_name("capability_scores.json")
_NEUTRAL = 0.5                                                              

                                                                                

                                                                     
_PROVIDER_PREFIX_RE = re.compile(r"^[^/]+/")
                                                                        
                                                                           
                                                                           
                                                                        
_VENDOR_PREFIX_RE = re.compile(
    r"^(?:meta|mistralai|nvidia|google|microsoft|nousresearch|cognitivecomputations|"
    r"deepseek-ai|cohere|c4ai|ai21|aisingapore|ibm-granite|ibm|zai-org|zai|"
    r"moonshotai|minimaxai|xiaomimimo|opengvlab|sarvamai|01-ai|"
    r"openai|z-ai)[-_]",
    re.IGNORECASE,
)
                                                              
                                                                            
_DOUBLED_FAMILY_RE = re.compile(r"^([a-z]{3,})[-_](?=\1)", re.IGNORECASE)
                                                                               
                                                                                  
_DATE_SUFFIX_RE = re.compile(r"[-_](?:\d{4}-\d{2}-\d{2}|\d{6,8}|\d{2,4})$")
                                                                             
                                                                               
                                                                                
                                                                            
_VARIANT_SUFFIX_RE = re.compile(
    r"[-_](?:versatile|instant|latest|instruct|chat|it|hf|fp8|bf16|lora|"
    r"preview|turbo|tuned|free|online|beta)$",
    re.IGNORECASE,
)

                                                                             
                                                                                
                                                     
_MODEL_NAME_ALIASES = {
    "morph-glm52-744b": "glm-5.2",
    "morph-minimax3-428b": "minimax-m3",
    "morph-dsv4flash": "deepseek-v4-flash",
                                                                             
                                                                               
                                                                             
    "qwen3.6-27b": "qwen3-30b-a3b",
    "qwen3.6-35b-a3b": "qwen3-30b-a3b",
}


@lru_cache(maxsize=8192)
def _normalize_model_name_base(name: str) -> str:
                                                                                     
    s = (name or "").strip().lower()
    s = _PROVIDER_PREFIX_RE.sub("", s)
                                                                                   
                                                                
    s = re.sub(r"[^a-z0-9.]+", "-", s).strip("-")
    s = _VENDOR_PREFIX_RE.sub("", s)
    s = _DOUBLED_FAMILY_RE.sub("", s)
                                                                          
    for _ in range(6):
        peeled = _VARIANT_SUFFIX_RE.sub("", s)
        peeled = _DATE_SUFFIX_RE.sub("", peeled)
        if peeled == s:
            break
        s = peeled
    s = s.strip("-")
    return s


@lru_cache(maxsize=8192)
def normalize_model_name(name: str) -> str:
                                                                                   
                                                                                  
                                                                     
                                                                                    
       
    key = _normalize_model_name_base(name)
    return _MODEL_NAME_ALIASES.get(key, key)


def _core(name: str) -> str:
                                                                          
    return re.sub(r"[^a-z0-9]+", "", normalize_model_name(name))


                                                                                

                                                                                 
                                                                               
                                    
_PARAM_RE = re.compile(r"(?<![.\d])(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)
_DOWNWEIGHT_RE = re.compile(r"\b(?:flash|lite|mini|nano|tiny|instant|small|edge)\b", re.IGNORECASE)
_UPWEIGHT_RE = re.compile(r"\b(?:opus|reasoning|thinking|r1|o[1-9])\b", re.IGNORECASE)


def _heuristic_score(name: str) -> float:
                                                                                 
                                                                               
                                
    s = (name or "").lower()
    params = [float(x) for x in _PARAM_RE.findall(s)]
    if params:
        b = max(params)
        if b >= 200:
            score = 0.85
        elif b >= 100:
            score = 0.78
        elif b >= 60:
            score = 0.68
        elif b >= 30:
            score = 0.58
        elif b >= 12:
            score = 0.46
        elif b >= 7:
            score = 0.38
        else:
            score = 0.28
    else:
        score = _NEUTRAL
    if _DOWNWEIGHT_RE.search(s):
        score = min(score, 0.40)
    if _UPWEIGHT_RE.search(s):
        score = max(score, 0.62)
    return round(score, 4)


                                                                                


def user_capability_path() -> Path:
                                                                                   

                                                                        
       
    override = os.environ.get("SPARROW_CAPABILITY_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "sparrow" / "capability_scores.json"


def _read_scores(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = data.get("scores", {}) if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, val in raw.items():
        score = val.get("score") if isinstance(val, dict) else val
        if score is None:
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):                                                
            continue
                                                                        
                                                             
        out[str(key)] = max(0.0, min(1.0, value))
    return out


@lru_cache(maxsize=8)
def _table_cached(user_str: str, _user_mtime: int) -> Mapping[str, float]:
                                                                                
                                                                                   
                                                                                       
    table = _read_scores(_BUNDLED_SCORES)
    table.update(_read_scores(Path(user_str)))
    return MappingProxyType(table)


def capability_table() -> Mapping[str, float]:
                                                                                  

                                                                             
       
    user = user_capability_path()
    try:
        mtime = user.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return _table_cached(str(user), mtime)


def model_capability(name: str, table: Mapping[str, float] | None = None) -> float:
                                                                                   

                                                                                 
                                                         
       
    if table is None:
        table = capability_table()
                                                                              
                                                                                
                                                                               
                                                            
    direct_key = _normalize_model_name_base(name)
    if direct_key in table:
        return table[direct_key]
    key = _MODEL_NAME_ALIASES.get(direct_key, direct_key)
    if key in table:
        return table[key]
    core = _core(name)
    if core and core in table:
        return table[core]
    return _heuristic_score(name)


                                                                                

_CODE_RE = re.compile(
    r"```|\bdef \b|\bclass \b|=>|;\s*$|^\s*(?:diff --git|@@ |[+-]{3} )", re.MULTILINE
)
_HARD_RE = re.compile(
    r"\b(?:debug|refactor|prove|analy[sz]e|algorithm|optimi[sz]e|architect|"
    r"design|reason|derive|complex|trade-?offs?|step by step|why)\b",
    re.IGNORECASE,
)


def _messages_text(messages) -> tuple[str, int]:
                                                                                
    parts: list[str] = []
    turns = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") in ("user", "assistant"):
            turns += 1
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
    return "\n".join(parts), turns


def prompt_difficulty(messages, max_tokens: int | None = None, tools=None) -> float:
                                                            

                                                                            
                                                                             
                                                                                 
                                                                      
       
    text, turns = _messages_text(messages)
    tokens = estimate_input_tokens(messages, tools)
    score = 0.35                                      
    if tokens > 8000:
        score += 0.30
    elif tokens > 2000:
        score += 0.20
    elif tokens > 500:
        score += 0.10
    if _CODE_RE.search(text):
        score += 0.20
    if _HARD_RE.search(text):
        score += 0.20
    if tools:
        score += 0.15
    if turns >= 6:
        score += 0.10
    if max_tokens and max_tokens >= 2048:
        score += 0.10
    return round(max(0.0, min(1.0, score)), 4)


                                                                                

_UNDERPOWER_PENALTY = 100.0                                   
_OVERPOWER_PENALTY = 1.0                                               


def fit_penalty(capability: float, need: float) -> float:
                                                                               
                                         

                                                                               
                                                                               
                                                                                
                                                             
       
    gap = capability - need
    if gap < 0:
        return (-gap) * _UNDERPOWER_PENALTY
    return gap * _OVERPOWER_PENALTY


                                                                                


def normalize_scores(raw: dict[str, float]) -> dict[str, float]:
                                                                             
                                                                                   
                             

                                                                                  
                                                                                  
                                                                                 
                                                                                    
                                                                                   
                                                                                   
                     
       
    if not raw:
        return {}
    by_key: dict[str, float] = {}
    for name, value in raw.items():
        key = normalize_model_name(name)
        if not key:
            continue
        by_key[key] = max(by_key.get(key, float("-inf")), float(value))
    values = sorted(by_key.values())
    n = len(values)
    out: dict[str, float] = {}
    for key, value in by_key.items():
        lo = bisect.bisect_left(values, value)
        hi = bisect.bisect_right(values, value)
        out[key] = round((lo + hi) / 2.0 / n, 4)                      
    return out


def build_capability_table(
    *,
    aa_scores: dict[str, float] | None = None,
    arena_scores: dict[str, float] | None = None,
    aider_scores: dict[str, float] | None = None,
    catalog_names: list[str] | None = None,
) -> dict[str, dict]:
                                                                                 
                                                                         

                                                                                    
                                                                                  
                                                                                     
                                                                                  
                                                                                  
                                                                                   
                                                                                     
                                                                                
                                                                                     
                    
       
    from .config import load_catalog

    if catalog_names is None:
        catalog_names = [m.name for p in load_catalog() for m in p.models]

    aa = normalize_scores(aa_scores or {})
    arena = normalize_scores(arena_scores or {})
    aider = normalize_scores(aider_scores or {})
    resolvers = [
        _index_source("aa", aa),
        _index_source("arena", arena),
        _index_source("aider", aider),
    ]
    families = set().union(*(r["families"] for r in resolvers))

                                                                              
                                                                                   
                                                                
    stem_keys: dict[str, set[str]] = {}
    for name in catalog_names:
        key = normalize_model_name(name)
        if key and _largest_params(key) is not None:
            stem_keys.setdefault(_alnum(_strip_params(key)), set()).add(key)
    ambiguous_stems = {stem for stem, keys in stem_keys.items() if len(keys) > 1}

    table: dict[str, dict] = {}
    for name in catalog_names:
        key = normalize_model_name(name)
        if not key or key in table:
            continue
        entry = _resolve_capability(key, resolvers, families, ambiguous_stems)
        if entry is not None:
            table[key] = entry
    return table


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s)


def _strip_params(key: str) -> str:
                                                                                       
    return re.sub(r"(?<![.\d])\d+(?:\.\d+)?b\b", "", key)


def _largest_params(key: str) -> float | None:
    params = [float(x) for x in re.findall(r"(?<![.\d])(\d+(?:\.\d+)?)b\b", key)]
    return max(params) if params else None


def _leading_family(key: str) -> str:
                                                                         
                                                                   
    m = re.match(r"[a-z]+", key)
    fam = m.group(0) if m else ""
    return fam if len(fam) >= 4 else ""


def _index_source(label: str, norm_scores: dict[str, float]) -> dict:
                                                              
                                                                                 
                                                                             
                                                                                  
                                                                                    
    core: dict[str, float] = {}
    noparam_core: dict[str, float] = {}
    fp: dict[tuple[str, float], float] = {}
    families: set[str] = set()
    for key, value in norm_scores.items():
        ck = _alnum(key)
        if ck:
            core[ck] = max(core.get(ck, 0.0), value)
        fam = _leading_family(key)
        if fam:
            families.add(fam)
        params = _largest_params(key)
        if params is None:
            if ck:
                noparam_core[ck] = max(noparam_core.get(ck, 0.0), value)
        elif fam:
                                                                                    
            fp[(fam, params)] = max(fp.get((fam, params), 0.0), value)
    return {
        "label": label,
        "exact": norm_scores,
        "core": core,
        "noparam": noparam_core,
        "fp": fp,
        "families": families,
    }


def _resolve_capability(
    key: str, resolvers: list[dict], families: set[str], ambiguous_stems: set[str]
) -> dict | None:
                                                                                       

                                                                                   
                                                                                     
                                                                                  
                                                                                  
                                                                                    
                                                                         
    core = _alnum(key)
    np_core = _alnum(_strip_params(key))
    has_params = np_core != core
    for r in resolvers:
        if key in r["exact"]:
            return {"score": r["exact"][key], "source": r["label"]}
        if core in r["core"]:
            return {"score": r["core"][core], "source": r["label"]}
        if has_params and np_core and np_core not in ambiguous_stems and np_core in r["noparam"]:
            return {"score": r["noparam"][np_core], "source": r["label"]}
    params = _largest_params(key)
    if params is not None:
        tokens = [t for t in re.findall(r"[a-z]+", key) if len(t) >= 4 and t in families]
        for r in resolvers:
            for tok in tokens:
                if (tok, params) in r["fp"]:
                    return {"score": r["fp"][(tok, params)], "source": f"{r['label']}~"}
    return None


                                                                                 

                                                                             
ARENA_DATASET = "mathewhe/chatbot-arena-elo"
_HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
                                                                              
                                                                              
                                                                                 
                                                                          
AA_DEFAULT_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
                                                                                
                                                                          
AIDER_URLS = (
    "https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml",
    "https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/edit_leaderboard.yml",
)
_MAX_FETCH_BYTES = 8 * 1024 * 1024
                                                                                 
                                    
_AA_ALLOWED_HOSTS = frozenset({"artificialanalysis.ai", "www.artificialanalysis.ai"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
                                                                                  
                                                        

    def redirect_request(self, *args, **kwargs):              
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect())


def _get_text(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> str:
    if not url.lower().startswith("https://"):
        raise ValueError(f"refusing non-https benchmark URL: {url!r}")
    request = urllib.request.Request(url, headers=headers or {})
    with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
        raw = response.read(_MAX_FETCH_BYTES + 1)
    if len(raw) > _MAX_FETCH_BYTES:
        raise ValueError(f"benchmark response exceeds {_MAX_FETCH_BYTES} bytes; refusing to load")
    return raw.decode("utf-8")


def _get_json(url: str, *, timeout: float, headers: dict[str, str] | None = None):
    return json.loads(_get_text(url, timeout=timeout, headers=headers))


def fetch_aider_scores(*, timeout: float = 20.0) -> dict[str, float]:
                                                                              

                                                                                  
                                                                    
       
    scores: dict[str, float] = {}
    for url in AIDER_URLS:
        try:
            text = _get_text(url, timeout=timeout)
        except (OSError, ValueError, urllib.error.HTTPError):
            continue
        model: str | None = None
        for line in text.splitlines():
            name_match = re.match(r"\s*model:\s*(.+?)\s*$", line)
            if name_match:
                model = name_match.group(1)
            rate_match = re.match(r"\s*pass_rate_2:\s*([\d.]+)", line)
            if rate_match and model:
                scores[model] = max(scores.get(model, 0.0), float(rate_match.group(1)))
                model = None
    return scores


def fetch_arena_scores(*, timeout: float = 20.0) -> dict[str, float]:
                                                                      

                                                                              
                                                 
       
    scores: dict[str, float] = {}
    offset = 0
    page = 100
    while True:
        url = (
            f"{_HF_ROWS_URL}?dataset={ARENA_DATASET.replace('/', '%2F')}"
            f"&config=default&split=train&offset={offset}&length={page}"
        )
        data = _get_json(url, timeout=timeout)
        rows = data.get("rows", []) if isinstance(data, dict) else []
        if not rows:
            break
        for entry in rows:
            row = entry.get("row", {}) if isinstance(entry, dict) else {}
            name = row.get("Model")
            elo = row.get("Arena Score")
            if isinstance(name, str) and isinstance(elo, (int, float)):
                scores[name] = float(elo)
        total = data.get("num_rows_total") if isinstance(data, dict) else None
        offset += page
        if not isinstance(total, int) or offset >= total:
            break
    return scores


def fetch_aa_scores(
    *, api_key: str, url: str = AA_DEFAULT_URL, timeout: float = 20.0
) -> dict[str, float]:
                                                                            

                                                                                  
                                                                                   
                                                                                
                                                                          
       
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in _AA_ALLOWED_HOSTS:
        raise ValueError(f"refusing to send the AA key to a non-AA/non-https URL: {url!r}")
    try:
        data = _get_json(url, timeout=timeout, headers={"x-api-key": api_key})
    except (OSError, ValueError, urllib.error.HTTPError):
        return {}
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}
    scores: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("slug") or row.get("name")
        evals = row.get("evaluations")
        value = (
            evals.get("artificial_analysis_intelligence_index") if isinstance(evals, dict) else None
        )
        if isinstance(name, str) and isinstance(value, (int, float)):
            scores[name] = float(value)
    return scores


def sync_capability_table(
    *,
    timeout: float = 20.0,
    aa_api_key: str | None = None,
    aa_url: str = AA_DEFAULT_URL,
    path: Path | None = None,
) -> tuple[Path, dict]:
                                                                           

                                                                                 
                                                                                   
                                                                               
       
    path = path or user_capability_path()
    arena = fetch_arena_scores(timeout=timeout)
    aider = fetch_aider_scores(timeout=timeout)
    aa = fetch_aa_scores(api_key=aa_api_key, url=aa_url, timeout=timeout) if aa_api_key else {}
    if aa:
                                                                                  
                                                                            
        package_dir = Path(__file__).resolve().parent
        if package_dir == path.resolve().parent or package_dir in path.resolve().parents:
            raise ValueError(
                f"refusing to write Artificial Analysis data into the package dir: {path}. "
                "AA scores may only be cached outside the installed package."
            )
    table = build_capability_table(aa_scores=aa, arena_scores=arena, aider_scores=aider)
    by_source: dict[str, int] = {}
    for entry in table.values():
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
    payload = {
        "meta": {
            "arena_models": len(arena),
            "aider_models": len(aider),
            "aa_models": len(aa),
            "mapped": len(table),
        },
        "scores": table,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _table_cached.cache_clear()
    return path, {
        "arena": len(arena),
        "aider": len(aider),
        "aa": len(aa),
        "mapped": len(table),
        "by_source": by_source,
    }
