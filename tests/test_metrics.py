                                                                       

from __future__ import annotations

from sparrow.metrics import Metrics


def test_success_rate_and_totals():
    m = Metrics()
    m.record_success("p/x", 100.0)
    m.record_success("p/x", 200.0)
    m.record_failure("p/x", "boom")
    st = m.get("p/x")
    assert st.ok == 2
    assert st.fail == 1
    assert st.total == 3
    assert abs(st.success_rate - 2 / 3) < 1e-9


def test_ewma_smooths_latency():
    m = Metrics(alpha=0.5)
    m.record_success("p/x", 100.0)
    assert m.get("p/x").ewma_ms == 100.0
    m.record_success("p/x", 200.0)
                       
    assert m.get("p/x").ewma_ms == 150.0
    assert m.get("p/x").last_ms == 200.0


def test_failing_needs_samples_and_majority():
    m = Metrics()
    m.record_failure("p/x", "e")
    assert not m.failing("p/x")                   
    m.record_failure("p/x", "e")
    m.record_failure("p/x", "e")
    assert m.failing("p/x")               
                                            
    for _ in range(5):
        m.record_success("p/y", 50.0)
    m.record_failure("p/y", "e")
    assert not m.failing("p/y")


def test_score_unknown_sits_between_healthy_and_failing():
    m = Metrics()
    m.record_success("good/x", 100.0)                  
    m.record_failure("bad/x", "e")
    m.record_failure("bad/x", "e")
                                                                           
                                                
    assert m.score("good/x") < m.score("never/seen") < m.score("bad/x")


def test_snapshot_is_isolated_copy():
    m = Metrics()
    m.record_success("p/x", 10.0)
    snap = m.snapshot()
    snap["p/x"].ok = 999
    assert m.get("p/x").ok == 1                                         
