                                              

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Model:
                                               

    name: str
    rpd: int = 0                                                          
    enabled: bool = True                                                                      
    context: int | None = None                                                          
    auto: bool = True                                                                             
    requires_key: bool = False

    @property
    def key(self) -> str:
                                                                      
        return self.name


@dataclass(frozen=True)
class Provider:
                                                            

    id: str
    label: str
    adapter: str                                      
    base_url: str
    models: tuple[Model, ...]
    key_env: str | None = None
    auth: str = "bearer"                               
    key_optional: bool = False                                            
    extra_env: tuple[str, ...] = field(default_factory=tuple)

    @property
    def keyless(self) -> bool:
                                                                           
        return self.auth == "none" or self.key_optional or not self.key_env

    def is_configured(self, env: dict[str, str] | None = None) -> bool:
                                                                               
                                                     
        env = env if env is not None else dict(os.environ)
        if not all(env.get(name) for name in self.extra_env):
            return False
        if self.keyless:
            return True
        return bool(self.key_env and env.get(self.key_env))

    def api_key(self, env: dict[str, str] | None = None) -> str | None:
        env = env if env is not None else dict(os.environ)
        if not self.key_env:
            return None
        return env.get(self.key_env) or None

    def model(self, name: str) -> Model | None:
        for m in self.models:
            if m.name == name:
                return m
        return None


@dataclass
class Reply:
                                                                

    text: str
    provider_id: str
    model: str
    raw: dict
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1                                                           
    message: dict | None = None                                                    
    cached: bool = False                                          

    def __str__(self) -> str:                                  
        return self.text


@dataclass
class EmbedReply:
                                                            

    vectors: list[list[float]]
    provider_id: str
    model: str
    prompt_tokens: int | None = None


@dataclass
class TranscribeReply:
                                                                                   

    text: str
    provider_id: str
    model: str
    raw: dict
    prompt_tokens: int | None = None
