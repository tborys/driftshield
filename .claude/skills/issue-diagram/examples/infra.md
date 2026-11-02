# Infra

Systems as frames, their parts inside, the context (users, outside services) as plain boxes. Edges carry what flows between them.

```mermaid
flowchart TB
  user["<b>Browser </b><font color='#6f7681'><i>a signed in user</i></font>"]
  subgraph web["Web app"]
    pages["<b>Pages </b><font color='#6f7681'><i>rendered on the server</i></font>"]
  end
  subgraph api["API service"]
    handlers["<b>Request handlers </b><font color='#6f7681'><i>slow under load</i></font>"]
    cache["<b>Response cache </b><font color='#6f7681'><i>60 second expiry</i></font>"]
  end
  subgraph data["Database"]
    db["<b>Postgres </b><font color='#6f7681'><i>the primary</i></font>"]
  end
  user --> pages --> handlers
  handlers -->|"read first"| cache
  handlers -->|"on a miss"| db
  classDef containerBox fill:#f2f3f5, color:black, stroke:#1071e5, stroke-width:1px, stroke-dasharray:5
  classDef componentBox fill:#ffffff, color:black, stroke:none
  classDef unchanged fill:#e9ebee, color:black, stroke:#c9ccd1, stroke-width:1px
  classDef broken fill:#fdecee, color:black, stroke:#d62b3a, stroke-width:2px
  classDef todo fill:#ffffff, color:#c4202f, stroke:#d62b3a, stroke-width:1.5px, stroke-dasharray:5
  class web,api,data containerBox
  class user componentBox
  class pages,db unchanged
  class handlers broken
  class cache todo
```

Legend: grey works today and stays, red outline is broken today, red dashed outline is still to build.
