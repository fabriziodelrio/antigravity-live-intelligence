[English](README.md) | [Italiano](README.it.md)
# Antigravity Live Intelligence

Local real-time dashboard to monitor Google Antigravity usage: sessions, input/output/cache tokens, tools called, and models used.

## Features
- Lightweight local HTTP server (Python standard library only, zero dependencies)
- JSON API at `/api/stats`, dashboard auto-refreshing every 3 seconds
- Reads local Antigravity logs (`~/.gemini/antigravity`): no data leaves your PC
- `antigravity_stats.py`: generates a static HTML report

## Requirements
Python 3.8+ and Antigravity must have been used at least once.

## Starting
```bash
python antigravity_live_server.py
```
The browser will open at http://localhost:4242

Static report:
```bash
python antigravity_stats.py
```

## Privacy
Everything stays local. The generated static report contains your project names: do not publish it.

## License
MIT

