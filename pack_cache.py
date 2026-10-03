"""
Keep a builder's per-source-PDF analysis on disk between runs.

Most of a chapter build is first-touch work on each source PDF: find_tables() over every
mark-scheme page, the question-number scan of every question paper, the /Rotate bake.
It comes out the same on every run unless the PDF or the code changes, and redoing it
made one 118-question chapter take 255 s instead of 44 s.

Values live in ~/.cache/papers_pack_cache/<tag>-<function>-<code hash>.pkl, keyed by the
PDF's real path, checked against its size and mtime. One file per hooked function: an
audit fix to, say, mark-scheme row detection must never be hidden behind rows found by the
code before it, but a fix to page layout must not throw the scans away either.

The code hash is the function's closure, worked out from the source with ast: its own
definition, plus every module-level definition (function, class, constant, regex, import)
it names, and so on transitively, across the project modules (the builder's folder:
every .py that the builder imports, directly or not, except this one). Names resolve
conservatively, since leaving one out hides a fix and taking one too many costs only a
cold build:
  - a bare name that is defined at module level is in;
  - poc.X, poc.sp.Y resolve through the import aliases to that module's X, Y;
  - any other attribute .X takes in every module-level X and every project class with a
    member X (the whole class), wherever they are.
Each definition is hashed as ast.dump, so comments and blank lines do not count; the
Python major.minor and the PyMuPDF version are hashed too.
ponytail: the ceiling. A closure cannot be trusted when names are reached dynamically or
rebound at run time, so the function falls back to a hash of every project file (as
before, never wrong) when a module it draws on uses globals()/vars()/eval/exec/__dict__/
getattr or setattr with a computed name/__import__/importlib/a star import, when it
passes a project module around as a value, or when the closure reaches a name that some
function rebinds (`global X`, or poc.X = ... in a function). The fallback and its reason
are printed to stderr. Still not seen: a function outside the closure MUTATING a
module-level object the closure reads (X.append in some layout function), and a test that
monkeypatches a helper at run time - such a test must run with PACK_CACHE=0.

Only a function of ONE source PDF (and of its code) may be hooked: nothing that reads
tags, By Topic files or question_bank.json, since those are not in the key.

PACK_CACHE=0 turns it off; hook() then hands every function back untouched.
PACK_CACHE_KEY=file keys as before this closure rule: one file per subject, sha1 over the
whole files passed to hook().
"""

import ast
import atexit
import hashlib
import os
import pickle
import sys
import time
from functools import lru_cache
from pathlib import Path

DIR = Path.home() / ".cache" / "papers_pack_cache"   # hidden: the desktop indexer skips it
KEEP = 200         # newest cache files kept, older ones deleted (one per subject, function and code
                   # version; parallel fixers' private code copies must not evict each other)
SAVE_EVERY = 60    # seconds; a killed build loses at most this much of its work
DYNAMIC = {"globals", "vars", "eval", "exec", "__import__", "importlib", "__dict__"}
_stores = {}       # cache file -> its state; functions keyed to one file share it
_said = set()
_projects = {}


def hook(tag, *code_files):
    """wrap(fn, memo): `fn(path)` with its in-process cache `memo` (keyed str(path)) gets
    the disk cache behind it. `tag` names the file (a subject); it may be a callable,
    read at first use, since the toolkit only learns its subject from argv. `code_files`
    are hashed whole only under PACK_CACHE_KEY=file; the closure finds its own files."""
    if os.environ.get("PACK_CACHE") == "0":
        return lambda fn, memo: fn

    def wrap(fn, memo):
        src, st = os.path.abspath(fn.__code__.co_filename), {}

        def store():
            if not st:
                try:
                    name = tag() if callable(tag) else tag
                except Exception:   # e.g. the Toolkit's ROOT.name before use_subject(): keys are real paths, so a
                    name = "untagged"   # shared file name is still correct
                st["s"] = _store(_cache_file(name, fn.__name__, src, code_files))
            return st["s"]

        def cached(path):
            key = str(path)
            if key in memo:
                return fn(path)
            real = os.path.realpath(path)
            try:
                s = os.stat(real)
            except OSError:
                return fn(path)         # let fn raise its own error, as it always did
            k, sig = (fn.__name__, real), (s.st_size, s.st_mtime_ns)
            sto = store()
            data = sto["data"]
            if k in data and data[k][0] == sig:
                memo[key] = data[k][1]
                return fn(path)
            out = fn(path)
            sto["new"][k] = data[k] = (sig, memo[key])
            sto["unsaved"] += 1
            if time.time() - sto["saved"] > SAVE_EVERY:
                _save(sto)
            return out
        return cached
    return wrap


