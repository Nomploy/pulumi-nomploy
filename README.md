# pulumi-nomploy

Manage **[nomploy](https://nomploy.com)** services **as code** with
[Pulumi](https://www.pulumi.com/). A TypeScript **dynamic provider** that drives
the panel's existing REST API — no separate API layer and no Go toolchain — so you
can declare projects, applications, databases, domains and compose stacks in a
Pulumi program and `pulumi up` them onto your cluster.

> **Status:** prototype. Resources and types are complete and type-check; validated
> with `pulumi preview`. Run it against your own instance with `pulumi up` (see
> *Quick start*). APIs may still change.

## Why

nomploy exposes its whole tRPC router set over HTTP (via `@dokploy/trpc-openapi`)
at `<endpoint>/api/<router>.<procedure>` — GET for queries, POST for mutations,
`x-api-key` auth. This provider maps each resource's lifecycle onto those
procedures, so everything the panel can create, you can declare.

## Resources

| Resource | Create | Read | Update | Delete |
|---|---|---|---|---|
| `Project` | `project.create` | `project.one` | `project.update` | `project.remove` |
| `Application` | `application.create` | `application.one` | `application.update` | `application.delete` |
| `Domain` | `domain.create` | `domain.one` | `domain.update` | `domain.delete` |
| `Postgres` / `Mysql` / `Mariadb` / `Mongo` / `Redis` (`Database`) | `<engine>.create` | `<engine>.one` | `<engine>.update` | `<engine>.remove` |
| `Compose` | `compose.create` | `compose.one` | `compose.update` | `compose.delete` |

- **`Project`** auto-creates a production environment; its `environmentId` output
  feeds `Application` / `Database` / `Compose`.
- **`Application`** sets its source from a **Docker image** (`dockerImage` +
  optional registry creds → `application.saveDockerProvider`) **or** a **generic
  git repo** (`gitUrl` / `gitBranch` / `buildType` → `application.saveGitProvider`
  + `saveBuildType`), and with `deploy: true` runs `application.deploy` on create
  and whenever the source changes.
- **`Database`** (or the named `Postgres`/… subclasses) covers all five engines
  with the same shape, and `deploy: true`.
- **`Compose`** takes a raw `composeFile` (translated to a Nomad job) or a
  `nomadPack` + `nomadPackRegistry`, with `deploy`.

## Prerequisites

- [Pulumi CLI](https://www.pulumi.com/docs/install/) and Node.js 18+.
- An **API key**: panel → **Settings → API / Swagger** (or `POST
  /api/user.createApiKey` from an authenticated session). The first key must be
  minted from the UI/session; after that the provider only needs the key.

## Quick start

```bash
npm install

# Local state backend (or `pulumi login` to Pulumi Cloud)
pulumi login --local
pulumi stack init dev

pulumi config set endpoint https://your-nomploy-instance.com
pulumi config set apiKey     <your-x-api-key>  --secret
pulumi config set dbPassword <postgres-pass>   --secret
pulumi config set host app.example.com         # optional — routes a domain
pulumi config set dbServerId <worker-server-id> # optional — see Databases note

pulumi preview     # plan
pulumi up          # project → postgres + application(+deploy) → domain
pulumi destroy     # tear it all down
```

`apiKey` (and other secrets) are stored encrypted in the Pulumi state — the
resources mark it an `additionalSecretOutput`.

## Using it in your own program

```ts
import * as pulumi from "@pulumi/pulumi";
import * as nomploy from "pulumi-nomploy/src/nomploy";

const conn = {
  endpoint: "https://your-nomploy-instance.com",
  apiKey: new pulumi.Config().requireSecret("apiKey"),
};

const project = new nomploy.Project("web", { ...conn, name: "web" });

new nomploy.Application("api", {
  ...conn,
  name: "api",
  environmentId: project.environmentId,
  dockerImage: "ghcr.io/you/api:latest",   // or gitUrl/gitBranch/buildType
  deploy: true,
});

new nomploy.Postgres("db", {
  ...conn,
  name: "db",
  environmentId: project.environmentId,
  databaseName: "app",
  databaseUser: "app",
  databasePassword: new pulumi.Config().requireSecret("dbPassword"),
  deploy: true,
});
```

## Typed API client (codegen)

`src/nomploy/api-types.ts` is generated from the panel's OpenAPI spec with
`openapi-typescript` (`npm run gen:types`, reading the vendored `openapi.json`).
`client.ts` exports typed helpers for any spec path:

```ts
import { post, type ApiBody } from "pulumi-nomploy/src/nomploy";
await post(conn, "/project.create", { name: "x" }); // body is type-checked
```

The dynamic providers themselves use the uniform untyped `call` (the spec's
**response** schemas are thin, and the `Database` provider builds `<engine>.*`
paths at runtime); the typed helpers are for request bodies/queries and new code.

Regenerate against your instance: drop a fresh spec in `openapi.json` (from the
nomploy repo's `apps/dokploy/scripts/generate-openapi.ts`, or `/api` at runtime)
and run `npm run gen:types`.

## Notes & caveats

- **tRPC-flavored REST:** everything is GET/POST to `/<router>.<procedure>`; ids go
  in the body/query, not the URL path. `src/nomploy/client.ts` handles that.
- Validate the JSON codec against your instance — the tRPC layer uses superjson
  internally; the OpenAPI handler is expected to emit plain JSON, which this client
  assumes.
- It's a **dynamic provider**, so connection details (`endpoint`, `apiKey`) travel
  as resource inputs rather than ambient config.
- `Compose` destroy keeps volumes unless `deleteVolumesOnDestroy: true`.
- **Database node placement.** A database binds its engine port (5432, 3306, …) as
  a **static host port** and defaults to the **control plane**, which already runs
  stateful services (often a Postgres on 5432). On a multi-node cluster a second DB
  of the same engine on that node fails to place (`reserved port collision`) and
  sits "deploying". Give databases a **`serverId`** (a worker node) so the port is
  free — only one DB per engine-port per node. Changing `serverId` replaces the DB.
- **Database deploys are synchronous** (`<engine>.deploy` pulls the image, then
  registers the Nomad job, then returns) — there's no async/streaming REST variant.
  `deploy` waits up to ~2 min; the **first-ever pull of a new image** on a node can
  take longer (and a proxy may cut a very long request). If a DB doesn't come up on
  the first `pulumi up` with a brand-new image, deploy it once from the panel or
  re-run `pulumi up` (the image is cached by then). Apps/compose deploy
  asynchronously and return fast.

## Roadmap

- Run against more real-world stacks; stabilise the resource APIs.
- Optionally package as a proper Pulumi component/provider (published to npm).
- A Terraform provider over the same REST API, if there's demand.

## License

Apache-2.0 (same permissive terms as the Apache-2.0 portions of nomploy).
