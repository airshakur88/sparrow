from __future__ import annotations

import asyncio
import threading

from sparrow import client as client_module
from sparrow.aio import AsyncPool
from sparrow.credentials import CredentialSelection
from sparrow.router import Pool


def test_async_parity_uses_explicit_managed_secret_and_one_transport_call(providers, quota, tmp_path):
    provider = providers[0]
    del tmp_path

    class Manager:
        def reserve(self, provider_id, model, operation, **_kwargs):
            del operation
            return CredentialSelection(
                "primary", provider_id, "shared", "async-secret", "attempt", model
            )

    manager = Manager()
    calls: list[tuple[dict, dict]] = []

    async def apost(url, headers, body, timeout):
        del url, timeout
        calls.append((headers, body))
        return client_module.HTTPResult(
            200,
            {"choices": [{"message": {"content": "async ok"}}]},
            "",
        )

    async_pool = AsyncPool(
        Pool(
            [provider],
            env={},
            post=lambda *_args: client_module.HTTPResult(500, {}, ""),
            quota=quota,
            credential_manager=manager,  # type: ignore[arg-type]
        ),
        apost=apost,
    )

    reply = asyncio.run(async_pool.aask("hello", providers=["alpha"]))

    assert reply.text == "async ok"
    assert calls[0][0]["Authorization"] == "Bearer async-secret"
    assert calls[0][1]["model"] == "alpha-small"


def test_async_reservation_worker_finishes_before_cancellation(providers, quota):
    started = threading.Event()
    release = threading.Event()

    class Manager:
        def reserve(self, *_args, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return CredentialSelection(
                "primary", "alpha", "shared", "secret", "attempt", "generation"
            )

    async def run() -> None:
        async_pool = AsyncPool(
            Pool(
                [providers[0]],
                env={},
                post=lambda *_args: client_module.HTTPResult(500, {}, ""),
                quota=quota,
                credential_manager=Manager(),  # type: ignore[arg-type]
            ),
            apost=lambda *_args: _empty_async_result(),
        )
        task = asyncio.create_task(async_pool._reserve_credential(
            async_pool._pool.credential_manager, "alpha", "alpha-small", set(), 10.0
        ))
        await asyncio.to_thread(started.wait, 1)
        task.cancel()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert started.is_set()

    asyncio.run(run())


async def _empty_async_result():
    return client_module.HTTPResult(200, {"choices": []}, "")