def _cache_file(tag, fn, src, code_files):
    if os.environ.get("PACK_CACHE_KEY") == "file":     # the old keying: whole files, one file per subject
        return DIR / f"{tag}-{_sha_files(code_files)[:16]}.pkl"
    try:
        digest, _, _, why, files = closure(src, fn)
    except Exception as exc:    # never fail a build over the analysis: fall back to whole files
        digest, why, files = "", [f"analysis failed: {exc!r}"], [src]
    if why:
        digest = "f" + _sha_files(sorted({os.path.abspath(f) for f in [*files, *code_files]}))[:15]
        if fn not in _said:
            _said.add(fn)
            print(f"pack_cache: {fn} keyed on whole files ({'; '.join(why)})", file=sys.stderr)
    return DIR / f"{tag}-{fn}-{digest[:16]}.pkl"


def _sha_files(files):
    h = hashlib.sha1()
    for f in files:
        h.update(Path(f).read_bytes())
    return h.hexdigest()


def closure(src, name):
    """(sha1, {(module, name)}, {(module, first line, last line)}, why, project files) for
    function `name` defined at module level in file `src`. `why` lists what makes the
    closure untrustworthy; empty means the sha1 may key the cache."""
    mods, index = _project(src)
    seen, stmts, why, used = set(), {}, [], set()
    todo = [(Path(src).stem, name)]
    while todo:
        m, n = todo.pop()
        if (m, n) in seen or m not in mods:
            continue
        seen.add((m, n))
        mod = mods[m]
        if n in mod["rebound"]:
            why.append(f"{m}.{n} is rebound at run time")
        for st in mod["defs"].get(n, ()):
            used.add(m)
            stmts[(m, st.lineno)] = (m, st)
            inner = {id(a.value) for a in ast.walk(st) if isinstance(a, ast.Attribute)}
            for node in ast.walk(st):
                if id(node) in inner:
                    continue
                if isinstance(node, ast.Name):
                    if node.id in mod["alias"]:
                        why.append(f"module {node.id} used as a value in {m}")
                    todo.append((m, node.id))
                elif isinstance(node, ast.Attribute):
                    pairs, rest = _chain(mods, m, node)
                    if pairs and not rest and pairs[-1][1] in mods[pairs[-1][0]]["alias"]:
                        why.append(f"module {pairs[-1][1]} used as a value in {m}")
                    todo += pairs
                    for a in rest:
                        todo += index.get(a, [])
                elif isinstance(node, ast.ImportFrom) and node.module in mods:
                    todo += [(node.module, a.name) for a in node.names]
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id in ("getattr", "hasattr") and len(node.args) > 1
                      and isinstance(node.args[1], ast.Constant)):
                    todo += index.get(node.args[1].value, [])
    why += [w for m in sorted(used) for w in mods[m]["taint"]]
    h = hashlib.sha1(f"python {sys.version_info[:2]} pymupdf {_pymupdf()}".encode())
    for line in sorted(f"{m} {ast.dump(st)}" for m, st in stmts.values()):
        h.update(line.encode())
    spans = {(m, _start(st), st.end_lineno) for m, st in stmts.values()}
    members = {p for p in seen if p[1] in mods[p[0]]["defs"]}
    return h.hexdigest(), members, spans, sorted(set(why)), [mods[m]["path"] for m in sorted(mods)]


