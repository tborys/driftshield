# DriftShield dashboard

The local web dashboard for DriftShield. It reads ingested sessions from the
local DriftShield API and draws each failed run as a decision graph. Click a
node to see its risk flags, evidence and inflection explanation, then open the
generated forensic report inline.

This is a local-only tool. No login, no cloud, no account. It talks to the
DriftShield API running on your machine.

## Stack

- React 19 + TypeScript, built with Vite
- Tailwind CSS 4 with shadcn / Radix UI primitives
- `@xyflow/react` for the decision graph, `@dagrejs/dagre` for layout
- TanStack Query for data fetching
- `react-markdown` for the report view
- Playwright for end-to-end tests

## Run it

The dashboard needs the DriftShield API running first. From the repository root,
follow the Quick Start in the [top-level README](../../README.md) to start
Postgres and the API, then:

```bash
cd driftshield/frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to
`http://localhost:8080` by default. Point it elsewhere with `VITE_API_TARGET`:

```bash
VITE_API_TARGET=http://localhost:9000 npm run dev
```

With no sessions ingested yet, the dashboard shows empty states. Ingest a
transcript (see the top-level README) and refresh to see the session list,
decision graph, and reports populate.

## Theme

The dashboard uses the DriftShield brand palette: dark navy backgrounds, a
`#5b8cff` royal-blue accent, Inter for body text, Sora for headings, and
JetBrains Mono for code and identifiers. The tokens live in `src/index.css` and
feed the shadcn semantic variables, so components pick up the palette without
per-component styling.

## Scripts

| Command | What it does |
|---------|--------------|
| `npm run dev` | Start the Vite dev server with hot reload |
| `npm run build` | Type-check and build the production bundle to `dist/` |
| `npm run preview` | Serve the built bundle locally |
| `npm run lint` | Run ESLint over the project |
| `npx playwright test` | Run the end-to-end tests (reuses a running dev server) |

## Layout

```
src/
├── api/            # API client + typed query hooks (sessions, reports)
├── components/
│   ├── investigation/  # decision graph, node inspector, risk badges
│   ├── layout/         # app shell + branded header
│   ├── reports/        # report trigger + markdown preview
│   ├── sessions/       # session list table
│   ├── ui/             # shadcn primitives
│   └── validation/     # analyst review drawer
├── pages/          # session list + investigation pages
├── types/          # shared response types
└── index.css       # brand theme tokens + component styles
```
