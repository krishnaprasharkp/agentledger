"""Fail closed if the rendered production stack departs from the demo boundary."""
import json
import os
import sys


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def verify(data, env):
    services = data.get("services", {})
    require(set(services) == {"demo-api", "proxy"}, "Only the demo API and proxy may be deployed.")
    api, proxy = services["demo-api"], services["proxy"]
    expected = {
        "APP_MODE": "public_demo", "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "EXTRACTION_PROVIDER": "rules", "SUPPORT_LIVE_PROBE_ENABLED": "false",
        "LLM_API_KEY": "", "WORKSPACE_API_KEY": "",
    }
    require(api.get("environment") == expected, "Unexpected demo environment or credentials.")
    require(not data.get("volumes") and not api.get("volumes") and not api.get("ports"),
            "The API cannot publish ports or mount persistent data.")
    require(set(api.get("networks", {})) == {"demo-backend"} and
            data.get("networks", {}).get("demo-backend", {}).get("internal") is True,
            "The API must be on the internal network only.")
    require(set(data.get("networks", {})) == {"demo-edge", "demo-backend"} and not any(
        network.get("external") for network in data["networks"].values()
    ), "Only project-managed demo networks are allowed.")
    require(set(proxy.get("networks", {})) == {"demo-edge", "demo-backend"},
            "The proxy must connect to both dedicated demo networks.")
    require(api.get("read_only") is True and api.get("healthcheck", {}).get("test"),
            "The API must have a read-only root and health check.")
    command = api.get("command", [])
    require(command[:2] == ["uvicorn", "main:app"] and
            {"--no-proxy-headers", "--no-access-log"}.issubset(command) and
            command.count("--workers") == 1 and
            command[command.index("--workers") + 1:][:1] == ["1"] and
            not any(arg.startswith("--workers=") for arg in command),
            "The demo must use the audited server command.")
    for service, image_key, memory, cpus, pids in (
        (api, "DEMO_API_IMAGE", 536870912, 0.75, 128),
        (proxy, "DEMO_PROXY_IMAGE", 134217728, 0.20, 64),
    ):
        require(service.get("image") == env.get(image_key) and not service.get("build") and
                service.get("pull_policy") == "never", "Only reviewed local release images are allowed.")
        require(int(service.get("mem_limit", 0)) == memory and
                int(service.get("memswap_limit", 0)) == memory and
                float(service.get("cpus", 0)) == cpus and service.get("pids_limit") == pids,
                "Expected CPU, memory, swap and process limits are missing.")
        require(not (service.get("privileged") or service.get("network_mode") or
                     service.get("env_file") or service.get("secrets") or service.get("configs")) and
                "no-new-privileges:true" in service.get("security_opt", []),
                "Unexpected privileges, networking, or configuration mounts.")
        require(service.get("logging") == {
            "driver": "json-file", "options": {"max-size": "10m", "max-file": "3"},
        }, "Bounded container logs are required.")
    require(not proxy.get("environment"), "The edge proxy may not receive secrets through its environment.")
    ports = proxy.get("ports", [])
    require(len(ports) == 1 and ports[0].get("target") == 8443 and ports[0].get("protocol") == "tcp" and
            ports[0].get("host_ip") == env.get("DEMO_BIND_ADDRESS") and
            str(ports[0].get("published")) == env.get("DEMO_HTTPS_PORT"), "Only the configured HTTPS port may be published.")
    mounts = proxy.get("volumes", [])
    targets = {
        "/etc/nginx/conf.d/default.conf": "DEMO_NGINX_CONFIG",
        "/etc/nginx/demo-cert.pem": "DEMO_TLS_CERT",
        "/etc/nginx/demo-key.pem": "DEMO_TLS_KEY",
    }
    require(len(mounts) == 3 and {m.get("target") for m in mounts} == set(targets) and all(
        m.get("type") == "bind" and m.get("read_only") is True and
        os.path.normcase(os.path.normpath(m.get("source", ""))) ==
        os.path.normcase(os.path.normpath(env.get(targets[m["target"]], ""))) for m in mounts
    ), "Only the three read-only proxy configuration mounts are allowed.")


if __name__ == "__main__":
    verify(json.load(sys.stdin), os.environ)
