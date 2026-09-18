                                                                    

                              

                                                                    
                                                                    
                                                 
                                                                      
                                                     
                                                                     
                         

                                                                       
                                                                   
                                                                        
   

from __future__ import annotations

import ipaddress
import secrets
import shutil
import string
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TextIO

                                                                    
                                                                    
                                     
_TAILNET_V4_NETWORK = ipaddress.ip_network("100.64.0.0/10")

                                                                   
                                                                      
                                                                     
                                                                      
_TAILSCALE_TIMEOUT_SECONDS = 4.0


                                                                     
                                                               
STATE_USABLE = "usable"
STATE_CLI_MISSING = "cli-missing"
STATE_LOGGED_OUT = "logged-out"
STATE_NO_IPV4 = "no-ipv4"
STATE_MALFORMED = "malformed"


class SetupTokenLabel(Enum):
                                                                 

    PROXY_KEY = "<proxy-key>"
    PROXY_KEY_FROM_SERVER = "<proxy-key-from-server>"
    YOUR_PROXY_KEY = "<your-proxy-key>"
    SESSION_REAL_RUN = "<session-token-printed-on-real-run>"
    SESSION_DISCLOSED = "<session-token-shown-above>"


@dataclass(frozen=True)
class TailnetStatus:
                                                  

               
                                           
                                                                        
                                                 
                                                                        
                                                                  
                                                  
                                                                      
                                                                       
       

    state: str
    ipv4: str | None = None
    raw: str = ""
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.state == STATE_USABLE and self.ipv4 is not None


def _run_tailscale(
    args: Sequence[str],
    *,
    timeout: float,
    binary: str = "tailscale",
) -> subprocess.CompletedProcess[str]:
                                                                        

                                                                    
                        
       
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _validate_tailnet_ipv4(candidate: str) -> str | None:
                                                                       

                                                                      
                                                                      
                                                             
       
    if not candidate:
        return None
    try:
        addr = ipaddress.IPv4Address(candidate)
    except (ipaddress.AddressValueError, ValueError):
        return None
    if addr in _TAILNET_V4_NETWORK:
        return str(addr)
    return None


def _cli_missing_status() -> TailnetStatus:
    return TailnetStatus(
        state=STATE_CLI_MISSING,
        detail=(
            "the `tailscale` CLI is not on PATH. "
            "Install Tailscale (https://tailscale.com/download) and log in, "
            "or run `sparrow start` on loopback instead."
        ),
    )


def _logged_out_status() -> TailnetStatus:
    return TailnetStatus(
        state=STATE_LOGGED_OUT,
        detail=(
            "`tailscale` is not logged in. Run `tailscale up` to join your Tailnet, "
            "or run `sparrow start` on loopback instead."
        ),
    )


def _classify_ipv4_output(raw: str) -> TailnetStatus | None:
                                                                           

                                                                       
                                                                    
                              
       
    raw = raw.strip()
    if not raw:
        return None

    seen: list[str] = []
    for line in raw.splitlines():
        token = line.strip()
        if not token:
            continue
        seen.append(token)
        validated = _validate_tailnet_ipv4(token)
        if validated is not None:
            return TailnetStatus(state=STATE_USABLE, ipv4=validated, raw=raw)

                                                                     
                                                                
                                                                
    return TailnetStatus(
        state=STATE_MALFORMED,
        raw=raw,
        detail=(
            "`tailscale ip -4` output did not contain a 100.64.0.0/10 "
            f"address (saw: {', '.join(seen[:3])}). "
            "Refusing to bind to a non-Tailnet address."
        ),
    )


def detect_tailnet(
    *,
    binary: str | None = "tailscale",
    runner=None,
    timeout: float = _TAILSCALE_TIMEOUT_SECONDS,
) -> TailnetStatus:
                                                       

                                                                   
                                                                      
                                                                       
                                           

         
                                                                   
                                                                      
                                                                      
                                                                
                                                                   
                                        
                                                                         
                                                         
                                                                    
                                                            
       
    if binary is None:
        return _cli_missing_status()
    if binary == "tailscale" and shutil.which(binary) is None:
        return _cli_missing_status()
    if runner is None:

        def runner(args: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
            return _run_tailscale(args, timeout=timeout, binary=binary)

                                                                     
                           
    try:
        proc = runner(["ip", "-4"], timeout=timeout)
    except subprocess.TimeoutExpired:
        return TailnetStatus(
            state=STATE_LOGGED_OUT,
            detail=(
                "`tailscale ip -4` timed out — the local Tailscale daemon is not "
                "responding. Run `tailscale status` to diagnose."
            ),
        )
    except OSError as exc:
                                                                    
                                                                   
        return TailnetStatus(
            state=STATE_CLI_MISSING,
            detail=f"could not invoke `tailscale`: {exc.strerror or exc}",
        )

    if proc.returncode != 0:
                                                                     
                                                                      
                                                                     
                                                           
        return _logged_out_status()

    classified = _classify_ipv4_output(proc.stdout or "")
    if classified is not None:
        return classified

    return TailnetStatus(
        state=STATE_NO_IPV4,
        detail=(
            "`tailscale ip -4` returned no IPv4 address. "
            "This usually means the node has no usable Tailnet IP yet "
            "(check `tailscale status`)."
        ),
    )


def is_loopback_host(host: str) -> bool:
                                                                                 
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ipaddress.AddressValueError, ValueError):
        return False


