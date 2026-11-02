# Software change

A real bug from an open source CLI: `analyze --json` printed parser warnings to stdout before the JSON, so a script that parses stdout dropped the session. Two frames, Before and After, with the same steps in each.

## In the issue, under Picture

```mermaid
flowchart LR
  run["<b>You run analyze --json </b><font color='#6f7681'><i>on a session with one bad line</i></font>"]
  subgraph before["Before"]
    b_out["<b>stdout </b><font color='#6f7681'><i>the warning, then the JSON</i></font>"]
    b_read["<b>Script parses stdout </b><font color='#6f7681'><i>fails, the session is dropped</i></font>"]
  end
  subgraph after["After"]
    a_out["<b>stdout </b><font color='#6f7681'><i>the JSON only</i></font>"]
    a_err["<b>stderr </b><font color='#6f7681'><i>the warning</i></font>"]
    a_read["<b>Script parses stdout </b><font color='#6f7681'><i>works</i></font>"]
  end
  run --> b_out --> b_read
  run --> a_out --> a_read
  run --> a_err
  classDef containerBox fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5
  classDef componentBox fill:#ffffff, color:black, stroke:none
  classDef broken fill:#fdecee, color:black, stroke:#d62b3a, stroke-width:2px
  classDef todo fill:#ffffff, color:#c4202f, stroke:#d62b3a, stroke-width:1.5px, stroke-dasharray:5
  class before,after containerBox
  class run componentBox
  class b_out,b_read broken
  class a_out,a_err,a_read todo
```

Legend: red outline is broken today, red dashed outline is still to build.

## In the PR, under After

The same picture, drawn from the diff. What the PR built turns green.

```mermaid
flowchart LR
  run["<b>You run analyze --json </b><font color='#6f7681'><i>on a session with one bad line</i></font>"]
  subgraph before["Before"]
    b_out["<b>stdout </b><font color='#6f7681'><i>the warning, then the JSON</i></font>"]
    b_read["<b>Script parses stdout </b><font color='#6f7681'><i>fails, the session is dropped</i></font>"]
  end
  subgraph after["After"]
    a_out["<b>stdout </b><font color='#6f7681'><i>the JSON only</i></font>"]
    a_err["<b>stderr </b><font color='#6f7681'><i>the warning</i></font>"]
    a_read["<b>Script parses stdout </b><font color='#6f7681'><i>works</i></font>"]
  end
  run --> b_out --> b_read
  run --> a_out --> a_read
  run --> a_err
  classDef containerBox fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5
  classDef componentBox fill:#ffffff, color:black, stroke:none
  classDef broken fill:#fdecee, color:black, stroke:#d62b3a, stroke-width:2px
  classDef fixed fill:#cfeae5, color:black, stroke:#2f8f6f, stroke-width:1.5px
  class before,after containerBox
  class run componentBox
  class b_out,b_read broken
  class a_out,a_err,a_read fixed
```

Legend: red outline was broken before this PR, green is new or fixed by it.
