                                      

from __future__ import annotations


class SparrowError(Exception):
    pass


class NoProvidersConfigured(SparrowError):
    pass


class AllProvidersExhausted(SparrowError):
    pass

                                                                          
                                                                     
       

    def __init__(
        self,
        attempts: list[tuple[str, str]],
        *,
        client_status: int | None = None,
        client_message: str | None = None,
    ):
        self.attempts = attempts
                                                                                   
                                                                                   
                                                              
        self.client_status = client_status
        self.client_message = client_message
        detail = "; ".join(f"{name}: {reason}" for name, reason in attempts) or "no candidates"
        super().__init__(f"all providers exhausted ({detail})")


class ContextWindowExceeded(AllProvidersExhausted):
                                                                           

                                                                                  
                                                                                 
                                                                             
                                               
       

    def __init__(self, attempts: list[tuple[str, str]], *, est_tokens: int):
        self.est_tokens = est_tokens
        super().__init__(attempts)

    def __str__(self) -> str:
        detail = "; ".join(f"{name}: {reason}" for name, reason in self.attempts) or "no candidates"
        return (
            f"input is ~{self.est_tokens:,} tokens and exceeded the context window of every "
            f"model tried — shorten the input or configure a larger-context provider ({detail})"
        )


class ProviderHTTPError(SparrowError):
                                                     

                                                                           
                                                                        
       

    def __init__(
        self,
        status: int,
        message: str,
        *,
        retryable: bool,
        retry_after: float | None = None,
        error_type: str | None = None,
    ):
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.error_type = error_type
        super().__init__(f"HTTP {status}: {message}")
