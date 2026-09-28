#!/usr/bin/env python
"""Внести §5.4 скилла в references/ и оставить указатель: файл скилла у лимита 100k."""
import sys

base = "/home/hermes/.hermes/skills/software-development/civrealm-tournament"
sk = f"{base}/SKILL.md"
text = open(sk, encoding="utf-8").read()
lines = text.split("\n")
start = next(i for i, l in enumerate(lines) if l.startswith("### 5.4 Games without built-in AI"))
end = next(i for i, l in enumerate(lines) if l.startswith("### 5.2i "))
section = "\n".join(lines[start:end]).rstrip() + "\n"
print("переносим строк:", end - start, "символов:", len(section))

ref = f"{base}/references/ai-less-games-and-identity-wall.md"
import os
os.makedirs(os.path.dirname(ref), exist_ok=True)
body = section.split("\n", 1)[1].lstrip("\n")
with open(ref, "w", encoding="utf-8") as fh:
    fh.write("# Games without built-in AI, and the identity wall (measured 2026-09-26)\n\n"
             "_Extracted from SKILL.md §5.4 to keep SKILL.md under its size limit. "
             "Content unchanged._\n\n" + body)
print("записано в", ref, len(body), "символов")

pointer = (
    "### 5.4 Games without built-in AI, and the identity wall (measured 2026-09-26)\n\n"
    "Settings are **CLI flags** (`--aifill`, `--minp`, `--phasemode`, `--maxplayers`;\n"
    "civrealm turns every top-level `default_settings.yaml` key into `--<key>`, and the\n"
    "client sends them to the server as chat commands). `--aifill 0` = no built-in AI civs;\n"
    "`aifill N` = N players TOTAL (measured: 4 players → 3 AI + you). The identity wall\n"
    "(which player id is really you, and how the two sides read the same game) plus the\n"
    "measured tables are in `references/ai-less-games-and-identity-wall.md`.\n")
new = "\n".join(lines[:start]) + "\n" + pointer + "\n" + "\n".join(lines[end:])
with open(sk, "w", encoding="utf-8") as fh:
    fh.write(new)
print("SKILL.md теперь:", len(new), "символов")