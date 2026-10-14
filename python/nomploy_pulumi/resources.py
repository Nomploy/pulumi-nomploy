"""Pulumi dynamic-provider resources for nomploy, over the REST API.

Mirrors the TypeScript provider. Each resource carries its own ``endpoint`` +
``api_key`` (a dynamic provider is serialized into state, so connection details
travel as resource inputs); ``api_key`` is kept out of the state file via
``additional_secret_outputs``.
"""

from __future__ import annotations

from typing import Any, Optional

import pulumi
from pulumi.dynamic import (
    CreateResult,
    DiffResult,
    ReadResult,
    ResourceProvider,
    UpdateResult,
)

from ._client import call, trigger


# ---- helpers ---------------------------------------------------------------

def _conn(p: dict) -> dict:
    return {"endpoint": p["endpoint"], "apiKey": p["api_key"]}


def _changed(olds: dict, news: dict, keys: list) -> bool:
    return any(olds.get(k) != news.get(k) for k in keys)


def _clean(d: dict) -> dict:
    """Drop None-valued keys so optional fields are omitted (not sent as JSON
    null) — the API's zod schemas reject null for unset string fields. The
    ``save*`` source calls keep their explicit nulls (those fields are nullable
    and required-present)."""
    return {k: v for k, v in d.items() if v is not None}


def _opts(opts: Optional[pulumi.ResourceOptions]) -> pulumi.ResourceOptions:
    secret = pulumi.ResourceOptions(additional_secret_outputs=["api_key"])
    return pulumi.ResourceOptions.merge(opts, secret) if opts else secret


# ---- Project ---------------------------------------------------------------

class _ProjectProvider(ResourceProvider):
    def create(self, inputs):
        conn = _conn(inputs)
        r = call(
            conn,
            "project.create",
            _clean(
                {
                    "name": inputs["name"],
                    "description": inputs.get("description"),
                    "env": inputs.get("env"),
                }
            ),
            "POST",
        )
        pid = r["project"]["projectId"]
        eid = (r.get("environment") or {}).get("environmentId")
        return CreateResult(
            id_=pid, outs={**inputs, "project_id": pid, "environment_id": eid}
        )

    def read(self, id_, props):
        r = call(_conn(props), "project.one", {"projectId": id_}, "GET") or {}
        return ReadResult(
            id_=id_,
            outs={**props, "project_id": id_, "name": r.get("name", props.get("name"))},
        )

    def diff(self, _id, olds, news):
        return DiffResult(changes=_changed(olds, news, ["name", "description", "env"]))

    def update(self, id_, _olds, news):
        call(
            _conn(news),
            "project.update",
            _clean(
                {
                    "projectId": id_,
                    "name": news["name"],
                    "description": news.get("description"),
                    "env": news.get("env"),
                }
            ),
            "POST",
        )
        return UpdateResult(outs={**news, "project_id": id_})

    def delete(self, id_, props):
        call(_conn(props), "project.remove", {"projectId": id_}, "POST")


class Project(pulumi.dynamic.Resource):
    project_id: pulumi.Output[str]
    environment_id: pulumi.Output[str]

    def __init__(
        self,
        resource_name: str,
        *,
        endpoint: pulumi.Input[str],
        api_key: pulumi.Input[str],
        name: pulumi.Input[str],
        description: Optional[pulumi.Input[str]] = None,
        env: Optional[pulumi.Input[str]] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            _ProjectProvider(),
            resource_name,
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "name": name,
                "description": description,
                "env": env,
                "project_id": None,
                "environment_id": None,
            },
            _opts(opts),
        )


# ---- Application ------------------------------------------------------------

_APP_SOURCE_KEYS = [
    "docker_image",
    "registry_url",
    "registry_username",
    "registry_password",
    "git_url",
    "git_branch",
    "git_build_path",
    "git_ssh_key_id",
    "build_type",
    "dockerfile",
    "docker_context_path",
]


