                                      

                                                                                
                                                   
   

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .config import (
    configured_providers,
    load_catalog,
    resolve_alias,
    settings,
    split_provider_model,
)
from .conformance import ConformanceStore
from .errors import AllProvidersExhausted, NoProvidersConfigured
from .mode import (
    WISE_DEFAULT_MAX_TOKENS,
    WISE_DEFAULT_ROUTING,
    declared_quota_exhausted,
    is_wise_enabled,
    targets_with_declared_headroom,
)
from .panel import render_panel_markdown, run_panel
from .quota import QuotaStore
from .roles import format_roles, get_role
from .router import Pool
from .routing_modes import PUBLIC_ROUTING_ALIASES, routing_override
from .savings import format_saved
from .task_quality import TASK_HINTS
from .virtual_models import VIRTUAL_MODELS


def _read_stdin() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _runtime_catalog():
                                                                                

    from .plugins import registered_providers

    by_id = {provider.id: provider for provider in load_catalog()}
    for provider in registered_providers():
        by_id[provider.id] = provider
    return list(by_id.values())


def cmd_ask(args: argparse.Namespace) -> int:
    stdin = _read_stdin()
    prompt = args.prompt or ""
    if stdin:
        prompt = f"{stdin}\n\n{prompt}".strip() if prompt else stdin

    if not prompt.strip():
        print("sparrow: no prompt provided (pass text or pipe stdin)", file=sys.stderr)
        return 3

    role = get_role(args.role) if args.role else None
    if args.role and role is None:
        print(f"sparrow: unknown role '{args.role}'\n", file=sys.stderr)
        print(format_roles(), file=sys.stderr)
        return 2

                                                                          
                                                                                 
                                                                                
    model_filter = resolve_alias(args.model) if args.model else None
    if model_filter == "auto":
        model_filter = None
    provider_filter = args.providers.split(",") if args.providers else None
    if model_filter and "/" in model_filter:
                                                                                              
                                                                                             
        prov, mdl = split_provider_model(model_filter, {p.id for p in configured_providers()})
        if prov is not None:
            provider_filter, model_filter = prov, mdl

    system = args.system
    if system is None and role is not None and role.system_prefix is not None:
        system = role.system_prefix
    if args.json:
        json_rule = "Respond with a single valid JSON value and nothing else — no prose, no markdown fences."
        system = f"{system}\n{json_rule}" if system else json_rule

    pool = Pool.from_default_config()
    pool_env = os.environ.copy()
    configured_env = getattr(pool, "env", None)
    if configured_env is not None:
        pool_env = {str(name): str(value) for name, value in configured_env.items()}
    mode_settings = settings(pool_env)
    has_routing_config = bool(pool_env.get("SPARROW_ROUTING") or mode_settings.get("routing"))
    wise = is_wise_enabled(pool_env, override=args.mode, settings=mode_settings)
    max_tokens = args.max_tokens
    if max_tokens is None:
        max_tokens = (
            role.max_tokens
            if (role is not None and role.max_tokens is not None)
            else (WISE_DEFAULT_MAX_TOKENS if wise else 1024)
        )

    temperature = args.temperature
    if temperature is None:
        temperature = role.temperature if (role is not None and role.temperature is not None) else 0.0

    routing = routing_override(args.routing) if args.routing is not None else None
    if args.routing is None and routing is None and role is not None and role.routing is not None:
        routing = role.routing
    if args.routing is None and routing is None and role is None and wise:
        routing = WISE_DEFAULT_ROUTING
    if args.routing is None and routing is None and role is None and args.mode == "normal":
        if not has_routing_config:
            routing = "fair"
    task = args.task if args.task is not None else (role.task if role is not None else None)

    second_opinion = bool(args.second_opinion or (role is not None and role.name == "second-opinion"))
    if second_opinion:
        if args.json:
            print("sparrow: --json is not supported with --second-opinion", file=sys.stderr)
            return 2
        result = run_panel(
            pool,
            prompt=prompt,
            system=system,
            n=args.opinions,
            routing=routing or "quality",
            model=model_filter,
            providers=provider_filter,
            max_tokens=max_tokens,
            timeout=args.timeout,
            synthesize=args.synthesize,
            task=task,
        )
        if not result.answers:
            print("sparrow: no providers configured", file=sys.stderr)
            return 3
        print(render_panel_markdown(result, title="sparrow second opinion panel"))
        return 0 if result.successful_answers else 4

    if wise and not args.model and not args.providers:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        targets = pool.rank_targets(
            messages,
            routing=routing,
            model=model_filter,
            providers=provider_filter,
            task=task,
        )
        snapshot = pool.quota.snapshot()
        if declared_quota_exhausted(targets, snapshot):
            print(
                "sparrow: declared local free quota is exhausted in wise mode; "
                "rerun with an explicit --model or --providers if you want to override.",
                file=sys.stderr,
            )
            return 4
        headroom_targets = targets_with_declared_headroom(targets, snapshot)
        if headroom_targets:
            target = headroom_targets[0]
            provider_filter = [target.provider.id]
            model_filter = target.model
    try:
        reply = pool.ask(
            prompt,
            system=system,
            model=model_filter,
            providers=provider_filter,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=args.timeout,
            routing=routing,
            task=task,
        )
    except NoProvidersConfigured as exc:
        print(f"sparrow: {exc}", file=sys.stderr)
        return 3
    except AllProvidersExhausted as exc:
        print(f"sparrow: {exc}", file=sys.stderr)
        return 4

    text = reply.text
    if args.json:
        text = _strip_fences(text)
    print(text)
    if args.verbose:
        saved = format_saved(reply.prompt_tokens, reply.completion_tokens)
        print(f"\n[served by {reply.provider_id}/{reply.model} · {saved}]", file=sys.stderr)
    return 0


