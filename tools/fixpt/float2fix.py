"""float -> 16.16 fixed-point source transform for C homebrew sources.

Rewrites C files so they compile as C++ against tools/fixpt/fix16.hpp:
  * `float` / `double` -> `fix16`;
  * floating literals -> FIX16_RAW(<rounded value * 65536>) (no float at run time);
  * identifiers that are C++ keywords (`this`, `new`, `class`, ...) are renamed.
Strings, character constants and comments are left alone. The game's number model
changes from IEEE single to 16.16 fixed (the native model of PICO-8 games).

Usage: python -m tools.fixpt.float2fix OUT_DIR file.c [file.c ...]
"""
import os
import re
import sys

CXX_KW = {"this", "new", "delete", "class", "template", "typename", "private", "public",
          "protected", "namespace", "operator", "friend", "virtual", "throw", "try",
          "catch", "using", "explicit", "mutable", "export"}
LIT = re.compile(r"(?<![\w.])((?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)([fFlL]?)(?![\w.])")
WORD = re.compile(r"\b[A-Za-z_]\w*\b")
# strings, chars, comments, preprocessor #include lines
SKIP = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*|^\s*#\s*include[^\n]*',
                  re.S | re.M)


def fix_literal(m):
    v = float(m.group(1))
    return f"FIX16_RAW({int(round(v * 65536))})"


def fix_word(m):
    w = m.group(0)
    if w in ("float", "double"):
        return "fix16"
    if w in CXX_KW:
        return w + "_"
    return w


def _split_ternary(t):
    """(cond, a, b) if t has a ?: at paren depth 0, else None."""
    d, q = 0, None
    for i, ch in enumerate(t):
        if ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
        elif d == 0 and ch == "?" and q is None:
            q = i
        elif d == 0 and ch == ":" and q is not None:
            return t[:q], t[q + 1:i], t[i + 1:]
    return None


def fix_ternaries(t):
    """Rewrite every `c ? a : b` (innermost paren groups first) to FIX16_TERN(c, a, b),
    which converts both arms to the common type (fix16 wins over integers)."""
    out, i = [], 0
    while i < len(t):
        if t[i] == "(":
            d, j = 1, i + 1
            while j < len(t) and d:
                d += {"(": 1, ")": -1}.get(t[j], 0)
                j += 1
            out.append("(" + fix_ternaries(t[i + 1:j - 1]) + ")")
            i = j
        else:
            out.append(t[i])
            i += 1
    t = "".join(out)
    s = _split_ternary(t)
    if s and "#" not in t:
        c, a, b = s
        return f" FIX16_TERN({c.strip()}, {a.strip()}, {fix_ternaries(b).strip()})"
    return t


DEFINE = re.compile(r"^(\s*#\s*define\s+\w+(?:\([^)]*\))?\s)(.*)$", re.M)


def transform_code(code):
    code = LIT.sub(fix_literal, code)
    code = DEFINE.sub(lambda m: m.group(1) + fix_ternaries(m.group(2)), code)
    return WORD.sub(fix_word, code)


def transform(src):
    out, pos = [], 0
    for m in SKIP.finditer(src):
        out.append(transform_code(src[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(transform_code(src[pos:]))
    return '#include "fix16.hpp"\n' + "".join(out)


def main(argv):
    od = argv[0]
    os.makedirs(od, exist_ok=True)
    for f in argv[1:]:
        dst = os.path.join(od, os.path.basename(f))
        if dst.endswith(".c"):
            dst = dst[:-2] + ".cpp"
        open(dst, "w").write(transform(open(f).read()))
    for f in os.listdir(os.path.dirname(os.path.abspath(argv[1]))):
        if f.endswith(".h"):   # headers next to the sources are transformed too
            p = os.path.join(os.path.dirname(os.path.abspath(argv[1])), f)
            open(os.path.join(od, f), "w").write(transform(open(p).read()).split("\n", 1)[1])


if __name__ == "__main__":
    main(sys.argv[1:])
