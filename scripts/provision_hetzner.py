#!/usr/bin/env python3
"""Hetzner VPS provisioning for SearchClaw SearXNG nodes.

Manages CX22 VPS instances (EUR 3.79/month) with Docker pre-installed,
running SearXNG containers as external search backends.

Environment variables:
    HETZNER_API_TOKEN: Hetzner Cloud API token
    SEARXNG_AUTH_TOKEN: Shared auth token for API gateway communication

Usage:
    provision_hetzner.py create [--name NAME] [--count N] [--location LOC]
    provision_hetzner.py list
    provision_hetzner.py destroy <server-id-or-name>
    provision_hetzner.py rotate <server-id-or-name>
"""

import argparse
import hashlib
import os
import secrets
import sys
import time

from hcloud import Client
from hcloud.images import Image
from hcloud.locations import Location
from hcloud.server_types import ServerType

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN")
SEARXNG_AUTH_TOKEN = os.environ.get("SEARXNG_AUTH_TOKEN", "")

LABEL_KEY = "project"
LABEL_VALUE = "searchclaw"
SERVER_TYPE = "cx22"
IMAGE = "ubuntu-24.04"
DEFAULT_LOCATION = "fsn1"
SSH_KEY_NAME = "searchclaw-deploy"

# Engine weight profiles — each instance gets a different profile so
# search engine load is distributed and blocks affect fewer instances.
ENGINE_PROFILES = [
    {"google": 1.5, "bing": 0.8, "duckduckgo": 0.7, "brave": 0.9, "wikipedia": 0.8},
    {"google": 0.8, "bing": 1.5, "duckduckgo": 0.9, "brave": 0.7, "wikipedia": 0.8},
    {"google": 0.9, "bing": 0.7, "duckduckgo": 1.5, "brave": 0.8, "wikipedia": 0.9},
    {"google": 1.0, "bing": 1.0, "duckduckgo": 0.8, "brave": 1.3, "wikipedia": 0.7},
    {"google": 0.7, "bing": 1.2, "duckduckgo": 1.0, "brave": 1.0, "wikipedia": 1.2},
]


def generate_settings_yml(instance_index: int) -> str:
    """Generate a unique SearXNG settings.yml for each instance."""
    profile = ENGINE_PROFILES[instance_index % len(ENGINE_PROFILES)]
    secret_key = secrets.token_hex(32)

    return f"""general:
  instance_name: "SearchClaw Node {instance_index}"
  debug: false

search:
  safe_search: 1
  default_lang: "en"
  formats:
    - json

server:
  secret_key: "{secret_key}"
  limiter: false
  image_proxy: false
  method: "GET"
  bind_address: "0.0.0.0"
  port: 8080

outgoing:
  request_timeout: 5.0
  max_request_timeout: 10.0
  useragent_suffix: ""

engines:
  - name: google
    engine: google
    shortcut: g
    disabled: false
    weight: {profile['google']}

  - name: bing
    engine: bing
    shortcut: b
    disabled: false
    weight: {profile['bing']}

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false
    weight: {profile['duckduckgo']}

  - name: brave
    engine: brave
    shortcut: br
    disabled: false
    weight: {profile['brave']}

  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    disabled: false
    weight: {profile['wikipedia']}

  - name: wikidata
    engine: wikidata
    shortcut: wd
    disabled: false

  - name: yahoo
    disabled: true
  - name: qwant
    disabled: true
"""