def _strip_fences(text: str) -> str:
                                                                           
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def cmd_providers(args: argparse.Namespace) -> int:
    catalog = _runtime_catalog()
    configured = {p.id for p in configured_providers(catalog)}
    n_models = sum(1 for p in catalog for m in p.models if m.enabled)
    print(f"sparrow catalog: {len(catalog)} providers, {n_models} models\n")
    for p in catalog:
        mark = "[ok]" if p.id in configured else "[--]"
        status = "configured" if p.id in configured else f"set {p.key_env}"
        on = sum(1 for m in p.models if m.enabled)
        off = len(p.models) - on
        count = f"{on} models" + (f" (+{off} off)" if off else "")
        print(f"  {mark} {p.id:<12} {p.label:<28} {count:<16} [{status}]")
    if not configured:
        print("\nNo providers configured yet. Add a key with `sparrow keys add <provider>`, or set one manually.")
    return 0


def cmd_providers_health(args: argparse.Namespace) -> int:
    from .healthcheck import render_health_table, run_healthcheck

    pool = Pool.from_default_config()
    provider_filter = args.providers.split(",") if args.providers else None
    rows = run_healthcheck(
        pool,
        model=args.model,
        providers=provider_filter,
        timeout=args.timeout,
    )
    print(render_health_table(rows))
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    import json

    catalog = _runtime_catalog()
    configured = {p.id for p in configured_providers(catalog)}
    conformance = ConformanceStore()
    conformance_snapshot = conformance.snapshot()
    only = set(args.providers.split(",")) if args.providers else None
    if args.json:
        rows = []
        keyless_configured = any(
            provider.keyless and provider.id in configured for provider in catalog
        )
        for provider in catalog:
            if (only is not None and provider.id not in only) or (
                args.configured_only and provider.id not in configured
            ):
                continue
            for model in provider.models:
                if not model.enabled and not args.all:
                    continue
                evidence = conformance.evidence(
                    provider,
                    model.name,
                    snapshot=conformance_snapshot,
                )
                rows.append(
                    {
                        "provider": provider.id,
                        "model": model.name,
                        "enabled": model.enabled,
                        "configured": provider.id in configured,
                        "capabilities": evidence,
                        "verified_features": sorted(
                            feature
                            for feature, result in evidence.items()
                            if result.get("status") == "pass"
                        ),
                        }
                    )
        if keyless_configured and (only is None or "sparrow" in only):
            rows.extend(
                {
                    "provider": "sparrow",
                    "model": model.name,
                    "enabled": True,
                    "configured": True,
                    "virtual": True,
                    "description": model.description,
                }
                for model in VIRTUAL_MODELS
            )
        print(json.dumps(rows, separators=(",", ":")))
        return 0

    shown = 0
    keyless_configured = any(
        provider.keyless and provider.id in configured for provider in catalog
    )
    if keyless_configured and (only is None or "sparrow" in only):
        print("\nSparrow virtual models")
        for model in VIRTUAL_MODELS:
            shown += 1
            print(f"    {model.name}  ({model.description})")
    for p in catalog:
        if only is not None and p.id not in only:
            continue
        if args.configured_only and p.id not in configured:
            continue
        keyless = ""
        if p.keyless and p.id in configured and not p.label.lower().endswith("(keyless)"):
            keyless = " (keyless)"
        print(f"\n{p.label}{keyless}")
        for m in p.models:
            if not m.enabled and not args.all:
                continue
            shown += 1
            tag = "  (off by default)" if not m.enabled else ""
            print(f"    {p.id}/{m.name}{tag}")
    if shown == 0:
        print("No models match. Try `sparrow providers` to see configuration status.")
        return 0
    print(
        "\nPass any id above to `--model`, e.g. "
        f'`sparrow ask -m {catalog[0].id}/{catalog[0].models[0].name} "hi"`,'
    )
    print("or just `--model <model-name>` to use that model on any provider that has it.")
    return 0


