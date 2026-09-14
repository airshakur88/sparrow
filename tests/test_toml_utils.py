from __future__ import annotations

import tomllib

from sparrow.toml_utils import toml_escape


def test_toml_escape_basic():
    assert toml_escape('a"b\\c') == 'a\\"b\\\\c'


def test_toml_escape_control_chars_keep_toml_parseable():
                                                                                     
    raw = 'x"\n\r\tinjected = "y'
    rendered = f'v = "{toml_escape(raw)}"'
    assert tomllib.loads(rendered)["v"] == raw                                         