def is_tailnet_host(host: str) -> bool:
                                                                  
    return _validate_tailnet_ipv4(host) is not None


def generate_session_token(*, nbytes: int = 24) -> str:
                                                              

                                                                       
                                                                    
                                                                    
                                                                  
                                                                       
                                                             

         
                                                                    
                                                                       
       
    return secrets.token_urlsafe(nbytes)


class _NonTTYDisclosureError(RuntimeError):
    pass


def _disclose_session_token_to_tty(token: str, *, stream: TextIO) -> None:
                                                                          

                                                                             
                                                                               
                                                                               
                                                            
       
    if not stream.isatty():
        raise _NonTTYDisclosureError(
            "refusing session-token disclosure without an interactive terminal"
        )
    if not token:
        raise ValueError("session token must be non-empty")
    stream.write(
        "\nsparrow: generated a one-session proxy key:\n"
        f"  {token}\n"
        "  (use it as the client bearer token; it is not saved anywhere)\n"
    )
    stream.flush()


                                                                   
                                                             
                                                                   
                                                                      
_ALPHANUM = string.ascii_letters + string.digits


def generate_session_token_simple(length: int = 32) -> str:
                                                                        
                                                                 

                                                                   
                                                              
       
    if length <= 0:
        return ""
    return "".join(secrets.choice(_ALPHANUM) for _ in range(length))


def safe_base_url(host: str, port: int) -> str:
                                                                      

                                                                       
                                                                    
                                                                 
       
    url_host = host
    if not (host.startswith("[") and host.endswith("]")):
        try:
            addr = ipaddress.ip_address(host)
        except (ipaddress.AddressValueError, ValueError):
            pass
        else:
            url_host = f"[{addr}]" if addr.version == 6 else str(addr)
    return f"http://{url_host}:{port}"


def format_setup_hints(
    *,
    base_url: str,
    auth_enabled: bool,
    token_label: SetupTokenLabel = SetupTokenLabel.PROXY_KEY,
    include_provider_keys: bool = False,
) -> str:
                                                                     

                                                                          
                                                                               
                                                                           
                                

                                                                  
                                                                  
                                                                      
                                                     
       
                                                                    
    del include_provider_keys
    if not isinstance(auth_enabled, bool):
        raise TypeError("auth_enabled must be a bool")
    if not isinstance(token_label, SetupTokenLabel):
        raise TypeError("token_label must be a SetupTokenLabel")

    openai_base = f"{base_url}/v1"
    if auth_enabled:
        key_value = token_label.value
        openai_key = f"'{key_value}'"
        openai_note = "# proxy bearer token"
    else:
        openai_key = "anything"
        openai_note = "# ignored when proxy auth is disabled"

    auth_lines = []
    if auth_enabled:
        auth_lines.append(
            f"    export SPARROW_PROXY_KEY='{token_label.value}'  "
            "# optional local name for the proxy token"
        )
    auth_block = ("\n".join(auth_lines) + "\n") if auth_lines else ""
    return (
        f"  OpenAI-compatible base URL : {openai_base}\n"
        f"  dashboard                  : {base_url}/dashboard\n"
        "\n"
        "  On the client machine (or in the agent's env):\n"
        f"    export OPENAI_BASE_URL={openai_base}\n"
        f"    export OPENAI_API_KEY={openai_key}        {openai_note}\n"
        f"    export SPARROW_BASE_URL={openai_base}\n"
        f"{auth_block}"
    )


def assert_bind_safe(
    *,
    host: str,
    api_key: str | None,
    allow_lan: bool = False,
    allow_no_auth: bool = False,
) -> None:
                                                                           

                                     

                                                          
                                                          
                                                                        
                                                              
                                                                     
                                                                     
                                                                       

                                                                       
                         
       
    if is_loopback_host(host):
        return

    tailnet = is_tailnet_host(host)
    if tailnet and api_key:
        return                                          

    if tailnet and not api_key:
        if allow_no_auth:
            return
        raise UnsafeBindError(
            f"refusing to bind to Tailnet address {host} without a proxy key. "
            "Pass --api-key, set SPARROW_PROXY_KEY, or pass --allow-no-auth "
            "to acknowledge the risk."
        )

                                                                 
    if not allow_lan:
        raise UnsafeBindError(
            f"refusing to bind to {host}: not loopback and not a Tailnet (100.x) "
            "address. Pass --allow-lan to expose the proxy on your LAN, "
            "or use a 100.x Tailnet IPv4 for safer cross-machine access."
        )
    if not api_key and not allow_no_auth:
        raise UnsafeBindError(
            f"refusing to bind to {host} without a proxy key. "
            "Pass --api-key, set SPARROW_PROXY_KEY, or pass --allow-no-auth "
            "to acknowledge the risk."
        )


class UnsafeBindError(ValueError):
    pass


__all__ = [
    "STATE_USABLE",
    "STATE_CLI_MISSING",
    "STATE_LOGGED_OUT",
    "STATE_NO_IPV4",
    "STATE_MALFORMED",
    "SetupTokenLabel",
    "TailnetStatus",
    "detect_tailnet",
    "is_loopback_host",
    "is_tailnet_host",
    "generate_session_token",
    "generate_session_token_simple",
    "safe_base_url",
    "format_setup_hints",
    "assert_bind_safe",
    "UnsafeBindError",
]
