# Workflow

Who does what, in order, and where the work changes hands. One frame per person or agent, steps inside, edges in the order things happen. Label a hand off on its edge. A chain this long runs top to bottom, or GitHub shrinks it to fit.

```mermaid
flowchart TB
  subgraph owner["Owner"]
    write["<b>Write the issue </b><font color='#6f7681'><i>problem and checklist</i></font>"]
    picture["<b>Draw the Picture </b><font color='#6f7681'><i>what will change</i></font>"]
  end
  subgraph lead["Lead agent"]
    build["<b>Build and push </b><font color='#6f7681'><i>test first</i></font>"]
    drawn["<b>Draw the After picture </b><font color='#6f7681'><i>from the diff</i></font>"]
  end
  subgraph reviewer["Reviewer agent"]
    review["<b>Review the diff </b><font color='#6f7681'><i>against the checklist</i></font>"]
    compare["<b>Compare the pictures </b><font color='#6f7681'><i>with the diff</i></font>"]
  end
  pr["<b>Draft PR </b><font color='#6f7681'><i>ready for a person</i></font>"]
  write --> picture -->|"says go"| build --> drawn -->|"opens the PR"| review --> compare -->|"approves"| pr
  classDef containerBox fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5
  classDef componentBox fill:#ffffff, color:black, stroke:none
  classDef unchanged fill:#e9ebee, color:black, stroke:#c9ccd1, stroke-width:1px
  classDef todo fill:#ffffff, color:#c4202f, stroke:#d62b3a, stroke-width:1.5px, stroke-dasharray:5
  class owner,lead,reviewer containerBox
  class pr componentBox
  class write,build,review unchanged
  class picture,drawn,compare todo
```

Legend: grey works today and stays, red dashed outline is still to build.
