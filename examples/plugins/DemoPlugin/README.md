# DemoPlugin (example package)

This is a *placeholder* CounterStrikeSharp plugin package used to try out
`cs2-link-manager` without downloading a real plugin.

It mirrors the standard release layout produced by many CSS plugins:

```
DemoPlugin/
└── addons/
    └── counterstrikesharp/
        ├── plugins/
        │   └── DemoPlugin/
        │       ├── DemoPlugin.dll        (placeholder)
        │       └── DemoPlugin.deps.json
        └── configs/
            └── plugins/
                └── DemoPlugin/
                    └── DemoPlugin.json
```

`DemoPlugin.dll` is a text file, **not a real assembly** — it exists only so
the package can be exercised in a test/simulation server.

## Try it

```bash
cs2lm init --repo ./plugins-repo --server ./cs2-server
cs2lm add DemoPlugin ./examples/plugins/DemoPlugin
cs2lm install DemoPlugin
cs2lm list
cs2lm doctor
cs2lm uninstall DemoPlugin
```