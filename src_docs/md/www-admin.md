# www-admin integration

`api.fontlab.com/www-admin/` is a password-protected PHP admin UI that lets
FontLab editors rebuild web properties and publish blog posts without SSH
access.  It triggers `fontlab-www-toolkit` remotely via a shell command.

## Architecture

```
Browser (editor)
    │  HTTPS POST /www-admin/build.php
    ▼
api.fontlab.com  (PHP)
    │  shell_exec("uv run fontlab-www-toolkit build --skip_webflow")
    ▼
fontlab-www-toolkit  (Python, installed in /www-admin/venv/)
    │  four-layer build
    ▼
public/  →  rsync  →  live site
```

## Setup command

The toolkit ships a `setup` subcommand that creates a `uv`-managed virtual
environment in the admin's working directory:

```bash
fontlab-www-toolkit setup --venv /www-admin/venv --clear
```

This is called once after deployment.  The `--clear` flag tears down and
recreates the venv, useful after a `pip install` conflict.

## Recommended admin call pattern

The PHP admin should call the toolkit with `--skip_webflow` during routine
content builds (blog posts, editorial copy) to avoid hitting the Webflow network
on every publish.  The Webflow cache is refreshed manually or on a schedule:

```php
// Routine build (fast, no network)
shell_exec('uv run fontlab-www-toolkit build --skip_webflow 2>&1');

// Webflow refresh (infrequent, updates wf_cache/)
shell_exec('uv run fontlab-www-toolkit pull-webflow 2>&1');
```

## Publishing sites that build elsewhere (`mirror`)

`studio.fontlab.com/tth-debugger` is built by `github.com/fontlab/tth-debugger`
CI and published to GitHub Pages at
`https://fontlab.dev/tth-debugger/alpha-sdx992/` together with a
`manifest.json`. The admin republishes it with:

```bash
fontlab-www-toolkit mirror \
  --manifest_url https://fontlab.dev/tth-debugger/alpha-sdx992/manifest.json \
  --dest "$LIVE/studio.fontlab.com/public/tth-debugger"
```

See the README section "Mirroring a published static site" for the manifest
schema.

## Environment variables

| Variable | Description |
|---|---|
| `UV_PUBLISH_TOKEN` | PyPI token (only needed in `publish.sh`, not in admin) |
| `FONTLAB_WEB_ROOT` | Optional: override the site repo root instead of passing `--root` |

## Security notes

- The PHP admin is password-protected at the HTTP level (`.htaccess`).
- The toolkit itself does not perform authentication; access control is entirely
  the responsibility of the PHP layer.
- `uv run` is called with the site repo as the working directory; there is no
  privilege escalation.
- The `wf_cache/` directory is writable by the web server user only when
  `pull-webflow` is called; build-only runs do not write to disk (aside from
  `build_docs/` and `public/`).

## Per-site config file

Each consumer site can have a `fontlab-www-toolkit.json` in its root:

```json
{
  "frontmatter_key": "webflow-import-url",
  "split_google_fonts": true,
  "rocket_loader_optout": true,
  "cloudinary": {
    "cl_cloud": "fontlab",
    "cl_map": {
      "https://cdn.prod.website-files.com/SITE_ID": "wf"
    },
    "cl_trans": "c_limit,w_auto/f_auto,q_auto,dpr_auto/",
    "cl_responsive": {
      "methodology": "modern",
      "lazyload": "observer",
      "placeholder": "blur"
    }
  }
}
```

Pass a non-default path with `--config`:

```bash
fontlab-www-toolkit build --config /etc/fontlab/www-fontlab-com.json
```
