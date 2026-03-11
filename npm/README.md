# openrag

npm installer for [OpenRAG](https://github.com/langflow-ai/openrag) — Intelligent Agent-powered document search and RAG platform.

## Install

```bash
npm install -g openrag
```

This will:
1. Install the `openrag` npm package
2. Automatically install the Python `openrag` package using the best available tool (`uv` > `pipx` > `pip`)

## Requirements

- **Node.js** >= 16
- **Python** >= 3.13

## Usage

```bash
openrag
```

After installation, the `openrag` command is available globally. Run it to start the setup walkthrough, or use `openrag --tui` for the full terminal UI.

## How it works

This is a thin npm wrapper around the Python [openrag](https://pypi.org/project/openrag/) package. The `postinstall` script handles installing the Python package, and the `openrag` bin script delegates to the installed Python CLI.
