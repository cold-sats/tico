# A team's private config

Tico's public repository is the product. What is yours (your roster, bots, skills, tool
pages, query lists) lives in a repository of your own, layered over a Tico release. This folder
is the shape of the parts that describe outside systems; `docs/databases.md` ("A private team
config") says how to deploy it to the server and the runners.

```
your-team-config/
  registry/                    -> the server's TICO_REGISTRY_DIR (employees.yaml, people.yaml, ...)
    integrations/              -> pages and query lists, layered over the release's integrations/
      warehouse.md                one page per database or outside system (frontmatter as integrations/README.md)
      queries/warehouse.yaml      its named queries
      atlas.md, queries/atlas.yaml   the same for a MongoDB Atlas database (`mongo:` entries instead of `sql:`)
  bot-<slug>/bot.yaml     -> each bot's repository: `tools:` declares which databases it may read
  secrets/                     -> on the runner computer only, never in git: DB_WAREHOUSE_URL=...
```

`integrations/` here is a working example for a fictional team (Acme). Copy it, rename the
service to your database's name, and edit.