def _chain(mods, m, node):
    """poc.sp.f -> ([(builder, poc), (poc, sp), (split_papers, f)], []): the (module, name)
    pairs an attribute chain walks through the import aliases, and the attributes left."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return [], parts
    parts.insert(0, node.id)
    out = []
    for i, p in enumerate(parts):
        out.append((m, p))
        if p not in mods[m]["alias"]:
            return out, parts[i + 1:]
        m = mods[m]["alias"][p]
    return out, []


def _project(src):
    """{module: {path, defs, alias, rebound, taint}} for src's module and every module of its
    folder it imports, transitively; and {attribute name: [(module, definition)]}."""
    hit = _projects.get(src)    # the four hooks of one builder share one parse while the files are unchanged
    if hit and all(Path(p).read_bytes() == b for p, b in hit[0]):
        return hit[1]
    folder, mods, todo = os.path.dirname(os.path.abspath(src)), {}, [Path(src).stem]
    is_mod = lambda n: n and n != "pack_cache" and os.path.isfile(os.path.join(folder, f"{n}.py"))
    while todo:
        m = todo.pop()
        if m in mods:
            continue
        path = os.path.join(folder, f"{m}.py")
        text = Path(path).read_bytes()
        tree = ast.parse(text)
        mod = mods[m] = dict(path=path, text=text, tree=tree, defs={}, alias={}, rebound=set(), taint=[])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if is_mod(a.name):
                        mod["alias"][a.asname or a.name] = a.name
                        todo.append(a.name)
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    mod["taint"].append(f"star import in {m}")
                if node.level == 0 and is_mod(node.module):
                    todo.append(node.module)
            elif isinstance(node, ast.Global):
                mod["rebound"].update(node.names)
            elif (isinstance(node, ast.Name) and node.id in DYNAMIC) or \
                    (isinstance(node, ast.Attribute) and node.attr in DYNAMIC):
                mod["taint"].append(f"{getattr(node, 'id', None) or node.attr} in {m}")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("getattr", "setattr", "hasattr", "delattr")
                  and (len(node.args) < 2 or not isinstance(node.args[1], ast.Constant))):
                mod["taint"].append(f"{node.func.id} with a computed name in {m}")
        # module-level statements, each filed under every name it binds or changes
        # (X = .., import X, def X, X[k] = .., X.append(..)); the hook lines are not code
        hooks = set()
        for st in tree.body:
            names = _binds(st)
            if any(isinstance(n, ast.Name) and n.id in hooks | {"pack_cache"} or
                   isinstance(n, ast.alias) and n.name == "pack_cache" for n in ast.walk(st)):
                hooks |= names - {n for n in names if n in mod["defs"]}
                continue
            for n in names:
                mod["defs"].setdefault(n, []).append(st)
    index = {}
    for m, mod in mods.items():
        for n, sts in mod["defs"].items():
            index.setdefault(n, []).append((m, n))
            for st in sts:
                if isinstance(st, ast.ClassDef):
                    for k in set().union(*map(_binds, st.body)):
                        index.setdefault(k, []).append((m, st.name))
        for node in ast.walk(mod["tree"]):   # poc.X = .. anywhere: X is not what its source says
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                pairs, rest = _chain(mods, m, node)
                if pairs and not rest and len(pairs) > 1:
                    mods[pairs[-1][0]]["rebound"].add(pairs[-1][1])
    _projects[src] = ([(mod["path"], mod["text"]) for mod in mods.values()], (mods, index))
    return mods, index


def _binds(st):
    if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {st.name}
    out = set()
    effects = {id(n.value.func) for n in ast.walk(st)   # X.append(..) on a line of its own
               if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)}
    for n in ast.walk(st):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Attribute, ast.Subscript)) and (
                isinstance(n.ctx, (ast.Store, ast.Del)) or id(n) in effects):
            while isinstance(n, (ast.Attribute, ast.Subscript)):
                n = n.value
            if isinstance(n, ast.Name):
                out.add(n.id)
    return out


def _start(st):
    return min([st.lineno] + [d.lineno for d in getattr(st, "decorator_list", [])])


@lru_cache(maxsize=1)
def _pymupdf():
    try:
        from importlib.metadata import version
        return version("pymupdf")
    except Exception:
        return getattr(sys.modules.get("pymupdf"), "VersionBind", "?")


def _store(path):
    if path not in _stores:
        _stores[path] = dict(path=path, data=_load(path), new={}, unsaved=0, saved=time.time())
        atexit.register(_save, _stores[path])
        try:
            os.utime(path)      # in use: keep it off the pruning end of the list
        except OSError:
            pass
    return _stores[path]


def _save(st):
    # Merge into what is on disk now: two or three builders may share the file.
    # Last writer wins between two saves that overlap, which loses nothing but time.
    if not st["unsaved"]:
        return
    st["saved"] = time.time()
    try:
        data = _load(st["path"])
        data.update(st["new"])
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = st["path"].with_name(f"{st['path'].name}.{os.getpid()}.tmp")
        tmp.write_bytes(pickle.dumps(data, pickle.HIGHEST_PROTOCOL))
        os.replace(tmp, st["path"])
        st["unsaved"] = 0
    except Exception as exc:  # a full disk, an unwritable dir, anything: this runs inside a hooked call,
        # so an exception here would surface in build_chapter and become a SKIP of a correctly built entry
        print(f"pack_cache: not saved ({exc!r})", file=sys.stderr)
        return
    try:                    # stale code versions, and temp files of killed builds
        old = sorted(DIR.glob("*.pkl"), key=os.path.getmtime, reverse=True)[KEEP:]
        old += [t for t in DIR.glob("*.tmp") if time.time() - os.path.getmtime(t) > 3600]
        for p in old:
            p.unlink(missing_ok=True)
    except Exception:       # another builder renamed or pruned one first: next time
        pass


def _load(path):
    # Only ever a file this module wrote into the user's own cache, so unpickling is safe.
    try:
        return pickle.loads(path.read_bytes())
    except Exception:           # missing, or unreadable: start empty rather than fail a build
        return {}