def generate_cloud_init(instance_index: int, auth_token: str) -> str:
    """Generate cloud-init user data that installs Docker and deploys SearXNG."""
    settings_yml = generate_settings_yml(instance_index)
    # Escape single quotes for shell embedding
    settings_escaped = settings_yml.replace("'", "'\\''")

    return f"""#cloud-config
package_update: true
packages:
  - docker.io
  - nginx
  - ufw

write_files:
  - path: /opt/searchclaw/settings.yml
    content: |
{chr(10).join('      ' + line for line in settings_yml.splitlines())}
    owner: root:root
    permissions: '0644'

  - path: /opt/searchclaw/auth_token
    content: "{auth_token}"
    owner: root:root
    permissions: '0600'

  - path: /etc/nginx/sites-available/searxng
    content: |
      server {{
          listen 8888;

          location / {{
              if ($http_x_searchclaw_token != "{auth_token}") {{
                  return 403;
              }}
              proxy_pass http://127.0.0.1:8080;
              proxy_set_header Host $host;
              proxy_set_header X-Real-IP $remote_addr;
              proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          }}

          location /healthz {{
              proxy_pass http://127.0.0.1:8080/healthz;
              proxy_set_header Host $host;
          }}
      }}
    owner: root:root
    permissions: '0644'

runcmd:
  - systemctl enable docker
  - systemctl start docker
  - ufw default deny incoming
  - ufw default allow outgoing
  - ufw allow 22/tcp
  - ufw allow 8888/tcp
  - ufw --force enable
  - docker pull searxng/searxng:latest
  - docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:8080:8080 -v /opt/searchclaw/settings.yml:/etc/searxng/settings.yml:ro searxng/searxng:latest
  - rm -f /etc/nginx/sites-enabled/default
  - ln -sf /etc/nginx/sites-available/searxng /etc/nginx/sites-enabled/searxng
  - systemctl enable nginx
  - systemctl restart nginx
"""


