// Demo Pulumi program: provision a project → database + application → domain on nomploy.
//
// Config (set with `pulumi config set …`):
//   pulumi-nomploy:endpoint     https://your-nomploy-instance.com
//   pulumi-nomploy:apiKey       <your x-api-key>   (--secret)
//   pulumi-nomploy:dbPassword   <postgres password> (--secret)
//   pulumi-nomploy:host         app.example.com     (optional — routes a domain)

import * as pulumi from "@pulumi/pulumi";
import { Application, Domain, Postgres, Project } from "./src/nomploy";

const config = new pulumi.Config();
const endpoint = config.require("endpoint");
const apiKey = config.requireSecret("apiKey");
const host = config.get("host"); // optional: skip the Domain if unset

const conn = { endpoint, apiKey };

// 1. Project — its create response hands back the auto-made production environment.
const project = new Project("demo", {
	...conn,
	name: "iac-demo",
	description: "Provisioned by Pulumi",
});

// 2a. A Postgres database in the same environment, deployed.
const db = new Postgres("demo-db", {
	...conn,
	name: "db",
	environmentId: project.environmentId,
	databaseName: "app",
	databaseUser: "app",
	databasePassword: config.requireSecret("dbPassword"),
	deploy: true,
});

// 2b. Application in that environment. Either a prebuilt image (shown) …
const app = new Application("demo-app", {
	...conn,
	name: "api",
	environmentId: project.environmentId,
	dockerImage: "nginxdemos/hello:latest",
	deploy: true,
});

// … or a generic git repo (application.saveGitProvider + saveBuildType):
//   new Application("web", {
//     ...conn, name: "web", environmentId: project.environmentId,
//     gitUrl: "https://github.com/you/repo.git", gitBranch: "main",
//     buildType: "nixpacks", // or "dockerfile" (+ dockerfile/dockerContextPath)
//     deploy: true,
//   });

// 3. Domain routed to the application (only when a `host` is configured).
const domain = host
	? new Domain("demo-domain", {
			...conn,
			host,
			applicationId: app.applicationId,
			port: 80,
			https: true,
			certificateType: "letsencrypt",
		})
	: undefined;

export const projectId = project.projectId;
export const environmentId = project.environmentId;
export const applicationId = app.applicationId;
export const databaseId = db.databaseId;
export const domainId = domain
	? domain.domainId
	: "(set the 'host' config to create a domain)";
