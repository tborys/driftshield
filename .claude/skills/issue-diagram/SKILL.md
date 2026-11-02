---
name: issue-diagram
description: Draw the Picture for an issue, or the After picture for a PR, as one styled Mermaid diagram checked by check_diagram.py.
disable-model-invocation: true
---

# Issue diagram

One Mermaid diagram shows a change so a person gets it before reading the text. An issue carries it under `## Picture`: the plan. A PR carries it under `## After`: what the diff did. GitHub draws Mermaid inline.

## Steps

1. **Pick the shape** from the table below and copy its example from `examples/` next to this file.
2. **Draw it.** Label each box with what a user or the system sees, such as "stdout shows the JSON only". Label each edge with what happens, such as "says go" or "on a miss". Variable, function and file names stay out of labels.
3. **Colour by meaning**: one class per box, from Classes.
4. **Write the legend line** right under the block: `Legend:` and then each colour you used, in plain words.
5. **Check it**: `python3 <this folder>/check_diagram.py <file>`. The file is the issue or PR body, as markdown or as JSON with a `body` string. Fix every line it prints. Done when it prints `clean`.

## Shapes

| Shape | For | Frames | Example |
|---|---|---|---|
| Software change | code that will behave differently | `Before` and `After`, the same steps in each | `examples/software-change.md` |
| Workflow | people or agents handing work on | one per person or agent, steps in order | `examples/workflow.md` |
| Infra | systems, services and storage | one per system, its parts inside | `examples/infra.md` |

For states (what a user sees, and what moves them on) use the software change shape with rounded boxes, `id(["..."])`.

One diagram, at most 12 boxes. More than that is two changes: split the diagram, or the issue.

## Classes

Every frame is a `containerBox`. Every box takes exactly one of the other five. At the end of the diagram put the `classDef` lines you use, always both house ones, then the `class` lines:

```text
classDef containerBox fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5
classDef componentBox fill:#ffffff, color:black, stroke:none
classDef unchanged fill:#e9ebee, color:black, stroke:#c9ccd1, stroke-width:1px
classDef broken fill:#fdecee, color:black, stroke:#d62b3a, stroke-width:2px
classDef fixed fill:#cfeae5, color:black, stroke:#2f8f6f, stroke-width:1.5px
classDef todo fill:#ffffff, color:#c4202f, stroke:#d62b3a, stroke-width:1.5px, stroke-dasharray:5
```

| Class | Looks | Means | The legend says |
|---|---|---|---|
| `componentBox` | white | context: a person, caller or system outside the change. At least one per diagram | nothing |
| `unchanged` | grey | works today and stays as it is | grey |
| `broken` | red outline | wrong today | red outline |
| `fixed` | green | new or fixed, in a PR: what the diff built | green |
| `todo` | red dashed outline | still to build, in an issue: what the work will build | red dashed |

## Syntax the checker accepts

- `flowchart LR` for up to three or four boxes across, `flowchart TB` for anything longer.
- Box: `id["<b>Title </b><font color='#6f7681'><i>Subtitle</i></font>"]`, with a space before `</b>`. The subtitle is optional. Ids are short words of letters, digits and underscores.
- Frame: `subgraph id["Title"]`, its boxes, `end`.
- Edge: `a --> b`, or with a label `a -->|"text"| b`.
- Colour only through the `classDef` and `class` lines at the end.

## What GitHub draws

Checked on a PR comment on 2 Nov 2026, light mode. Every class above renders: fills, solid and dashed outlines, the red title of `todo`, bold, italic and the grey subtitle. GitHub shrinks a diagram to the page width, so a row of seven boxes becomes unreadable and the zoom buttons cover its right edge. GitHub drops Font Awesome icons. It obeys a `%%{init}%%` theme, `linkStyle`, `click` and `:::`. They colour around the legend, so the checker refuses them, and `style` lines too.

## The After picture

Draw it from the diff (`git diff <base>...HEAD`), never from the plan. Start from the issue's Picture when there is one: the same shape, boxes and words. Then:

- a box the diff built or fixed turns `fixed`
- a part the diff changed that the Picture lacks is added, as `fixed`
- a box the Picture planned that the diff did not build stays `todo`, and the PR body says why

Green is a claim about the diff. A box is green only when the diff shows that change.