def get_client() -> Client:
    if not HETZNER_API_TOKEN:
        print("Error: HETZNER_API_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)
    return Client(token=HETZNER_API_TOKEN)


def get_ssh_key(client: Client):
    """Get the deploy SSH key, or None."""
    keys = client.ssh_keys.get_all(name=SSH_KEY_NAME)
    return keys[0] if keys else None


def create_servers(args: argparse.Namespace) -> None:
    """Create one or more CX22 VPS instances with Docker and SearXNG pre-installed."""
    if not SEARXNG_AUTH_TOKEN:
        print("Error: SEARXNG_AUTH_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    ssh_key = get_ssh_key(client)
    location = args.location or DEFAULT_LOCATION

    # Determine starting index for engine profile diversity
    existing = client.servers.get_all(label_selector=f"{LABEL_KEY}={LABEL_VALUE}")
    base_index = len(existing)

    for i in range(args.count):
        instance_index = base_index + i
        name = args.name if args.name and args.count == 1 else f"searchclaw-searxng-{int(time.time())}-{i}"

        print(f"Creating server '{name}' (type={SERVER_TYPE}, location={location}, profile={instance_index % len(ENGINE_PROFILES)})...")

        ssh_keys = [ssh_key] if ssh_key else []
        cloud_init = generate_cloud_init(instance_index, SEARXNG_AUTH_TOKEN)

        response = client.servers.create(
            name=name,
            server_type=ServerType(name=SERVER_TYPE),
            image=Image(name=IMAGE),
            location=Location(name=location),
            ssh_keys=ssh_keys,
            user_data=cloud_init,
            labels={LABEL_KEY: LABEL_VALUE, "role": "searxng"},
        )

        server = response.server
        print(f"  Server created: id={server.id}, status={server.status}")
        print(f"  IPv4: {server.public_net.ipv4.ip}")
        print(f"  IPv6: {server.public_net.ipv6.ip}")

        # Wait for server to be running
        print("  Waiting for server to be ready...")
        while True:
            server = client.servers.get_by_id(server.id)
            if server.status == "running":
                break
            time.sleep(3)

        print(f"  Server '{name}' is running.")
        print(f"  SearXNG will be available at http://{server.public_net.ipv4.ip}:8888 after cloud-init completes (~2-3 min)")
        print(f"  Manual deploy: ./scripts/deploy_searxng.sh {server.public_net.ipv4.ip}")
        print()


def list_servers(args: argparse.Namespace) -> None:
    """List all active SearchClaw VPS instances."""
    client = get_client()
    servers = client.servers.get_all(label_selector=f"{LABEL_KEY}={LABEL_VALUE}")

    if not servers:
        print("No SearchClaw servers found.")
        return

    print(f"{'ID':<10} {'Name':<35} {'Status':<10} {'IPv4':<16} {'Location':<8} {'Created'}")
    print("-" * 110)

    for server in servers:
        print(
            f"{server.id:<10} "
            f"{server.name:<35} "
            f"{server.status:<10} "
            f"{server.public_net.ipv4.ip:<16} "
            f"{server.datacenter.name:<8} "
            f"{server.created.strftime('%Y-%m-%d %H:%M')}"
        )


def destroy_server(args: argparse.Namespace) -> None:
    """Destroy a VPS instance by ID or name."""
    client = get_client()
    server = _resolve_server(client, args.server)

    print(f"Destroying server '{server.name}' (id={server.id}, ip={server.public_net.ipv4.ip})...")
    client.servers.delete(server)
    print("  Server destroyed.")


def rotate_server(args: argparse.Namespace) -> None:
    """Destroy a blocked VPS and create a replacement with a new IP."""
    client = get_client()
    old_server = _resolve_server(client, args.server)

    if not SEARXNG_AUTH_TOKEN:
        print("Error: SEARXNG_AUTH_TOKEN environment variable is required for rotate", file=sys.stderr)
        sys.exit(1)

    location = old_server.datacenter.location.name
    old_name = old_server.name
    old_ip = old_server.public_net.ipv4.ip

    print(f"Rotating server '{old_name}' (ip={old_ip}, location={location})...")

    # Destroy old server
    print("  Destroying old server...")
    client.servers.delete(old_server)
    print("  Old server destroyed.")

    # Determine instance index for engine profile
    existing = client.servers.get_all(label_selector=f"{LABEL_KEY}={LABEL_VALUE}")
    instance_index = len(existing)

    # Create replacement
    new_name = f"searchclaw-searxng-{int(time.time())}-0"
    print(f"  Creating replacement server '{new_name}'...")

    ssh_key = get_ssh_key(client)
    ssh_keys = [ssh_key] if ssh_key else []
    cloud_init = generate_cloud_init(instance_index, SEARXNG_AUTH_TOKEN)

    response = client.servers.create(
        name=new_name,
        server_type=ServerType(name=SERVER_TYPE),
        image=Image(name=IMAGE),
        location=Location(name=location),
        ssh_keys=ssh_keys,
        user_data=cloud_init,
        labels={LABEL_KEY: LABEL_VALUE, "role": "searxng"},
    )

    server = response.server

    # Wait for server to be running
    while True:
        server = client.servers.get_by_id(server.id)
        if server.status == "running":
            break
        time.sleep(3)

    print(f"  New server ready: id={server.id}, ip={server.public_net.ipv4.ip}")
    print(f"  SearXNG will be available at http://{server.public_net.ipv4.ip}:8888 after cloud-init (~2-3 min)")
    print()
    print(f"  Update API gateway config: replace {old_ip} with {server.public_net.ipv4.ip}")


def _resolve_server(client: Client, identifier: str):
    """Resolve a server by ID or name."""
    try:
        server_id = int(identifier)
        server = client.servers.get_by_id(server_id)
        if server:
            return server
    except (ValueError, Exception):
        pass

    server = client.servers.get_by_name(identifier)
    if server:
        return server

    print(f"Error: Server '{identifier}' not found", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Hetzner VPS instances for SearchClaw SearXNG nodes"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    create_parser = subparsers.add_parser("create", help="Create new VPS instance(s)")
    create_parser.add_argument("--name", help="Server name (auto-generated if omitted)")
    create_parser.add_argument("--count", type=int, default=1, help="Number of servers to create")
    create_parser.add_argument("--location", default=DEFAULT_LOCATION, help="Hetzner location (fsn1, nbg1, hel1)")
    create_parser.set_defaults(func=create_servers)

    # list
    list_parser = subparsers.add_parser("list", help="List all SearchClaw VPS instances")
    list_parser.set_defaults(func=list_servers)

    # destroy
    destroy_parser = subparsers.add_parser("destroy", help="Destroy a VPS instance")
    destroy_parser.add_argument("server", help="Server ID or name")
    destroy_parser.set_defaults(func=destroy_server)

    # rotate
    rotate_parser = subparsers.add_parser("rotate", help="Destroy and recreate a VPS (new IP)")
    rotate_parser.add_argument("server", help="Server ID or name to rotate")
    rotate_parser.set_defaults(func=rotate_server)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
