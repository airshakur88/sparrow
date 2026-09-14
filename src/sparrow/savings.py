                                                                       

                                                                                    
                                                                                                
                                                                           
                                                                         
   

from __future__ import annotations

                                                                               
_OPUS_INPUT = 15.00 / 1_000_000
_OPUS_OUTPUT = 75.00 / 1_000_000

                                                                              
BASELINE_LABEL = "Claude Opus 4.8 rates"


def usd_saved(prompt_tokens: int | None, completion_tokens: int | None) -> float:
                                                                  
    pt = prompt_tokens or 0
    ct = completion_tokens or 0
    return pt * _OPUS_INPUT + ct * _OPUS_OUTPUT


def format_saved(prompt_tokens: int | None, completion_tokens: int | None) -> str:
    amount = usd_saved(prompt_tokens, completion_tokens)
    if amount < 0.01:
        return f"~${amount:.4f} estimated not spent ({BASELINE_LABEL})"
    return f"~${amount:,.2f} estimated not spent ({BASELINE_LABEL})"