def _apply_app_source(conn: dict, app_id: str, p: dict) -> None:
    if p.get("docker_image"):
        call(
            conn,
            "application.saveDockerProvider",
            {
                "applicationId": app_id,
                "dockerImage": p["docker_image"],
                "username": p.get("registry_username"),
                "password": p.get("registry_password"),
                "registryUrl": p.get("registry_url"),
            },
            "POST",
        )
        return
    if p.get("git_url"):
        call(
            conn,
            "application.saveGitProvider",
            {
                "applicationId": app_id,
                "customGitUrl": p["git_url"],
                "customGitBranch": p.get("git_branch") or "main",
                "customGitBuildPath": p.get("git_build_path") or "/",
                "customGitSSHKeyId": p.get("git_ssh_key_id"),
                "watchPaths": None,
                "enableSubmodules": False,
            },
            "POST",
        )
        call(
            conn,
            "application.saveBuildType",
            {
                "applicationId": app_id,
                "buildType": p.get("build_type") or "nixpacks",
                "dockerfile": p.get("dockerfile"),
                "dockerContextPath": p.get("docker_context_path"),
                "dockerBuildStage": None,
                "herokuVersion": None,
                "railpackVersion": None,
                "publishDirectory": None,
                "isStaticSpa": None,
            },
            "POST",
        )


class _ApplicationProvider(ResourceProvider):
    def create(self, inputs):
        conn = _conn(inputs)
        r = call(
            conn,
            "application.create",
            _clean(
                {
                    "name": inputs["name"],
                    "appName": inputs.get("app_name"),
                    "description": inputs.get("description"),
                    "environmentId": inputs["environment_id"],
                    "serverId": inputs.get("server_id"),
                }
            ),
            "POST",
        )
        app_id = r["applicationId"]
        _apply_app_source(conn, app_id, inputs)
        if inputs.get("deploy"):
            trigger(conn, "application.deploy", {"applicationId": app_id, "title": "Pulumi deploy"})
        return CreateResult(
            id_=app_id,
            outs={**inputs, "application_id": app_id, "app_name": r.get("appName")},
        )

    def read(self, id_, props):
        r = call(_conn(props), "application.one", {"applicationId": id_}, "GET") or {}
        return ReadResult(
            id_=id_,
            outs={
                **props,
                "application_id": id_,
                "name": r.get("name", props.get("name")),
                "app_name": r.get("appName", props.get("app_name")),
            },
        )

    def diff(self, _id, olds, news):
        replaces = (
            ["environment_id", "app_name", "server_id"]
            if _changed(olds, news, ["environment_id", "app_name", "server_id"])
            else []
        )
        return DiffResult(
            changes=_changed(olds, news, ["name", "description", "deploy", *_APP_SOURCE_KEYS]),
            replaces=replaces,
            delete_before_replace=True,
        )

    def update(self, id_, olds, news):
        conn = _conn(news)
        call(
            conn,
            "application.update",
            _clean({"applicationId": id_, "name": news["name"], "description": news.get("description")}),
            "POST",
        )
        if _changed(olds, news, _APP_SOURCE_KEYS):
            _apply_app_source(conn, id_, news)
            if news.get("deploy"):
                trigger(conn, "application.deploy", {"applicationId": id_, "title": "Pulumi redeploy"})
        return UpdateResult(outs={**news, "application_id": id_})

    def delete(self, id_, props):
        call(_conn(props), "application.delete", {"applicationId": id_}, "POST")


class Application(pulumi.dynamic.Resource):
    application_id: pulumi.Output[str]
    app_name: pulumi.Output[str]

    def __init__(
        self,
        resource_name: str,
        *,
        endpoint: pulumi.Input[str],
        api_key: pulumi.Input[str],
        name: pulumi.Input[str],
        environment_id: pulumi.Input[str],
        app_name: Optional[pulumi.Input[str]] = None,
        description: Optional[pulumi.Input[str]] = None,
        server_id: Optional[pulumi.Input[str]] = None,
        docker_image: Optional[pulumi.Input[str]] = None,
        registry_url: Optional[pulumi.Input[str]] = None,
        registry_username: Optional[pulumi.Input[str]] = None,
        registry_password: Optional[pulumi.Input[str]] = None,
        git_url: Optional[pulumi.Input[str]] = None,
        git_branch: Optional[pulumi.Input[str]] = None,
        git_build_path: Optional[pulumi.Input[str]] = None,
        git_ssh_key_id: Optional[pulumi.Input[str]] = None,
        build_type: Optional[pulumi.Input[str]] = None,
        dockerfile: Optional[pulumi.Input[str]] = None,
        docker_context_path: Optional[pulumi.Input[str]] = None,
        deploy: Optional[pulumi.Input[bool]] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            _ApplicationProvider(),
            resource_name,
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "name": name,
                "environment_id": environment_id,
                "app_name": app_name,
                "description": description,
                "server_id": server_id,
                "docker_image": docker_image,
                "registry_url": registry_url,
                "registry_username": registry_username,
                "registry_password": registry_password,
                "git_url": git_url,
                "git_branch": git_branch,
                "git_build_path": git_build_path,
                "git_ssh_key_id": git_ssh_key_id,
                "build_type": build_type,
                "dockerfile": dockerfile,
                "docker_context_path": docker_context_path,
                "deploy": deploy,
                "application_id": None,
            },
            _opts(opts),
        )


