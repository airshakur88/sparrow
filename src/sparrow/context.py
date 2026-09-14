                                                                            

                                                                             
                                                                                
                                                                                  
                                                                       

                                                                                 
                                                                                
                                                                                  
                                 
   

from __future__ import annotations

import json
import re

                                                                                
                                                                              
                                                       
_CTX_PHRASES = re.compile(
    r"maximum context length|context length is|context window|maximum_context_length|"
    r"prompt is too long|input is too long|too many (?:input )?tokens|"
    r"exceeds the (?:model'?s )?context|reduce the length of the messages",
    re.IGNORECASE,
)

                                                                                 
                                                                                
_LIMIT_RE = re.compile(r"context\s+(?:length|window)[^.\d]*?(\d[\d,]+)\s*token", re.IGNORECASE)

_TOKENS_PER_CHAR = 0.25                                                             


def estimate_input_tokens(messages, tools=None) -> int:
                                                                          

                                                                                
                                                                                  
                                                                                   
                                                              
       
    chars = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):                    
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
        if m.get("tool_calls"):                                              
            try:
                chars += len(json.dumps(m["tool_calls"]))
            except (TypeError, ValueError):                                
                pass
    if tools:
        try:
            chars += len(json.dumps(tools))
        except (TypeError, ValueError):                                
            pass
    return int(chars * _TOKENS_PER_CHAR)


def context_limit_from_error(status: int, message: str) -> tuple[bool, int | None]:
                                                                                   

                                                                                  
                                                                                   
                                                      
       
    if status not in (400, 413):
        return (False, None)
    msg = message or ""
    if not _CTX_PHRASES.search(msg):
        return (False, None)
    limit: int | None = None
    m = _LIMIT_RE.search(msg)
    if m:
        digits = m.group(1).replace(",", "")
        if digits.isdigit():
            limit = int(digits)
    return (True, limit)
