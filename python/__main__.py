"""Demo Pulumi program (Python): project -> database + application -> domain.

Config (set with `pulumi config set ...`):
  nomploy-iac-demo-py:endpoint    https://your-nomploy-instance.com
  nomploy-iac-demo-py:apiKey      <your x-api-key>    (--secret)
  nomploy-iac-demo-py:dbPassword  <postgres password> (--secret)
  nomploy-iac-demo-py:host        app.example.com     (optional - routes a domain)
  nomploy-iac-demo-py:dbServerId  <server id>         (optional - pin the DB to a node)
"""

import pulumi

import nomploy_pulumi as nomploy

config = pulumi.Config()
endpoint = config.require("endpoint")
api_key = config.require_secret("apiKey")
db_password = config.get_secret("dbPassword")  # optional — server generates one if unset
host = config.get("host")
db_server_id = config.get("dbServerId")

project = nomploy.Project(
    "demo",
    endpoint=endpoint,
    api_key=api_key,
    name="iac-demo-py",
    description="Provisioned by Pulumi (Python)",
)

db = nomploy.Postgres(
    "demo-db",
    endpoint=endpoint,
    api_key=api_key,
    name="db",
    environment_id=project.environment_id,
    server_id=db_server_id,
    database_name="app",
    database_user="app",
    database_password=db_password,
    deploy=True,
)

app = nomploy.Application(
    "demo-app",
    endpoint=endpoint,
    api_key=api_key,
    name="api",
    environment_id=project.environment_id,
    docker_image="nginxdemos/hello:latest",  # or git_url / git_branch / build_type
    deploy=True,
)

pulumi.export("project_id", project.project_id)
pulumi.export("environment_id", project.environment_id)
pulumi.export("application_id", app.application_id)
pulumi.export("database_id", db.database_id)

if host:
    domain = nomploy.Domain(
        "demo-domain",
        endpoint=endpoint,
        api_key=api_key,
        host=host,
        application_id=app.application_id,
        port=80,
        https=True,
        certificate_type="letsencrypt",
    )
    pulumi.export("domain_id", domain.domain_id)
