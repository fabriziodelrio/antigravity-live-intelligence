[English](README.md) | [Italiano](README.it.md)

# Antigravity Live Intelligence

Dashboard locale in tempo reale per monitorare l'uso di Google Antigravity: sessioni, token in input/output/cache, tool chiamati e modelli usati.

## Funzionalità
- Server HTTP locale leggero (solo libreria standard Python, zero dipendenze)
- API JSON su `/api/stats`, dashboard con aggiornamento automatico ogni 3 secondi
- Legge i log locali di Antigravity (`~/.gemini/antigravity`): nessun dato lascia il tuo PC
- `antigravity_stats.py`: genera un report HTML statico

## Requisiti
Python 3.8+ e Antigravity già usato almeno una volta.

## Avvio
```bash
python antigravity_live_server.py
```
Si apre il browser su http://localhost:4242

Report statico:
```bash
python antigravity_stats.py
```

## Privacy
Tutto resta in locale. Il report statico generato contiene i nomi dei tuoi progetti: non pubblicarlo.

## Licenza
MIT

