// Minimal client for the nomploy REST API, plus type-safe helpers generated from
// the OpenAPI spec (see `./api-types`, regenerate with `npm run gen:types`).
//
// The API is the tRPC router surface exposed over HTTP by `@dokploy/trpc-openapi`
// at `<endpoint>/api/<router>.<procedure>`: GET for queries (input flattened into
// query params), POST for mutations (input as a JSON body). Auth is the
// `x-api-key` header. Mint a key in the panel under Settings → API/Swagger
// (or `POST /api/user.createApiKey` from an authenticated session).

export interface Conn {
	/** Base URL of the panel, e.g. https://nomploy.example.com (no trailing /api). */
	endpoint: string;
	/** An API key (x-api-key). */
	apiKey: string;
}

export type Method = "GET" | "POST";

/** Call a tRPC procedure over REST. Throws on a non-2xx response. */
export async function call<T = any>(
	conn: Conn,
	procedure: string,
	input: Record<string, unknown> | undefined,
	method: Method,
): Promise<T> {
	const base = conn.endpoint.replace(/\/+$/, "");
	const url = new URL(`${base}/api/${procedure}`);
	const init: RequestInit = {
		method,
		headers: {
			"x-api-key": conn.apiKey,
			"content-type": "application/json",
		},
	};
	if (method === "GET") {
		for (const [k, v] of Object.entries(input ?? {})) {
			if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
		}
	} else {
		init.body = JSON.stringify(input ?? {});
	}

	const res = await fetch(url.toString(), init);
	const text = await res.text();
	if (!res.ok) {
		throw new Error(
			`nomploy ${method} ${procedure} failed: ${res.status} ${res.statusText} — ${text.slice(0, 500)}`,
		);
	}
	return (text ? JSON.parse(text) : undefined) as T;
}

/**
 * Fire a long-running action (e.g. a deploy) and wait up to `waitMs` for it.
 *
 * Some deploy endpoints — notably the databases' `<engine>.deploy` — run the
 * deployment **synchronously** (they pull the image, then register the Nomad
 * job, then return), so the request can stay open for a while. We wait up to
 * `waitMs`; a timeout is treated as best-effort ("triggered"). HTTP errors throw.
 *
 * Caveat: a cold first-time pull of a *new* image can exceed `waitMs` (and a
 * reverse proxy may cut a very long request), and the server ties the deploy to
 * the request — so a timed-out cold deploy may not register. Once the image is
 * cached on the node, deploys finish in seconds. If a DB doesn't come up on the
 * first `pulumi up` with a brand-new image, deploy it once from the panel (or
 * re-run `pulumi up` — the image is cached by then).
 */
export async function trigger(
	conn: Conn,
	procedure: string,
	input: Record<string, unknown>,
	waitMs = 120000,
): Promise<void> {
	const base = conn.endpoint.replace(/\/+$/, "");
	try {
		const res = await fetch(`${base}/api/${procedure}`, {
			method: "POST",
			headers: { "x-api-key": conn.apiKey, "content-type": "application/json" },
			body: JSON.stringify(input),
			signal: AbortSignal.timeout(waitMs),
		});
		if (!res.ok) {
			const t = await res.text();
			throw new Error(
				`nomploy POST ${procedure} failed: ${res.status} ${res.statusText} — ${t.slice(0, 300)}`,
			);
		}
	} catch (e: any) {
		// Our own timeout → the deploy is long-running and already accepted.
		if (e?.name === "TimeoutError" || e?.name === "AbortError") return;
		throw e;
	}
}

// ─── Typed helpers (from the generated OpenAPI types) ─────────────────────────
// `get`/`post` take a spec path like "/project.create" and type the body/query +
// response from `api-types.ts`. The dynamic providers mostly use the untyped
// `call` above (uniform handling, and the DB provider builds engine paths at
// runtime), but new/typed code can use these.

import type { paths } from "./api-types";

export type ApiPath = keyof paths & string;

type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;

/** Request body type for a POST path. */
export type ApiBody<P extends ApiPath> = paths[P] extends {
	post: { requestBody?: infer RB };
}
	? Json<RB>
	: never;

/** Query-params type for a GET path. */
export type ApiQuery<P extends ApiPath> = paths[P] extends {
	get: { parameters: { query?: infer Q } };
}
	? Q
	: never;

/** 200 JSON response type for a path (GET or POST). */
export type ApiResponse<P extends ApiPath> = paths[P] extends {
	get: { responses: { 200: infer R } };
}
	? Json<R>
	: paths[P] extends { post: { responses: { 200: infer R } } }
		? Json<R>
		: never;

const stripSlash = (p: string) => p.replace(/^\/+/, "");

/** Typed GET for a spec path, e.g. `get(conn, "/project.one", { projectId })`. */
export function get<P extends ApiPath>(
	conn: Conn,
	path: P,
	query: ApiQuery<P>,
): Promise<ApiResponse<P>> {
	return call(conn, stripSlash(path), query as any, "GET");
}

/** Typed POST for a spec path, e.g. `post(conn, "/project.create", { name })`. */
export function post<P extends ApiPath>(
	conn: Conn,
	path: P,
	body: ApiBody<P>,
): Promise<ApiResponse<P>> {
	return call(conn, stripSlash(path), body as any, "POST");
}