# ---- Domain ----------------------------------------------------------------

_DOMAIN_FIELDS = ["host", "port", "https", "path", "service_name", "certificate_type", "domain_type"]
_DOMAIN_API = {
    "host": "host",
    "port": "port",
    "https": "https",
    "path": "path",
    "service_name": "serviceName",
    "certificate_type": "certificateType",
    "domain_type": "domainType",
}


class _DomainProvider(ResourceProvider):
    def _body(self, p: dict) -> dict:
        b = {_DOMAIN_API[k]: p.get(k) for k in _DOMAIN_FIELDS}
        b["applicationId"] = p.get("application_id")
        b["composeId"] = p.get("compose_id")
        return b

    def create(self, inputs):
        r = call(_conn(inputs), "domain.create", _clean(self._body(inputs)), "POST")
        did = r["domainId"]
        return CreateResult(id_=did, outs={**inputs, "domain_id": did})

    def read(self, id_, props):
        r = call(_conn(props), "domain.one", {"domainId": id_}, "GET") or {}
        return ReadResult(id_=id_, outs={**props, "domain_id": id_, "host": r.get("host", props.get("host"))})

    def diff(self, _id, olds, news):
        replaces = (
            ["application_id", "compose_id"]
            if _changed(olds, news, ["application_id", "compose_id"])
            else []
        )
        return DiffResult(
            changes=_changed(olds, news, _DOMAIN_FIELDS),
            replaces=replaces,
            delete_before_replace=True,
        )

    def update(self, id_, _olds, news):
        body = self._body(news)
        body.pop("applicationId", None)
        body.pop("composeId", None)
        body["domainId"] = id_
        call(_conn(news), "domain.update", _clean(body), "POST")
        return UpdateResult(outs={**news, "domain_id": id_})

    def delete(self, id_, props):
        call(_conn(props), "domain.delete", {"domainId": id_}, "POST")


class Domain(pulumi.dynamic.Resource):
    domain_id: pulumi.Output[str]

    def __init__(
        self,
        resource_name: str,
        *,
        endpoint: pulumi.Input[str],
        api_key: pulumi.Input[str],
        host: pulumi.Input[str],
        application_id: Optional[pulumi.Input[str]] = None,
        compose_id: Optional[pulumi.Input[str]] = None,
        port: Optional[pulumi.Input[int]] = None,
        https: Optional[pulumi.Input[bool]] = None,
        path: Optional[pulumi.Input[str]] = None,
        service_name: Optional[pulumi.Input[str]] = None,
        certificate_type: Optional[pulumi.Input[str]] = None,
        domain_type: Optional[pulumi.Input[str]] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            _DomainProvider(),
            resource_name,
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "host": host,
                "application_id": application_id,
                "compose_id": compose_id,
                "port": port,
                "https": https,
                "path": path,
                "service_name": service_name,
                "certificate_type": certificate_type,
                "domain_type": domain_type,
                "domain_id": None,
            },
            _opts(opts),
        )


# ---- Databases (postgres / mysql / mariadb / mongo / redis) -----------------

_DB_FIELDS = {
    "name": "name",
    "app_name": "appName",
    "description": "description",
    "server_id": "serverId",
    "docker_image": "dockerImage",
    "database_name": "databaseName",
    "database_user": "databaseUser",
    "database_password": "databasePassword",
    "database_root_password": "databaseRootPassword",
    "replica_sets": "replicaSets",
}


