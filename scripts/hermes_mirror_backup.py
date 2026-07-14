#!/usr/bin/env python3
"""
hermes-mirror backup script.
Mirrors the Hermes home (/opt/data) into a git repo, EXCLUDING ephemeral,
runtime, and sensitive files. Redacts config.yaml. Content-scans every file
that would be kept; aborts if a credential appears in a kept file.

Re-run safe (used by both the initial push and the daily cron job).
"""
import os, re, sys, shutil, fnmatch, subprocess, datetime

SRC = "/opt/data"
DST = "/opt/data/code/hermes-mirror"
EXCLUDES_FILE = "/opt/data/.secrets/mirror-excludes.txt"

# Files we deliberately keep but must transform (never copied verbatim).
REDACT_FILES = {"config.yaml"}

# Credential content signature (per user's spec).
CRED_RE = re.compile(r"api[_-]?key|secret|password|token", re.I)
# Value that looks like a real secret assignment: key: "long-ish value"
SECRET_ASSIGN_RE = re.compile(
    r'(?im)^(\s*[\w.\-]*(?:api[_-]?key|secret|password|token|access[_-]?key)[\w.\-]*\s*[:=]\s*)'
    r'(["\']?)([^"\'\s#][^"\'\n#]{6,})(\2)'
)

# High-confidence signatures of a REAL live credential (these hard-abort).
# Placeholders / var names / doc examples must NOT match here.
REAL_SECRET_RE = re.compile(
    r'(sk-[A-Za-z0-9]{20,}'
    r'|ghp_[A-Za-z0-9]{30,}'
    r'|gho_[A-Za-z0-9]{30,}'
    r'|github_pat_[A-Za-z0-9_]{60,}'
    r'|xai-[A-Za-z0-9]{20,}'
    r'|AIza[A-Za-z0-9_\-]{30,}'
    r'|xox[baprs]-[A-Za-z0-9-]{20,}'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})'
)
# Obvious non-secret markers that neutralize a SECRET_ASSIGN_RE hit.
PLACEHOLDER_RE = re.compile(
    r'x{3,}|\.\.\.|<[^>]+>|your[_-]|_here|example|placeholder|dummy|redacted'
    r'|\$\{|\$\(|env\[|os\.environ|getenv|process\.env|:-\}|:-\"',
    re.I,
)

def load_excludes():
    pats = []
    with open(EXCLUDES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pats.append(line)
    return pats

def is_excluded(relpath, is_dir, patterns):
    # relpath uses forward slashes, relative to SRC. Match each path segment
    # and the full path against gitignore-ish patterns.
    name = os.path.basename(relpath.rstrip("/"))
    candidates = [relpath, relpath + "/", name]
    # also test each ancestor dir with trailing slash (e.g. "sessions/")
    parts = relpath.split("/")
    for i in range(len(parts)):
        candidates.append("/".join(parts[: i + 1]) + "/")
    for pat in patterns:
        p = pat.rstrip("/")
        for c in candidates:
            if fnmatch.fnmatch(c, pat) or fnmatch.fnmatch(c, p) or fnmatch.fnmatch(c.rstrip("/"), p):
                return True
    return False

def redact(text):
    n = [0]
    def repl(m):
        n[0] += 1
        return f"{m.group(1)}{m.group(2)}<REDACTED>{m.group(4)}"
    return SECRET_ASSIGN_RE.sub(repl, text), n[0]

def is_texty(path):
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except Exception:
        return False

def main():
    patterns = load_excludes()
    os.makedirs(DST, exist_ok=True)

    kept, redacted_files, leaks = [], [], []

    # 1) Wipe DST contents (except .git and repo-meta files) so deletions
    #    in the source propagate, but README/.gitignore survive each run.
    PRESERVE = {".git", "README.md", ".gitignore"}
    for entry in os.listdir(DST):
        if entry in PRESERVE:
            continue
        p = os.path.join(DST, entry)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    # 2) Walk source, apply excludes, copy/transform.
    for root, dirs, files in os.walk(SRC):
        rel_root = os.path.relpath(root, SRC)
        rel_root = "" if rel_root == "." else rel_root
        # prune excluded dirs in-place
        pruned = []
        for d in list(dirs):
            rp = os.path.join(rel_root, d) if rel_root else d
            if is_excluded(rp.replace(os.sep, "/"), True, patterns):
                pruned.append(d)
        for d in pruned:
            dirs.remove(d)

        for fn in files:
            rp = (os.path.join(rel_root, fn) if rel_root else fn).replace(os.sep, "/")
            if is_excluded(rp, False, patterns):
                continue
            src_path = os.path.join(root, fn)
            if os.path.islink(src_path):
                continue
            dst_path = os.path.join(DST, rp)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            base = os.path.basename(rp)
            if base in REDACT_FILES and is_texty(src_path):
                with open(src_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                new, count = redact(content)
                with open(dst_path, "w", encoding="utf-8") as f:
                    f.write(new)
                redacted_files.append((rp, count))
                kept.append(rp)
                continue

            # Content scan for credentials in kept text files.
            if is_texty(src_path):
                with open(src_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                leaked = False
                # (a) High-confidence real credential signature anywhere -> abort,
                #     unless the match is an all-x placeholder (sk-xxxx, ghp_xxxx).
                for rm in REAL_SECRET_RE.finditer(content):
                    tok = rm.group(0)
                    body = re.sub(r'^(sk-|ghp_|gho_|github_pat_|xai-|AIza|xox[baprs]-)', '', tok)
                    if len(set(body.lower().replace('-', '').replace('_', ''))) > 2:
                        leaked = True
                        break
                if not leaked:
                    # (b) key: value assignment where value is a real-looking token:
                    #     contiguous (no whitespace), no code operators, has entropy.
                    for m in SECRET_ASSIGN_RE.finditer(content):
                        val = m.group(3).strip()
                        if PLACEHOLDER_RE.search(val) or PLACEHOLDER_RE.search(m.group(0)):
                            continue
                        if re.search(r'[\s()*+/\\]', val):   # code expr / func call
                            continue
                        if len(val) >= 16 and re.search(r'[A-Za-z]', val) and re.search(r'[0-9]', val):
                            leaked = True
                            break
                if leaked:
                    leaks.append(rp)
                    continue  # do NOT copy; report below
                shutil.copy2(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
            kept.append(rp)

    print(f"kept_files={len(kept)}")
    for rp, c in redacted_files:
        print(f"redacted={rp} secrets_masked={c}")
    if leaks:
        print("LEAK_DETECTED")
        for l in leaks:
            print(f"leak={l}")
    return 2 if leaks else 0

if __name__ == "__main__":
    sys.exit(main())
