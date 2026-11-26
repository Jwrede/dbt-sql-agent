"""Render docs/demo.gif: run the tutorial commands for real and draw their output as a terminal.

Needs Pillow, a built warehouse, `dbt-sql-agent setup` and the DSA_* settings in the environment.
LLM answers come from recordings/ (replay), everything else runs against PostgreSQL.

    python scripts/demo_gif.py docs/demo.gif
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

STEPS = [
    ("# grants for the agent role, derived from the dbt meta (contact_* columns are pii)",
     "dbt-sql-agent setup | grep dim_customers"),
    ("# a question, with the dbt docs in the prompt (recorded answer of Haiku 5.5)",
     'dbt-sql-agent ask "What was the revenue with customers in Germany in the fourth quarter of 2025?" '
     "--model haiku --mode replay --recordings recordings/dbt | grep -v explanation"),
    ("# the same question with the schema only: the model guesses 'Germany', the data says 'DE'",
     'dbt-sql-agent ask "What was the revenue with customers in Germany in the fourth quarter of 2025?" '
     "--model haiku --mode replay --recordings recordings/schema --context schema | grep -v explanation"),
    ("# personal data: the model declines",
     'dbt-sql-agent ask "What is the phone number of the contact person at customer 17?" '
     "--model sonnet --mode replay --recordings recordings/dbt | head -1"),
    ("# SQL sent directly (as an MCP client would): the guard rejects it",
     'dbt-sql-agent query "select contact_email from marts.dim_customers"'),
    ("# every decision is in the append-only audit log",
     "dbt-sql-agent audit -n 4 --short"),
]

COLS, ROWS = 112, 32
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
CW = FONT.getlength("M")
LH = 19
PAD = 14
BG, FG, DIM, PROMPT, OK, WARN = (24, 26, 33), (220, 223, 228), (130, 138, 150), (120, 200, 120), (120, 200, 120), (235, 190, 90)


def color(line: str):
    if line.startswith("$ "):
        return FG
    if line.startswith("# "):
        return DIM
    if line.startswith("status: executed"):
        return OK
    if line.startswith(("status: refused", "rejected", "database error")) or "None" == line.strip():
        return WARN
    return FG


def render(lines: list[str]) -> Image.Image:
    img = Image.new("RGB", (int(PAD * 2 + CW * COLS + 1), PAD * 2 + LH * ROWS), BG)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines[-ROWS:]):
        y = PAD + i * LH
        if line.startswith("$ "):
            d.text((PAD, y), "$", font=FONT, fill=PROMPT)
            d.text((PAD + 2 * CW, y), line[2:], font=FONT, fill=FG)
        else:
            d.text((PAD, y), line, font=FONT, fill=color(line))
    return img


def wrap(text: str, first: str = "", indent: str = "") -> list[str]:
    out = []
    for raw in text.splitlines() or [""]:
        out += textwrap.wrap(raw, COLS, initial_indent=first, subsequent_indent=indent or first,
                             break_long_words=True, break_on_hyphens=False) or [first]
        first = indent or first
    return out


def main(path: str) -> None:
    screen: list[str] = []
    frames: list[Image.Image] = []
    durations: list[int] = []

    def snap(ms: int) -> None:
        frames.append(render(screen))
        durations.append(ms)

    for comment, cmd in STEPS:
        screen += wrap(comment)
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        typed = ""
        base = list(screen)
        step = max(4, len(cmd) // 25)
        for i in range(0, len(cmd), step):
            typed = cmd[: i + step]
            screen[:] = base + wrap(typed, "$ ", "  ")
            snap(45)
        snap(500)
        text = (out.stdout + out.stderr).rstrip()
        screen += [ln[:COLS] for ln in wrap(text)] if text else []
        screen.append("")
        snap(3800)
    snap(2500)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"{path}: {len(frames)} frames, {sum(durations) / 1000:.1f} s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.gif")