def cmd_quota(args: argparse.Namespace) -> int:
    store = QuotaStore()
    snap = store.snapshot()
    if not snap:
        print("No usage recorded today (UTC).")
        return 0
    print("Today's usage (UTC):")
    for key, count in sorted(snap.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  {key}")
    return 0


def _format_capacity_row(row) -> str:
    quota = "?" if row.quota_hint <= 0 else str(row.quota_hint)
    key = "keyless" if row.keyless else (row.key_env or "-")
    expiry = f" expires={row.expires_at}" if row.expires_at else ""
    return (
        f"  {row.status:<11} {row.provider_id:<13} {row.label:<28} "
        f"used={row.used_today}/{quota:<5} models={row.enabled_models:<3} "
        f"key={key}{expiry}  {row.reason}"
    )


def cmd_keys_status(args: argparse.Namespace) -> int:
    from .capacity import build_capacity_report
    from .credential_cli import render_status
    from .credential_store import CredentialStore
    from .key_inventory import default_config_path, default_inventory_path, load_inventory

    inventory_path = default_inventory_path()
    inventory = load_inventory(inventory_path)
    report = build_capacity_report(target=args.target, inventory=inventory)
    print(f"Key inventory: {inventory_path}")
    print(f"Records: {len(inventory)}")
    print(f"Healthy providers: {report.healthy_count}/{args.target}\n")
    for row in report.providers:
        if args.all or row.status != "missing":
            print(_format_capacity_row(row))
    print("\nCredential slots:")
    try:
        print(render_status(default_config_path(), CredentialStore()))
    except ValueError as exc:
        print(f"Credential status unavailable: {exc}", file=sys.stderr)
    return 0


def cmd_keys_usage(args: argparse.Namespace) -> int:
    from .credential_cli import render_usage
    from .credential_store import CredentialStore
    from .key_inventory import default_config_path

    print(
        render_usage(
            CredentialStore(),
            provider=args.provider,
            day=args.day,
            as_json=args.json,
            config_path=default_config_path(),
        )
    )
    return 0


def cmd_keys_checklist(args: argparse.Namespace) -> int:
    from .capacity import build_capacity_report
    from .key_inventory import load_inventory

    report = build_capacity_report(target=args.target, inventory=load_inventory())
    todo = report.checklist()
    if not todo:
        print(f"Enough healthy providers: {report.healthy_count}/{args.target}.")
        return 0
    print(f"Manual key checklist to reach {args.target} healthy providers:")
    for row in todo:
        print(f"  - {row.provider_id}: create a key manually, then set {row.key_env}")
    return 0


def _choose_provider(catalog, provider_id: str | None):
    providers = [p for p in catalog if p.key_env]
    if provider_id:
        needle = provider_id.lower()
        matches = [p for p in providers if p.id.lower() == needle or p.label.lower() == needle]
        if not matches:
            raise SystemExit(
                f"provider is not configured in local providers.toml, or is keyless/external-only: {provider_id}"
            )
        return matches[0]

    print("Choose a provider to configure:")
    for i, provider in enumerate(providers, start=1):
        print(f"  {i}. {provider.id} ({provider.key_env})")

    while True:
        raw = input("Provider number or id: ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(providers):
                return providers[idx - 1]

        for provider in providers:
            if provider.id == raw:
                return provider

        print("Invalid provider, try again.")


def _yes(raw: str) -> bool:
    return raw.strip().lower() in {"y", "yes"}


def _load_or_sync_external_catalog():
    from .catalog import load_external_catalog, sync_external_catalog

    external = load_external_catalog()
    if external:
        return external
    try:
        _, external = sync_external_catalog()
    except Exception:                                                             
        return []
    return external


def _import_or_create_provider(provider_name: str, args: argparse.Namespace) -> str | None:
    from .catalog import (
        create_user_provider_stub,
        discover_openai_models,
        import_external_provider_to_user_catalog,
        suggest_external_provider,
    )

    external = _load_or_sync_external_catalog()
    suggestion = suggest_external_provider(provider_name, external)
    if suggestion:
        provider_slug = suggestion.provider.slug.replace("-", "_")
        query_slug = provider_name.lower().replace("_", "-")
        is_exact_provider = suggestion.exact and query_slug in {
            suggestion.provider.slug,
            provider_slug,
        }
        if is_exact_provider or (
            not args.yes
            and _yes(
                input(
                    f"Provider not found. Use external match "
                    f"{suggestion.provider.name} (matched {suggestion.matched})? [y/N] "
                )
            )
        ):
            local_id = import_external_provider_to_user_catalog(suggestion.provider.name)
            print(
                f"Imported external provider '{suggestion.provider.name}' as local provider '{local_id}'."
            )
            return local_id

    if args.yes and not args.base_url:
        print(
            "Provider not found. Pass --base-url to create it non-interactively.", file=sys.stderr
        )
        return None

    if not args.yes and not _yes(
        input(f"Provider '{provider_name}' not found. Create it manually? [y/N] ")
    ):
        return None

    base_url = args.base_url or input("OpenAI-compatible API base URL: ").strip()
    model = args.model or ("" if args.yes else input("Default model id (blank to autodiscover): ").strip())
    if not model:
        api_key = getattr(args, "value", None)
        if not api_key and not args.yes:
            import getpass

            api_key = getpass.getpass("API key for model discovery (blank if not needed): ").strip()
            if api_key:
                args.value = api_key
        try:
            models = discover_openai_models(base_url, api_key=api_key or None)
        except ValueError as exc:
            print(f"Could not autodiscover models: {exc}", file=sys.stderr)
            models = []
        model = _choose_discovered_model(models, args)
        if not model and not args.yes:
            model = input("Default model id: ").strip()
    if not model:
        print("Could not determine a default model for the provider.", file=sys.stderr)
        return None
    try:
        local_id = create_user_provider_stub(name=provider_name, base_url=base_url, model=model)
    except ValueError as exc:
        print(f"Could not create provider: {exc}", file=sys.stderr)
        return None
    print(f"Created local provider '{local_id}' in user providers.toml.")
    return local_id


def _choose_discovered_model(models: list[str], args: argparse.Namespace) -> str | None:
    if not models:
        return None
    if len(models) == 1 or args.yes:
        print(f"Discovered model: {models[0]}")
        return models[0]
    print("Discovered models:")
    for i, model in enumerate(models[:10], start=1):
        print(f"  {i}. {model}")
    raw = input("Model number or id: ").strip()
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= min(len(models), 10):
            return models[idx - 1]
    if raw in models:
        return raw
    return None


def cmd_keys_add(args: argparse.Namespace) -> int:
    import getpass
    from datetime import date

    from .config import load_catalog, load_config_file
    from .credential_cli import register_credential, set_config_keys
    from .key_inventory import (
        KeyRecord,
        append_inventory_record,
        default_config_path,
        upsert_config_key,
    )

    if getattr(args, "provider_arg", None) and not args.provider:
        args.provider = args.provider_arg
    try:
        catalog = load_catalog()
    except FileNotFoundError:
        catalog = []
    try:
        provider = _choose_provider(catalog, args.provider)
    except SystemExit:
        if not args.provider:
            raise
        local_id = _import_or_create_provider(args.provider, args)
        if not local_id:
            return 3
        provider = _choose_provider(load_catalog(), local_id)

    primary_env_var = args.env_var or provider.key_env
    if not primary_env_var:
        print(f"Provider {provider.id} has no key environment variable.", file=sys.stderr)
        return 3
    value = getpass.getpass(f"Paste {primary_env_var}: ").strip()

    if not value:
        print("No value provided.", file=sys.stderr)
        return 3

    existing_keys = load_config_file().get("keys", {})
    known_env = {str(k): str(v) for k, v in existing_keys.items() if v}
    known_env.update(os.environ)
    extra_values: dict[str, str] = {}
    for env_var in provider.extra_env:
        if known_env.get(env_var):
            continue
        extra_value = getpass.getpass(f"Paste {env_var}: ").strip()
        if not extra_value:
            print(f"No value provided for {env_var}.", file=sys.stderr)
            return 3
        extra_values[env_var] = extra_value

    if not args.yes:
        names = [primary_env_var, *extra_values]
        answer = input(f"Write {', '.join(names)} to {default_config_path()}? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    if args.credential_id:
        config_path = register_credential(
            default_config_path(),
            provider=provider.id,
            credential_id=args.credential_id,
            env_var=primary_env_var,
            quota_group=args.quota_group or "shared",
            secret=value,
            enabled=not args.disabled,
        )
    else:
        config_path = upsert_config_key(primary_env_var, value)
    if extra_values:
        if args.credential_id:
            config_path = set_config_keys(config_path, extra_values)
        else:
            for env_var, extra_value in extra_values.items():
                config_path = upsert_config_key(env_var, extra_value)

    written_names = [str(primary_env_var), *extra_values]
    inventory_path = append_inventory_record(
        KeyRecord(
            provider=provider.id,
            env_var=primary_env_var,
            label=args.label or "manual",
            created_at=date.today().isoformat(),
            commercial_allowed=args.commercial_allowed,
            notes=args.notes or "added with sparrow keys add",
        )
    )

    print(f"Added {provider.id} key metadata.")
    print(f"Wrote: {', '.join(written_names)}")
    print(f"Config: {config_path}")
    print(f"Inventory: {inventory_path}")
    unlocked = sum(1 for model in provider.models if model.enabled)
    suffix = "route" if unlocked == 1 else "routes"
    print(f"Unlocked {unlocked} enabled model {suffix} for {provider.label}.")
    print("Next command:")
    print("  sparrow providers health -p " + provider.id)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .cache import default_cache_path, default_max_entries
    from .catalog import default_external_catalog_path, load_external_catalog
    from .catalog_validation import validate_catalog
    from .config import config_diagnostics, effective_env, settings
    from .key_inventory import default_config_path

    env = effective_env()
    cfg = settings()
    catalog = load_catalog()
    configured = configured_providers(catalog, env)
    pool = Pool.from_default_config()
    quota_path = pool.quota.path
    cache_path = default_cache_path()
    external_path = default_external_catalog_path()
    external = load_external_catalog(external_path)
    config_issues = config_diagnostics()
    external_note = "missing"
    if external_path.exists():
        import time

        age_hours = max(0.0, (time.time() - external_path.stat().st_mtime) / 3600.0)
        external_note = f"{age_hours:.1f}h old"
        if age_hours > 24 * 7:
            external_note += ", stale"
    errors = validate_catalog()

    print(f"sparrow {__version__}")
    print(f"python: {sys.version.split()[0]}")
    print(f"config: {default_config_path()}")
    print(f"providers: {len(configured)}/{len(catalog)} configured")
    print(f"routing: {pool.routing}")
    print(f"quota: {quota_path} ({'exists' if quota_path.exists() else 'new'})")
    cache_ttl = env.get("SPARROW_CACHE_TTL") or cfg.get("cache_ttl", 0)
    print(f"cache: {cache_path} ttl={cache_ttl} max={default_max_entries()}")
    print(
        f"external catalog: {external_path} "
        f"({len(external)} cached provider{'s' if len(external) != 1 else ''}, {external_note})"
    )
    if config_issues:
        print("config validation: FAIL")
        for issue in config_issues[:20]:
            location = ""
            if issue.get("line") is not None:
                location += f" line={issue['line']}"
            if issue.get("column") is not None:
                location += f" column={issue['column']}"
            print(f"  - {issue.get('code', 'invalid_config')}{location}: {issue['message']}")
        if len(config_issues) > 20:
            print(f"  ... {len(config_issues) - 20} more")
    else:
        print("config validation: ok")
    if errors:
        print("catalog: FAIL")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more")
        return 1
    print("catalog: ok")
    return 1 if config_issues else 0


def cmd_start(args: argparse.Namespace) -> int:
    from .proxy import serve                                                  
    from .tailnet import (
        SetupTokenLabel,
        UnsafeBindError,
        assert_bind_safe,
        format_setup_hints,
        is_loopback_host,
        safe_base_url,
    )

                                                                                    
    if getattr(args, "tailnet", False):
        return _run_tailnet_serve(
            port=args.port,
            api_key=args.api_key,
            allow_lan=getattr(args, "allow_lan", False),
            allow_no_auth=getattr(args, "allow_no_auth", False),
            dry_run=False,
        )

    proxy_key = (
        args.api_key
        or os.environ.get("SPARROW_PROXY_KEY")
        or settings().get("proxy_key")
        or None
    )

                                                                     
                                                                    
                                                                       
                                                                 
    try:
        assert_bind_safe(
            host=args.host,
            api_key=proxy_key,
            allow_lan=getattr(args, "allow_lan", False),
            allow_no_auth=getattr(args, "allow_no_auth", False),
        )
    except UnsafeBindError as exc:
        print(f"sparrow: {exc}", file=sys.stderr)
        return 2

    host = str(args.host)
    loopback = is_loopback_host(host)
    if not loopback and not proxy_key:
                                                                             
                                                                            
                                                                      
        print(
            f"sparrow: WARNING — binding to {host} (not loopback) with NO proxy key "
            "exposes all your configured providers to the network. Set --api-key or "
            "SPARROW_PROXY_KEY, or bind to 127.0.0.1.",
            file=sys.stderr,
        )

    pool = Pool.from_default_config()
    if not pool.providers:
        print(
            "sparrow: no providers configured; set at least one API key "
            "(run `sparrow keys add <provider>` or configure a key manually).",
            file=sys.stderr,
        )
        return 3

    httpd = serve(pool, host=host, port=args.port, api_key=proxy_key)
    n_models = sum(len(p.models) for p in pool.providers)
    auth_enabled = proxy_key is not None
    auth_note = "  auth: Bearer key required\n" if auth_enabled else ""
    base_url = safe_base_url(host, args.port)
    print(
        f"sparrow start on {base_url}/v1  "
        f"({len(pool.providers)} providers, {n_models} models)\n"
        f"{auth_note}"
        f"  point your OpenAI client at:  OPENAI_BASE_URL={base_url}/v1\n"
        f"  dashboard:  {base_url}/dashboard\n"
        f"{format_setup_hints(base_url=base_url, auth_enabled=auth_enabled, token_label=SetupTokenLabel.YOUR_PROXY_KEY)}"
        "  press Ctrl-C to stop",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        s = pool.stats_snapshot()
        saved = format_saved(s["prompt_tokens"], s["completion_tokens"])
        print(
            f"\nsparrow: shutting down — served {s['requests']} requests · {saved}",
            file=sys.stderr,
        )
    finally:
        try:
            pool.flush()
        finally:
            httpd.server_close()
    return 0


def _run_tailnet_serve(
    *,
    port: int,
    api_key: str | None,
    allow_lan: bool,
    allow_no_auth: bool,
    dry_run: bool,
) -> int:
                                                                           

    from .proxy import serve                                                  
    from .tailnet import (
        STATE_CLI_MISSING,
        STATE_LOGGED_OUT,
        STATE_MALFORMED,
        STATE_NO_IPV4,
        SetupTokenLabel,
        UnsafeBindError,
        _disclose_session_token_to_tty,
        _NonTTYDisclosureError,
        assert_bind_safe,
        detect_tailnet,
        format_setup_hints,
        generate_session_token,
        safe_base_url,
    )

    status = detect_tailnet()
    if not status.usable:
                                                                       
                                                                        
                                                                     
                            
        if status.state == STATE_CLI_MISSING:
            print(
                "sparrow: cannot start Tailnet serving — "
                f"{status.detail}",
                file=sys.stderr,
            )
        elif status.state == STATE_LOGGED_OUT:
            print(
                "sparrow: cannot start Tailnet serving — "
                f"{status.detail}",
                file=sys.stderr,
            )
        elif status.state == STATE_NO_IPV4:
            print(
                "sparrow: cannot start Tailnet serving — "
                f"{status.detail}",
                file=sys.stderr,
            )
        elif status.state == STATE_MALFORMED:
            print(
                "sparrow: cannot start Tailnet serving — "
                f"{status.detail}",
                file=sys.stderr,
            )
        else:                                
            print(
                "sparrow: cannot start Tailnet serving — "
                f"unknown Tailscale state: {status.state}",
                file=sys.stderr,
            )
        print(
            "\nHint: `sparrow start` on loopback (127.0.0.1) still works "
            "without Tailscale.",
            file=sys.stderr,
        )
        return 3

                                                                       
                                                                      
    explicit_key = (
        api_key
        or os.environ.get("SPARROW_PROXY_KEY")
        or settings().get("proxy_key")
        or None
    )

    bind_host = status.ipv4
    if bind_host is None:
        print(
            "sparrow: cannot start Tailnet serving — no validated Tailnet IPv4 found",
            file=sys.stderr,
        )
        return 3

                                                                     
                                                                      
                            
    needs_session_token = explicit_key is None and not allow_no_auth
    if (
        needs_session_token
        and not dry_run
        and not bool(getattr(sys.stderr, "isatty", lambda: False)())
    ):
        print(
            "sparrow: refusing to print an auto-generated proxy key in a "
            "non-interactive session. Pass --api-key, set "
            "SPARROW_PROXY_KEY, or run from an interactive terminal.",
            file=sys.stderr,
        )
        return 2

    if needs_session_token:
                                                                        
                                                                     
                                                                      
                                                   
        explicit_key = generate_session_token()
        generated_session_token = True
    else:
        generated_session_token = False

    try:
        assert_bind_safe(
            host=bind_host,
            api_key=explicit_key,
            allow_lan=allow_lan,
            allow_no_auth=allow_no_auth,
        )
    except UnsafeBindError as exc:
        print(f"sparrow: {exc}", file=sys.stderr)
        return 2

    base_url = safe_base_url(bind_host, port)
    if generated_session_token:
        token_label = (
            SetupTokenLabel.SESSION_REAL_RUN
            if dry_run
            else SetupTokenLabel.SESSION_DISCLOSED
        )
    elif explicit_key:
        token_label = SetupTokenLabel.YOUR_PROXY_KEY
    else:
        token_label = SetupTokenLabel.PROXY_KEY
    auth_enabled = explicit_key is not None
    setup_block = format_setup_hints(
        base_url=base_url,
        auth_enabled=auth_enabled,
        token_label=token_label,
    )
    auth_status = (
        "Bearer key required (token generated for this session)"
        if generated_session_token
        else (
            "Bearer key required (using --api-key / SPARROW_PROXY_KEY)"
            if auth_enabled
            else "no auth (--allow-no-auth)"
        )
    )

    if dry_run:
                                                                      
                                                                      
                                                                        
        marker = token_label.value if auth_enabled else "<none>"
        print(
            f"sparrow Tailnet serving (dry run)\n"
            f"  bind host      : {bind_host}\n"
            f"  bind URL       : {base_url}/v1\n"
            f"  dashboard      : {base_url}/dashboard\n"
            f"  auth status    : {auth_status}\n"
            f"  token marker   : {marker}\n"
            f"\n{setup_block}",
            file=sys.stderr,
        )
        return 0

    pool = Pool.from_default_config()
    if not pool.providers:
        print(
            "sparrow: no providers configured; set at least one API key "
            "(run `sparrow keys add <provider>` or configure a key manually).",
            file=sys.stderr,
        )
        return 3

    if generated_session_token:
                                                                            
        if explicit_key is None:                                          
            print("sparrow: failed to generate a one-session proxy key.", file=sys.stderr)
            return 2
        try:
            _disclose_session_token_to_tty(explicit_key, stream=sys.stderr)
        except _NonTTYDisclosureError:
            print(
                "sparrow: refusing to disclose an auto-generated proxy key "
                "without an interactive terminal.",
                file=sys.stderr,
            )
            return 2

    httpd = serve(pool, host=bind_host, port=port, api_key=explicit_key)
    n_models = sum(len(p.models) for p in pool.providers)
    print(
        f"sparrow Tailnet serving on {base_url}/v1  "
        f"({len(pool.providers)} providers, {n_models} models)\n"
        f"  auth status    : {auth_status}\n"
        f"  bind address   : {bind_host} (Tailnet IPv4)\n"
        f"\n{setup_block}"
        "  press Ctrl-C to stop",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        s = pool.stats_snapshot()
        saved = format_saved(s["prompt_tokens"], s["completion_tokens"])
        print(
            f"\nsparrow: shutting down — served {s['requests']} requests · {saved}",
            file=sys.stderr,
        )
    finally:
        try:
            pool.flush()
        finally:
            httpd.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sparrow",
        description="Pool free-tier LLM APIs behind one OpenAI-compatible endpoint.",
    )
    parser.add_argument("--version", action="version", version=f"sparrow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="one-shot completion")
    p_ask.add_argument("prompt", nargs="?", default="", help="prompt text (stdin is appended)")
    p_ask.add_argument("-s", "--system", help="system prompt")
    p_ask.add_argument(
        "-m", "--model", help="model name, or provider/model (e.g. groq/llama-3.3-70b-versatile)"
    )
    p_ask.add_argument("-p", "--providers", help="comma-separated provider ids to allow")
    p_ask.add_argument(
        "--max-tokens", type=int, default=None, help="max output tokens (default: 1024, or the role's default)"
    )
    p_ask.add_argument(
        "--temperature", type=float, default=None, help="sampling temperature (default: 0.0, or the role's default)"
    )
    p_ask.add_argument("--timeout", type=float, default=90.0, help="upstream provider timeout seconds")
    p_ask.add_argument("-r", "--role", help="use a role preset")
    p_ask.add_argument(
        "--routing", choices=PUBLIC_ROUTING_ALIASES, help="routing mode override (auto uses the pool default)"
    )
    p_ask.add_argument(
        "--task", choices=TASK_HINTS, help="task hint for quality routing (auto classifies locally)"
    )
    p_ask.add_argument(
        "--mode", choices=["normal", "wise"], help="per-command quota mode override (default: SPARROW_MODE or config)"
    )
    p_ask.add_argument(
        "--second-opinion", action="store_true", help="ask a small panel of diverse free models instead of one model"
    )
    p_ask.add_argument("--opinions", type=int, default=3, help="number of models for --second-opinion (clamped to 2-5)")
    p_ask.add_argument("--synthesize", action="store_true", help="append a quality-routed synthesis for --second-opinion")
    p_ask.add_argument("--json", action="store_true", help="ask for JSON output and strip code fences")
    p_ask.add_argument("-v", "--verbose", action="store_true", help="report which provider served")
    p_ask.set_defaults(func=cmd_ask)

    p_prov = sub.add_parser("providers", help="list providers and configuration status")
    prov_sub = p_prov.add_subparsers(dest="providers_command")
    p_prov_health = prov_sub.add_parser("health", help="test configured providers with a tiny request")
    p_prov_health.add_argument("-m", "--model", help="pin one model name to test on every provider")
    p_prov_health.add_argument("-p", "--providers", help="comma-separated provider ids to test")
    p_prov_health.add_argument("--timeout", type=float, default=20.0, help="per-call timeout seconds")
    p_prov_health.set_defaults(func=cmd_providers_health)
    p_prov.set_defaults(func=cmd_providers)

    p_models = sub.add_parser("models", help="list every available provider/model id")
    p_models.add_argument("-p", "--providers", help="comma-separated provider ids to filter")
    p_models.add_argument("-c", "--configured-only", action="store_true", help="only show configured providers")
    p_models.add_argument("--all", action="store_true", help="include models that are off by default")
    p_models.add_argument("--json", action="store_true", help="emit a machine-readable JSON list")
    p_models.set_defaults(func=cmd_models)

    p_quota = sub.add_parser("quota", help="show today's per-provider usage")
    p_quota.set_defaults(func=cmd_quota)

    p_keys = sub.add_parser("keys", help="inspect manually configured provider keys")
    keys_sub = p_keys.add_subparsers(dest="keys_command", required=True)
    p_keys_status = keys_sub.add_parser("status", help="show key inventory and provider readiness")
    p_keys_status.add_argument("--target", type=int, default=5, help="desired healthy provider count")
    p_keys_status.add_argument("--all", action="store_true", help="include missing providers")
    p_keys_status.set_defaults(func=cmd_keys_status)
    p_keys_usage = keys_sub.add_parser("usage", help="show per-credential usage")
    p_keys_usage.add_argument("--provider")
    p_keys_usage.add_argument("--day")
    p_keys_usage.add_argument("--json", action="store_true")
    p_keys_usage.set_defaults(func=cmd_keys_usage)
    p_keys_checklist = keys_sub.add_parser("checklist", help="manual actions to reach target capacity")
    p_keys_checklist.add_argument("--target", type=int, default=5, help="desired healthy provider count")
    p_keys_checklist.set_defaults(func=cmd_keys_checklist)
    p_keys_add = keys_sub.add_parser("add", help="store a provider key and print newly unlocked model routes")
    p_keys_add.add_argument("provider_arg", nargs="?", help="provider id or external provider name")
    p_keys_add.add_argument("-p", "--provider")
    p_keys_add.add_argument("--id", dest="credential_id")
    p_keys_add.add_argument("--env-var")
    p_keys_add.add_argument("--quota-group")
    p_keys_add.add_argument("--disabled", action="store_true")
    p_keys_add.add_argument("--base-url", help="OpenAI-compatible base URL for a new provider")
    p_keys_add.add_argument("--model", help="default model id for a new provider")
    p_keys_add.add_argument("--label")
    p_keys_add.add_argument("--notes")
    p_keys_add.add_argument("--commercial-allowed", action="store_true")
    p_keys_add.add_argument("-y", "--yes", action="store_true")
    p_keys_add.set_defaults(func=cmd_keys_add)

    p_doctor = sub.add_parser("doctor", help="show local diagnostics without calling providers")
    p_doctor.set_defaults(func=cmd_doctor)

    p_start = sub.add_parser("start", help="run the OpenAI-compatible proxy server")
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--port", type=int, default=8080)
    p_start.add_argument("--api-key", default=None, help="require this Bearer token on requests (or set SPARROW_PROXY_KEY)")
    p_start.add_argument(
        "--tailnet", action="store_true", help="bind to the local 100.x Tailnet IPv4 and require auth"
    )
    p_start.add_argument(
        "--allow-lan", action="store_true", help="allow binding to a non-Tailnet LAN address (still requires auth unless --allow-no-auth)"
    )
    p_start.add_argument(
        "--allow-no-auth", action="store_true", help="explicit escape hatch: serve on a non-loopback bind with NO proxy key"
    )
    p_start.set_defaults(func=cmd_start)

    return parser


def main(argv: list[str] | None = None) -> int:
    from .observe import configure_logging_from_env

    configure_logging_from_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (EOFError, KeyboardInterrupt):
        print("\nsparrow: cancelled (no input)", file=sys.stderr)
        return 130


if __name__ == "__main__":                    
    raise SystemExit(main())
