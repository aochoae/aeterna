# Aeterna documentation

The documentation is built with Sphinx. From the repository root, install the
`docs` dependency group and build the HTML site:

```bash
uv sync --locked --group docs
uv run python -m sphinx -W --keep-going -b html docs docs/_build/html
```

The generated site is in `docs/_build/html/index.html`. The guides describe
the checked-out source under `packages/*/src`, so examples and API references
should be updated with the implementation.

Read the Docs builds these pages with `-W`, so any Sphinx warning fails the
documentation build.
