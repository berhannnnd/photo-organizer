# Photo Organizer

Local photo organization for tool-capable agents: a shared Python engine, JSON CLI,
stdio MCP server, and portable Skill. Original images are preserved; selection and
execution are represented by durable result IDs and plans.

**Status: development alpha, not a community-ready release yet.** The
[PRD](docs/PRD.md) defines the complete target. The
[delivery checklist](docs/DELIVERY.md) distinguishes implemented features from release gates.
Source: https://github.com/berhannnnd/photo-organizer. No package registry release yet.

## Install from a checkout

Python 3.11+ on macOS or Linux (POSIX file APIs). macOS has local test evidence;
Linux CI is configured but not yet executed remotely. Windows is unsupported.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[mcp]'
photo-organizer --state /absolute/library-state call capabilities
```

The core installation `pip install .` needs Pillow, not a model server. The `mcp`
extra installs the official MCP Python SDK. No credentials or model downloads are
required for metadata search, result snapshots, albums, copying or compression.

## A complete local workflow

Use a separate state directory outside your source tree. Keep this same state path
when switching agents or restarting sessions.

```sh
photo-organizer --state /absolute/library-state call scan --args '{"root":"/absolute/photos"}'
photo-organizer --state /absolute/library-state call search --args '{"rule":{"orientation":"landscape"}}'
# Substitute the actual result_set_id returned above.
photo-organizer --state /absolute/library-state call plan --args '{"spec":{"result_set_id":"RESULT_ID","group_by":"month"},"mode":"copy","target":"/absolute/organized"}'
# Inspect the returned plan before executing it within the user's authorization.
photo-organizer --state /absolute/library-state call apply --args '{"plan_id":"PLAN_ID"}'
```

No EXIF capture date means `date-unknown`. Download times are not capture times.
The target must be outside source roots. Existing destinations are never overwritten.
Read `status`, `error`, and per-action errors; partial failure is not success.

## Agent integration

Install or reference [the Skill](skills/photo-organizer/SKILL.md) using your host's
Skill mechanism. It is also included in the wheel under
`share/photo-organizer/skills/photo-organizer` relative to the installation prefix.
The [tool reference](skills/photo-organizer/references/tools.md) describes valid rules.

For a host supporting local stdio MCP, adapt its configuration to launch:

```json
{
  "mcpServers": {
    "photo-organizer": {
      "command": "/absolute/venv/bin/photo-organizer-mcp",
      "args": ["--state", "/absolute/library-state"]
    }
  }
}
```

This local process runs with the permissions of its user. It is not a remote,
multi-tenant service or an authentication boundary. Only connect it to trusted hosts
and operate on user-authorized directories. The host decides tool authorization.

## Optional visual facts

Copy [the example config](examples/provider.json) outside the repository, set the
exact image-capable model and endpoint, and set the named environment variable using
your shell or secret manager. The engine supports Anthropic-compatible image requests
in this alpha. CC Switch import remains optional legacy functionality.

```sh
photo-organizer --state /absolute/library-state index --config /absolute/provider.json --limit 5
```

This sends derived images to the configured provider. Start with an authorized small
batch and inspect evidence. Build a separate local vector index with `call embed-index`, then the observation
text index with `call describe-index`; `call retrieve` returns ranked candidates.
Same-person grouping and durable background jobs are still pending. Multi-level
grouping is available through `levels` (see the tool reference). Missing tags never prove that a subject is absent.

## Development and evidence

```sh
python -m pip install '.[mcp,dev]'
python -m unittest discover -s tests -v
python -m build
```

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) ·
[PRD](docs/PRD.md) · [Delivery status](docs/DELIVERY.md).

The existing local 1000-photo dataset is not distributed in the package. Its original
source metadata and per-image licensing must be preserved; the MIT code license does
not relicense photographs. See [LICENSE](LICENSE).
