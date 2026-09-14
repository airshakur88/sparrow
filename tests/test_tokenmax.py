                                                                           

from __future__ import annotations

from helpers import make_post

from sparrow import tokenmax
from sparrow.router import Pool

MSGS = [{"role": "user", "content": "hi"}]


def _pool(providers, env, quota, post=None):
    return Pool(providers, quota=quota, env=env, post=post or make_post({}))


def test_select_targets_defaults_to_all(providers, env, quota):
    pool = _pool(providers, env, quota)
    picks, n_providers = tokenmax.select_targets(pool, MSGS)
    assert len(picks) >= 1
    assert n_providers == len({t.provider.id for t in picks})


def test_select_targets_respects_hard_cap(providers, env, quota, monkeypatch):
    monkeypatch.setattr(tokenmax, "HARD_CAP", 2)
    pool = _pool(providers, env, quota)
    picks, _ = tokenmax.select_targets(pool, MSGS)                                    
    assert len(picks) == 2


def test_select_targets_max_models_lowers(providers, env, quota):
    pool = _pool(providers, env, quota)
    picks, _ = tokenmax.select_targets(pool, MSGS, max_models=1)
    assert len(picks) == 1


def test_select_targets_interleaves_across_providers(providers, env, quota):
                                                                                        
    pool = _pool(providers, env, quota)
    picks, n_providers = tokenmax.select_targets(pool, MSGS)
    if n_providers >= 2:
        assert picks[0].provider.id != picks[1].provider.id


def test_fan_out_collects_answers_and_reports_progress(providers, env, quota):
    pool = _pool(providers, env, quota)
    picks, _ = tokenmax.select_targets(pool, MSGS)
    seen: list[tuple[int, int]] = []
    answered, failed = tokenmax.fan_out(
        pool, MSGS, picks, max_tokens=50, progress=lambda d, t, _l: seen.append((d, t))
    )
    assert answered                                        
    assert len(answered) + len(failed) == len(picks)                             
    assert len(seen) == len(picks)                                                    
    assert max(done for done, _total in seen) == len(picks)                                
    assert all(total == len(picks) for _done, total in seen)


def test_fan_out_surfaces_failures(providers, env, quota):
                                                                                   
    post = make_post({"alpha.test": (500, {})})
    pool = _pool(providers, env, quota, post=post)
    picks, _ = tokenmax.select_targets(pool, MSGS)
    answered, failed = tokenmax.fan_out(pool, MSGS, picks, max_tokens=50)
    assert any(lbl.startswith("alpha/") for lbl in failed)


def test_rainbow_throb_non_tty_is_plain(capsys):
                                                                                   
                                                 
    with tokenmax.RainbowThrob("X"):
        pass
    err = capsys.readouterr().err
    assert "X" in err
    assert "\033[" not in err                                  