def _db_body(p: dict) -> dict:
    return {api: p.get(snake) for snake, api in _DB_FIELDS.items() if p.get(snake) is not None}


class _DatabaseProvider(ResourceProvider):
    def create(self, inputs):
        conn = _conn(inputs)
        engine = inputs["engine"]
        id_key = f"{engine}Id"
        body = {**_db_body(inputs), "environmentId": inputs["environment_id"]}
        # Always send a password field (empty => the server generates one); omitting
        # it can fail validation.
        body["databasePassword"] = inputs.get("database_password") or ""
        r = call(conn, f"{engine}.create", body, "POST")
        did = r[id_key]
        if inputs.get("deploy"):
            trigger(conn, f"{engine}.deploy", {id_key: did})
        return CreateResult(id_=did, outs={**inputs, "database_id": did, "app_name": r.get("appName")})

    def read(self, id_, props):
        engine = props["engine"]
        r = call(_conn(props), f"{engine}.one", {f"{engine}Id": id_}, "GET") or {}
        return ReadResult(id_=id_, outs={**props, "database_id": id_, "name": r.get("name", props.get("name"))})

    def diff(self, _id, olds, news):
        replaces = (
            ["engine", "environment_id", "app_name", "server_id"]
            if _changed(olds, news, ["engine", "environment_id", "app_name", "server_id"])
            else []
        )
        return DiffResult(
            changes=_changed(olds, news, [*_DB_FIELDS.keys(), "deploy"]),
            replaces=replaces,
            delete_before_replace=True,
        )

    def update(self, id_, olds, news):
        conn = _conn(news)
        engine = news["engine"]
        id_key = f"{engine}Id"
        call(conn, f"{engine}.update", {id_key: id_, **_db_body(news)}, "POST")
        if news.get("deploy") and _changed(olds, news, list(_DB_FIELDS.keys())):
            trigger(conn, f"{engine}.deploy", {id_key: id_})
        return UpdateResult(outs={**news, "database_id": id_})

    def delete(self, id_, props):
        engine = props["engine"]
        call(_conn(props), f"{engine}.remove", {f"{engine}Id": id_}, "POST")


class Database(pulumi.dynamic.Resource):
    database_id: pulumi.Output[str]
    app_name: pulumi.Output[str]

    def __init__(
        self,
        resource_name: str,
        *,
        engine: pulumi.Input[str],
        endpoint: pulumi.Input[str],
        api_key: pulumi.Input[str],
        name: pulumi.Input[str],
        environment_id: pulumi.Input[str],
        app_name: Optional[pulumi.Input[str]] = None,
        description: Optional[pulumi.Input[str]] = None,
        server_id: Optional[pulumi.Input[str]] = None,
        docker_image: Optional[pulumi.Input[str]] = None,
        database_name: Optional[pulumi.Input[str]] = None,
        database_user: Optional[pulumi.Input[str]] = None,
        database_password: Optional[pulumi.Input[str]] = None,
        database_root_password: Optional[pulumi.Input[str]] = None,
        replica_sets: Optional[pulumi.Input[bool]] = None,
        deploy: Optional[pulumi.Input[bool]] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            _DatabaseProvider(),
            resource_name,
            {
                "engine": engine,
                "endpoint": endpoint,
                "api_key": api_key,
                "name": name,
                "environment_id": environment_id,
                "app_name": app_name,
                "description": description,
                "server_id": server_id,
                "docker_image": docker_image,
                "database_name": database_name,
                "database_user": database_user,
                "database_password": database_password,
                "database_root_password": database_root_password,
                "replica_sets": replica_sets,
                "deploy": deploy,
                "database_id": None,
            },
            _opts(opts),
        )


def _db_subclass(engine: str):
    class _Engine(Database):
        def __init__(self, resource_name: str, **kwargs):
            super().__init__(resource_name, engine=engine, **kwargs)

    _Engine.__name__ = engine.capitalize()
    return _Engine


Postgres = _db_subclass("postgres")
Mysql = _db_subclass("mysql")
Mariadb = _db_subclass("mariadb")
Mongo = _db_subclass("mongo")
Redis = _db_subclass("redis")


