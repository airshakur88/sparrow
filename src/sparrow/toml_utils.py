                                                                   

from __future__ import annotations

                                                                                
                                                                        
                                                                               
                                                                   
_TOML_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
}


def toml_escape(value: str) -> str:
    out = []
    for ch in value:
        mapped = _TOML_BASIC_ESCAPES.get(ch)
        if mapped is not None:
            out.append(mapped)
        elif ch != "\t" and (ch < "\x20" or ch == "\x7f"):
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def toml_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{toml_escape(str(value))}"'


def dump_simple_toml(data: dict[str, dict]) -> str:
    chunks = []
    for table, values in data.items():
        lines = [f"[{table}]"]
        for key, value in values.items():
            lines.append(f"{key} = {toml_value(value)}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + ("\n" if chunks else "")
