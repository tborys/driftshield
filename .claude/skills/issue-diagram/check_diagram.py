#!/usr/bin/env python3
"""Check every Mermaid diagram in an issue or PR body against the house style.

  check_diagram.py <file or -> [--max-nodes 12]

The file is markdown, or JSON with a "body" string (a PR body ready to send).
Prints one line per problem, or `clean`. Exit 0 clean, 1 problems, 2 bad
command line. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CLASSES = {
    "containerBox": "fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5",
    "componentBox": "fill:#ffffff, color:black, stroke:none",
    "unchanged": "fill:#e9ebee, color:black, stroke:#c9ccd1, stroke-width:1px",
    "broken": "fill:#fdecee, color:black, stroke:#d62b3a, stroke-width:2px",
    "fixed": "fill:#cfeae5, color:black, stroke:#2f8f6f, stroke-width:1.5px",
    "todo": "fill:#ffffff, color:#c4202f, stroke:#d62b3a, stroke-width:1.5px, stroke-dasharray:5",
}
# What the legend line must say for each meaning class a diagram uses.
LEGEND_WORDS = {"unchanged": "grey", "broken": "red outline", "fixed": "green", "todo": "red dashed"}
LABEL = re.compile(r"<b>[^<>]*\S </b>(<font color='#6f7681'><i>[^<>]+</i></font>)?")
ID = re.compile(r"[A-Za-z_]\w*")
HEADER = re.compile(r"(flowchart|graph)\s+(LR|RL|TB|TD|BT)")
SUBGRAPH = re.compile(r'subgraph\s+([A-Za-z_]\w*)\s*(\[\s*"[^"]*"\s*\])?')
CLASS_LINE = re.compile(r"class\s+([A-Za-z_]\w*(?:,[A-Za-z_]\w*)*)\s+([A-Za-z_]\w*)")
CLASSDEF_LINE = re.compile(r"classDef\s+([A-Za-z_]\w*)\s+(.+)")
ARROW = re.compile(r"<?(?:-{2,}|={2,}|-\.+-|~{3,})(?:>|[ox](?=\s))?")
SHAPES = {"([": ("])",), "[(": (")]",), "[[": ("]]",), "((": ("))",), "{{": ("}}",), "[/": ("/]", "\\]"),
          "[\\": ("\\]", "/]"), "(": (")",), "[": ("]",), "{": ("}",), ">": ("]",)}


def styles(text: str) -> dict[str, str]:
    pairs = (p.split(":", 1) for p in text.split(",") if ":" in p)
    return {k.strip().lower(): v.strip().lower() for k, v in pairs}


def skip(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def chain(text: str) -> list[tuple[str, str | None]]:
    """The boxes in a box or edge statement, with their labels. ValueError says
    what is wrong in the words the fix needs."""
    found, i = [], 0
    while True:
        i = skip(text, i)
        m = ID.match(text, i)
        if not m:
            raise ValueError(f"expected a box id at {text[i:i + 24]!r}")
        box, i, label = m.group(), m.end(), None
        if text.startswith(":::", i):
            raise ValueError("put classes in class lines at the end, not :::")
        if text.startswith("@", i):
            raise ValueError(f"draw {box} with a bracket shape, not @{{ }}")
        opener = next((o for o in SHAPES if text.startswith(o, i)), None)
        if opener:
            j = skip(text, i + len(opener))
            end = text.find('"', j + 1) if text.startswith('"', j) else -1
            if end < 0:
                raise ValueError(f'quote the label of {box}: {box}{opener}"..."')
            label, k = text[j + 1:end], skip(text, end + 1)
            closer = next((c for c in SHAPES[opener] if text.startswith(c, k)), None)
            if not closer:
                raise ValueError(f"the shape of {box} is not closed")
            i = k + len(closer)
        found.append((box, label))
        i = skip(text, i)
        if i >= len(text):
            return found
        if text[i] == "&":
            i += 1
            continue
        m = ARROW.match(text, i)
        if not m:
            raise ValueError(f"expected an arrow at {text[i:i + 24]!r}")
        if m.group() in ("--", "=="):
            raise ValueError("write edge labels as a -->|text| b")
        i = skip(text, m.end())
        if text.startswith("|", i):
            end = text.find("|", i + 1)
            if end < 0:
                raise ValueError("an edge label has no closing |")
            i = end + 1


def check_block(lines: list[tuple[int, str]], legend: str | None, max_nodes: int) -> list[tuple[int, str]]:
    """Problems in one diagram: lines are (line number, text) inside the fence."""
    problems: list[tuple[int, str]] = []
    first = lines[0][0] if lines else 0
    boxes: dict[str, tuple[int, str | None]] = {}
    frames: dict[str, int] = {}
    defined: dict[str, int] = {}
    applied: dict[str, list[str]] = {}
    depth, header, tail = 0, False, False
    for no, raw in lines:
        line = raw.strip().removesuffix(";").strip()
        if not line:
            continue
        if line.startswith("%%{"):
            problems.append((no, "remove the %%{ }%% directive: the classes carry every colour"))
            continue
        if line.startswith("%%"):
            continue
        if not header:
            header = True
            if not HEADER.fullmatch(line):
                problems.append((no, "start with flowchart LR, TB, RL or BT"))
            continue
        if m := CLASSDEF_LINE.fullmatch(line):
            tail = True
            name, style = m.groups()
            if name not in CLASSES:
                problems.append((no, f"unknown class {name}: use {', '.join(CLASSES)}"))
            elif styles(style) != styles(CLASSES[name]):
                problems.append((no, f"classDef {name} must be: {CLASSES[name]}"))
            defined[name] = no
            continue
        if m := CLASS_LINE.fullmatch(line):
            tail = True
            for box in m.group(1).split(","):
                applied.setdefault(box, []).append(m.group(2))
            if m.group(2) not in CLASSES:
                problems.append((no, f"unknown class {m.group(2)}: use {', '.join(CLASSES)}"))
            continue
        if tail:
            problems.append((no, "classDef and class lines go last, after every box and edge"))
            continue
        word = line.split()[0]
        if word in ("style", "linkStyle", "click"):
            problems.append((no, f"remove the {word} line: colour comes only from the classes"))
        elif word == "subgraph":
            m = SUBGRAPH.fullmatch(line)
            if m:
                frames[m.group(1)] = no
                depth += 1
            else:
                problems.append((no, 'write a frame as subgraph id["Title"]'))
        elif line == "end":
            depth -= 1
            if depth < 0:
                problems.append((no, "end without a subgraph"))
                depth = 0
        elif word == "direction":
            continue
        else:
            try:
                for box, label in chain(line):
                    seen = boxes.get(box)
                    if label is not None and seen and seen[1] is not None and seen[1] != label:
                        problems.append((no, f"{box} has two different labels"))
                    if not seen or (label is not None and seen[1] is None):
                        boxes[box] = (no, label)
            except ValueError as err:
                problems.append((no, str(err)))
    if depth:
        problems.append((first, "a subgraph has no end"))

    for name in ("containerBox", "componentBox"):
        if name not in defined:
            problems.append((first, f"classDef {name} is missing: {name} {CLASSES[name]}"))
    for box in frames:
        boxes.pop(box, None)  # an edge may point at a frame
    used = {c for names in applied.values() for c in names}
    for name in sorted(used & set(CLASSES) - set(defined)):
        problems.append((first, f"class {name} is applied but not defined: classDef {name} {CLASSES[name]}"))
    for box in sorted(set(applied) - set(boxes) - set(frames)):
        problems.append((first, f"class line names unknown id {box}"))
    for box, no in frames.items():
        if applied.get(box) != ["containerBox"]:
            problems.append((no, f"frame {box} needs containerBox and nothing else"))
    for box, (no, label) in boxes.items():
        names = applied.get(box, [])
        if not names:
            problems.append((no, f"{box} has no class"))
        if "containerBox" in names:
            problems.append((no, f"containerBox is for frames: give {box} componentBox or a meaning class"))
        if len(names) > 1:
            problems.append((no, f"{box} has {len(names)} classes: give it one"))
        if label is None:
            problems.append((no, f"{box} has no label: {box}[\"<b>Title </b>\"]"))
        elif not LABEL.fullmatch(label):
            problems.append((no, f"{box} label must be <b>Title </b> then optionally "
                                 "<font color='#6f7681'><i>Subtitle</i></font>, with a space before </b>"))
    if not frames:
        problems.append((first, "no frame: put the boxes in at least one subgraph and give it containerBox"))
    if boxes and not any("componentBox" in applied.get(b, []) for b in boxes):
        problems.append((first, "no box uses componentBox: give it to the context, a person, caller or "
                                "system outside the change"))
    if len(boxes) > max_nodes:
        problems.append((first, f"{len(boxes)} boxes, at most {max_nodes}: split it into two diagrams"))

    if legend is None:
        problems.append((first, "no Legend: line under the diagram"))
    else:
        for name in sorted(used & set(LEGEND_WORDS)):
            if LEGEND_WORDS[name] not in legend.lower():
                problems.append((first, f"the legend does not mention {LEGEND_WORDS[name]} ({name})"))
    return problems


def check_text(text: str, max_nodes: int = 12) -> list[str]:
    lines = text.splitlines()
    out, count, i = [], 0, 0
    while i < len(lines):
        if lines[i].strip() != "```mermaid":
            i += 1
            continue
        count += 1
        start, i = i, i + 1
        while i < len(lines) and lines[i].strip() != "```":
            i += 1
        block = [(n + 1, lines[n]) for n in range(start + 1, i)]
        if i >= len(lines):
            out.append(f"diagram {count}, line {start + 1}: the mermaid block is not closed")
            break
        after = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
        legend = after.lstrip("*_ ") if after.lstrip("*_ ").startswith("Legend:") else None
        out += [f"diagram {count}, line {no}: {msg}" for no, msg in check_block(block, legend, max_nodes)]
        i += 1
    if not count:
        out.append("no mermaid block found: put the diagram in a ```mermaid fence")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="markdown, or JSON with a body string; - reads stdin")
    ap.add_argument("--max-nodes", type=int, default=12)
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    except OSError as err:
        print(f"cannot read {args.file}: {err.strerror}", file=sys.stderr)
        return 2
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("body"), str):
            text = data["body"]
    except ValueError:
        pass
    problems = check_text(text, args.max_nodes)
    print("\n".join(problems) if problems else "clean")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