# ---- Compose ---------------------------------------------------------------

_COMPOSE_FIELDS = {
    "name": "name",
    "description": "description",
    "app_name": "appName",
    "server_id": "serverId",
    "compose_type": "composeType",
    "compose_file": "composeFile",
    "nomad_pack": "nomadPack",
    "nomad_pack_registry": "nomadPackRegistry",
}


def _compose_body(p: dict) -> dict:
    body: dict = {
        "composeType": p.get("compose_type") or ("nomad-pack" if p.get("nomad_pack") else "nomad"),
    }
    for snake, api in _COMPOSE_FIELDS.items():
        if snake == "compose_type":
            continue
        if p.get(snake) is not None:
            body[api] = p[snake]
    return body


class _ComposeProvider(ResourceProvider):
    def create(self, inputs):
        conn = _conn(inputs)
        r = call(
            conn,
            "compose.create",
            {**_compose_body(inputs), "environmentId": inputs["environment_id"]},
            "POST",
        )
        cid = r["composeId"]
        if inputs.get("deploy"):
            trigger(conn, "compose.deploy", {"composeId": cid, "title": "Pulumi deploy"})
        return CreateResult(id_=cid, outs={**inputs, "compose_id": cid, "app_name": r.get("appName")})

    def read(self, id_, props):
        r = call(_conn(props), "compose.one", {"composeId": id_}, "GET") or {}
        return ReadResult(id_=id_, outs={**props, "compose_id": id_, "name": r.get("name", props.get("name"))})

    def diff(self, _id, olds, news):
        fields = [k for k in _COMPOSE_FIELDS if k not in ("app_name", "server_id")]
        replaces = (
            ["environment_id", "app_name", "server_id"]
            if _changed(olds, news, ["environment_id", "app_name", "server_id"])
            else []
        )
        return DiffResult(
            changes=_changed(olds, news, [*fields, "deploy"]),
            replaces=replaces,
            delete_before_replace=True,
        )

    def update(self, id_, olds, news):
        conn = _conn(news)
        call(conn, "compose.update", {"composeId": id_, **_compose_body(news)}, "POST")
        fields = [k for k in _COMPOSE_FIELDS if k not in ("app_name", "server_id")]
        if news.get("deploy") and _changed(olds, news, fields):
            trigger(conn, "compose.deploy", {"composeId": id_, "title": "Pulumi redeploy"})
        return UpdateResult(outs={**news, "compose_id": id_})

    def delete(self, id_, props):
        call(
            _conn(props),
            "compose.delete",
            {"composeId": id_, "deleteVolumes": bool(props.get("delete_volumes_on_destroy"))},
            "POST",
        )


class Compose(pulumi.dynamic.Resource):
    compose_id: pulumi.Output[str]
    app_name: pulumi.Output[str]

    def __init__(
        self,
        resource_name: str,
        *,
        endpoint: pulumi.Input[str],
        api_key: pulumi.Input[str],
        name: pulumi.Input[str],
        environment_id: pulumi.Input[str],
        app_name: Optional[pulumi.Input[str]] = None,
        description: Optional[pulumi.Input[str]] = None,
        server_id: Optional[pulumi.Input[str]] = None,
        compose_type: Optional[pulumi.Input[str]] = None,
        compose_file: Optional[pulumi.Input[str]] = None,
        nomad_pack: Optional[pulumi.Input[str]] = None,
        nomad_pack_registry: Optional[pulumi.Input[str]] = None,
        delete_volumes_on_destroy: Optional[pulumi.Input[bool]] = None,
        deploy: Optional[pulumi.Input[bool]] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            _ComposeProvider(),
            resource_name,
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "name": name,
                "environment_id": environment_id,
                "app_name": app_name,
                "description": description,
                "server_id": server_id,
                "compose_type": compose_type,
                "compose_file": compose_file,
                "nomad_pack": nomad_pack,
                "nomad_pack_registry": nomad_pack_registry,
                "delete_volumes_on_destroy": delete_volumes_on_destroy,
                "deploy": deploy,
                "compose_id": None,
            },
            _opts(opts),
        )
