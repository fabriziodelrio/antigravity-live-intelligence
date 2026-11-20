#!/usr/bin/env python3
"""
Antigravity Live Server & Telemetry Dashboard
Avvia un server HTTP locale leggero con API JSON in tempo reale.
La dashboard interroga /api/stats ogni 3 secondi o al click su 'Aggiorna'.
"""

import os
import sys
import json
import sqlite3
import re
import datetime
import http.server
import socketserver
import webbrowser
from collections import defaultdict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORT = 4242
DB_PATH = os.path.expanduser(r"~\.gemini\antigravity\conversation_summaries.db")
BRAIN_DIR = os.path.expanduser(r"~\.gemini\antigravity\brain")
CONVERSATIONS_DIR = os.path.expanduser(r"~\.gemini\antigravity\conversations")

def parse_transcript(conversation_id):
    transcript_path = os.path.join(BRAIN_DIR, conversation_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(transcript_path):
        return None
    
    in_tok = 0
    out_tok = 0
    cache_tok = 0
    tool_cnt = 0
    models = set()
    
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    in_tok += data.get("input_tokens", 0)
                    out_tok += data.get("output_tokens", 0)
                    cache_tok += data.get("cache_read_tokens", 0)
                    
                    tcalls = data.get("tool_calls")
                    if tcalls:
                        tool_cnt += len(tcalls)
                    
                    content = data.get("content", "")
                    if content and "Model Selection" in content:
                        m = re.search(r"Model Selection` from (?:.*?) to (.*?)\.\s*No need", content)
                        cand = m.group(1).strip() if m else ""
                        if not cand:
                            m2 = re.search(r"Model Selection` from .*? to ([^.\n]+)", content)
                            cand = m2.group(1).strip() if m2 else ""
                        if cand and len(cand) > 3 and not cand.startswith("("):
                            models.add(cand)
                    
                    if "model" in data and data["model"]:
                        m_val = str(data["model"]).strip()
                        if len(m_val) > 3 and not m_val.startswith("("):
                            models.add(m_val)
                except Exception:
                    pass
    except Exception:
        return None
                
    return {
        "in_tokens": in_tok,
        "out_tokens": out_tok,
        "cache_tokens": cache_tok,
        "tool_calls": tool_cnt,
        "models": list(models) if models else ["Gemini 3.8 Flash (Default)"]
    }

def clean_workspace(ws_uri):
    if not ws_uri:
        return "Altro"
    clean = ws_uri.replace('["file:///', '').replace('"]', '').replace('file:///', '').replace('%3A', ':')
    clean = clean.split("/")[-1]
    return clean or "Globale"

def collect_data(limit=250):
    if not os.path.exists(DB_PATH):
        return [], {}
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT conversation_id, preview, last_modified_time, workspace_uris, step_count 
        FROM conversation_summaries 
        ORDER BY last_modified_time DESC 
        LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    sessions = []
    active_sessions_count = 0
    archived_sessions_count = 0
    
    totals = {
        "sessions": len(rows),
        "steps": 0,
        "in_tokens": 0,
        "out_tokens": 0,
        "cache_tokens": 0,
        "tool_calls": 0,
        "projects": defaultdict(lambda: {"count": 0, "active": 0, "in": 0, "out": 0, "cache": 0}),
        "models": defaultdict(lambda: {"count": 0, "in": 0, "out": 0}),
        "daily": defaultdict(lambda: {"count": 0, "active": 0, "steps": 0, "tools": 0, "in": 0, "out": 0, "cache": 0}),
        "weekly": defaultdict(lambda: {"count": 0, "active": 0, "steps": 0, "tools": 0, "in": 0, "out": 0, "cache": 0}),
        "monthly": defaultdict(lambda: {"count": 0, "active": 0, "steps": 0, "tools": 0, "in": 0, "out": 0, "cache": 0}),
        "windows": {
            "h5": {"count": 0, "in": 0, "out": 0, "cache": 0, "tools": 0},
            "today": {"count": 0, "in": 0, "out": 0, "cache": 0, "tools": 0},
            "d7": {"count": 0, "in": 0, "out": 0, "cache": 0, "tools": 0},
        },
        "by_bucket": {
            "gemini": {"in": 0, "out": 0, "cache": 0, "tools": 0},
            "argon": {"in": 0, "out": 0, "cache": 0, "tools": 0},
            "claude_gpt": {"in": 0, "out": 0, "cache": 0, "tools": 0},
        },
    }
    now_dt = datetime.datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    
    for row in rows:
        cid, title, last_mod, ws_uri, steps = row
        steps = steps or 0
        project = clean_workspace(ws_uri)
        
        try:
            dt_clean = last_mod.split(".")[0].replace("Z", "")
            dt = datetime.datetime.fromisoformat(dt_clean)
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            day_key = dt.strftime("%Y-%m-%d")
            iso_year, iso_week, _ = dt.isocalendar()
            week_key = f"{iso_year}-W{iso_week:02d}"
            month_key = dt.strftime("%Y-%m")
            is_today = (day_key == today_str)
            age_sec = (now_dt - dt).total_seconds()
            is_recent_48h = (age_sec <= 48 * 3600)
            is_5h = (age_sec <= 5 * 3600)
            is_7d = (age_sec <= 7 * 86400)
        except Exception:
            formatted_date = str(last_mod)[:16]
            day_key = formatted_date[:10]
            week_key = day_key[:7]
            month_key = day_key[:7]
            is_today = False
            is_recent_48h = False
            is_5h = False
            is_7d = False
            
        t_data = parse_transcript(cid)
        is_active = t_data is not None
        
        if is_active:
            active_sessions_count += 1
            in_tok = t_data["in_tokens"]
            out_tok = t_data["out_tokens"]
            cache_tok = t_data["cache_tokens"]
            tool_cnt = t_data["tool_calls"]
            model_str = ", ".join(t_data["models"])
            status_label = "VIVA"
        else:
            archived_sessions_count += 1
            in_tok = 0
            out_tok = 0
            cache_tok = 0
            tool_cnt = 0
            model_str = "Archiviata (Compattata)"
            status_label = "ARCHIVIATA"
            
        session_obj = {
            "id": cid,
            "title": title or "Senza Titolo",
            "date": formatted_date,
            "day": day_key,
            "is_today": is_today,
            "is_recent_48h": is_recent_48h,
            "project": project,
            "steps": steps,
            "in_tokens": in_tok,
            "out_tokens": out_tok,
            "cache_tokens": cache_tok,
            "tool_calls": tool_cnt,
            "model": model_str,
            "is_active": is_active,
            "status": status_label
        }
        sessions.append(session_obj)
        
        totals["steps"] += steps
        totals["in_tokens"] += in_tok
        totals["out_tokens"] += out_tok
        totals["cache_tokens"] += cache_tok
        totals["tool_calls"] += tool_cnt
        
        p = totals["projects"][project]
        p["count"] += 1
        if is_active:
            p["active"] += 1
        p["in"] += in_tok
        p["out"] += out_tok
        p["cache"] += cache_tok
        
        if is_active:
            for m in t_data["models"]:
                m_stat = totals["models"][m]
                m_stat["count"] += 1
                m_stat["in"] += in_tok
                m_stat["out"] += out_tok

            m_low = model_str.lower()
            if "argon" in m_low:
                b_cat = "argon"
            elif "claude" in m_low or "gpt" in m_low:
                b_cat = "claude_gpt"
            else:
                b_cat = "gemini"
            bk = totals["by_bucket"][b_cat]
            bk["in"] += in_tok
            bk["out"] += out_tok
            bk["cache"] += cache_tok
            bk["tools"] += tool_cnt

        for bucket_name, b_key in (("daily", day_key), ("weekly", week_key), ("monthly", month_key)):
            b = totals[bucket_name][b_key]
            b["count"] += 1
            if is_active:
                b["active"] += 1
            b["steps"] += steps
            b["tools"] += tool_cnt
            b["in"] += in_tok
            b["out"] += out_tok
            b["cache"] += cache_tok

        for w_key, cond in (("h5", is_5h), ("today", is_today), ("d7", is_7d)):
            if cond:
                w = totals["windows"][w_key]
                w["count"] += 1
                w["in"] += in_tok
                w["out"] += out_tok
                w["cache"] += cache_tok
                w["tools"] += tool_cnt

    totals["active_sessions"] = active_sessions_count
    totals["archived_sessions"] = archived_sessions_count
    totals["today_sessions"] = sum(1 for s in sessions if s["is_today"])
    totals["recent48_sessions"] = sum(1 for s in sessions if s["is_recent_48h"])
    totals["unique_projects"] = len(totals["projects"])
    totals["projects"] = dict(totals["projects"])
    totals["models"] = dict(totals["models"])
    totals["daily"] = dict(totals["daily"])
    totals["weekly"] = dict(totals["weekly"])
    totals["monthly"] = dict(totals["monthly"])
        
    return sessions, totals

INDEX_HTML = """<!DOCTYPE html>
<html lang="it" class="dark">
<head>
  <meta charset="UTF-8">
  <title>Antigravity Live Intelligence Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: '#6366f1',
            darkbg: '#0b0f19',
            darkcard: '#1e293b',
            darkborder: '#334155'
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #0b0f19; color: #f1f5f9; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
    .glow { box-shadow: 0 0 25px rgba(99, 102, 241, 0.15); }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #0b0f19; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body class="p-6 max-w-[1440px] mx-auto min-h-screen">
  
  <!-- Header -->
  <div class="flex flex-col md:flex-row justify-between items-start md:items-center pb-6 border-b border-darkborder mb-8 gap-4">
    <div>
      <div class="flex items-center gap-3">
        <span class="text-3xl">⚡</span>
        <h1 class="text-2xl font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">Antigravity Live Intelligence</h1>
      </div>
      <p class="text-slate-400 text-sm mt-1">Monitoraggio live del Brain locale &bull; Aggiornamento automatico ogni 3 secondi</p>
    </div>
    <div class="flex items-center gap-3">
      <span id="liveBadge" class="px-3 py-1.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span> <span id="liveStatusText">LIVE ATTIVO</span>
      </span>
      <button onclick="fetchData()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium transition shadow-lg shadow-indigo-600/30 flex items-center gap-2">
        <svg id="refreshIcon" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
        Aggiorna Ora
      </button>
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Sessioni Totali</div>
      <div id="kpiSessions" class="text-2xl font-bold text-white mt-1">-</div>
      <div id="kpiSessionsSub" class="text-xs text-slate-400 mt-1">-</div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Tool Calls</div>
      <div id="kpiToolCalls" class="text-2xl font-bold text-indigo-400 mt-1">-</div>
      <div id="kpiToolCallsSub" class="text-xs text-slate-400 mt-1">-</div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Input Tokens</div>
      <div id="kpiInTokens" class="text-2xl font-bold text-blue-400 mt-1">-</div>
      <div id="kpiInTokensSub" class="text-xs text-slate-400 mt-1">-</div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Output Tokens</div>
      <div id="kpiOutTokens" class="text-2xl font-bold text-purple-400 mt-1">-</div>
      <div id="kpiOutTokensSub" class="text-xs text-slate-400 mt-1">-</div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider text-emerald-400">Prompt Cache Read</div>
      <div id="kpiCacheTokens" class="text-2xl font-bold text-emerald-400 mt-1">-</div>
      <div class="text-xs text-slate-400 mt-1">risparmiati da cache</div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl p-4 glow">
      <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Progetti Attivi</div>
      <div id="kpiProjects" class="text-2xl font-bold text-amber-400 mt-1">-</div>
      <div class="text-xs text-slate-400 mt-1">workspace rilevati</div>
    </div>
  </div>

  <!-- Finestre Consumi Reali (Contatore da Reset / Oggi / 7 Giorni) -->
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
    <div class="bg-darkcard border border-emerald-900/60 rounded-xl px-4 py-3 flex flex-col justify-between gap-2">
      <div class="flex items-center justify-between gap-2">
        <div>
          <div class="flex items-center gap-2">
            <span class="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">Contatore da Reset</span>
            <button onclick="resetDeltaCounter()" class="px-2 py-0.5 rounded bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-700 text-[10px] font-semibold transition cursor-pointer">Reset Ora</button>
          </div>
          <div id="winDeltaMeta" class="text-[11px] text-slate-400 mt-0.5">-</div>
        </div>
        <div class="text-right font-mono">
          <div id="winDeltaInOut" class="text-xs font-bold text-slate-100">-</div>
          <div id="winDeltaCache" class="text-[10px] text-emerald-400">-</div>
        </div>
      </div>
      <div id="winDeltaBuckets" class="grid grid-cols-3 gap-1.5 pt-1.5 border-t border-slate-800 text-[10px] font-mono"></div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl px-4 py-3 flex items-center justify-between">
      <div>
        <div class="text-[11px] font-semibold uppercase tracking-wider text-blue-400">Consumo Oggi</div>
        <div id="winTodayMeta" class="text-xs text-slate-400 mt-0.5">-</div>
      </div>
      <div class="text-right font-mono">
        <div id="winTodayInOut" class="text-sm font-bold text-slate-100">-</div>
        <div id="winTodayCache" class="text-[11px] text-emerald-400">-</div>
      </div>
    </div>
    <div class="bg-darkcard border border-darkborder rounded-xl px-4 py-3 flex items-center justify-between">
      <div>
        <div class="text-[11px] font-semibold uppercase tracking-wider text-purple-400">Ultimi 7 Giorni</div>
        <div id="win7dMeta" class="text-xs text-slate-400 mt-0.5">-</div>
      </div>
      <div class="text-right font-mono">
        <div id="win7dInOut" class="text-sm font-bold text-slate-100">-</div>
        <div id="win7dCache" class="text-[11px] text-emerald-400">-</div>
      </div>
    </div>
  </div>

  <!-- 1. Tabella Dettaglio Sessioni (Subito in alto, a tutta larghezza) -->
  <div class="bg-darkcard border border-darkborder rounded-xl p-5 glow mb-8">
    <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 mb-4">
      <div>
        <h2 class="text-lg font-semibold text-slate-200 flex items-center gap-2">
          <span>📋</span> Sessioni & Consumi Live
        </h2>
        <p class="text-xs text-slate-400 mt-0.5">Vista predefinita su Oggi &bull; Filtra per periodo, stato o cerca per titolo/progetto</p>
      </div>
      
      <div class="flex flex-wrap items-center gap-2">
        <div class="inline-flex flex-wrap rounded-lg bg-slate-900 p-1 border border-darkborder text-xs gap-1">
          <button id="btn-today" onclick="setFilter('today')" class="filter-btn px-3 py-1 rounded-md font-medium bg-indigo-600 text-white transition">Oggi (<span id="countToday">-</span>)</button>
          <button id="btn-recent48" onclick="setFilter('recent48')" class="filter-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">48h (<span id="countRecent48">-</span>)</button>
          <button id="btn-active" onclick="setFilter('active')" class="filter-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">Attive (<span id="countActive">-</span>)</button>
          <button id="btn-all" onclick="setFilter('all')" class="filter-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">Tutte (<span id="countAll">-</span>)</button>
          <button id="btn-archived" onclick="setFilter('archived')" class="filter-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">Archivio (<span id="countArchived">-</span>)</button>
        </div>
        <input type="text" id="searchInput" onkeyup="renderTable()" placeholder="Cerca titolo, progetto..." 
               class="px-3 py-1.5 bg-slate-900 border border-darkborder rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-48 md:w-60 transition">
      </div>
    </div>

    <div class="rounded-lg border border-darkborder max-h-[480px] overflow-y-auto overflow-x-auto">
      <table class="w-full text-left text-xs border-collapse">
        <thead class="bg-slate-900 text-slate-400 uppercase font-semibold text-[11px] sticky top-0 z-10 border-b border-darkborder shadow-sm">
          <tr>
            <th class="py-2.5 px-3 w-20">Stato</th>
            <th class="py-2.5 px-2.5 w-32">Data/Ora</th>
            <th class="py-2.5 px-3">Titolo Sessione</th>
            <th class="py-2.5 px-2.5 w-28">Progetto</th>
            <th class="py-2.5 px-2.5">Modello</th>
            <th class="py-2.5 px-2 text-right w-14">Step</th>
            <th class="py-2.5 px-2 text-right w-14">Tools</th>
            <th class="py-2.5 px-2.5 text-right w-24">Input</th>
            <th class="py-2.5 px-2.5 text-right w-24">Output</th>
            <th class="py-2.5 px-3 text-right w-28">Cache Read</th>
          </tr>
        </thead>
        <tbody id="sessionsTbody" class="divide-y divide-darkborder text-slate-300"></tbody>
      </table>
    </div>
  </div>

  <!-- 2. Consumi Token per Periodo (Giorni / Settimane / Mesi) -->
  <div class="bg-darkcard border border-darkborder rounded-xl p-5 glow mb-8">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-4">
      <div>
        <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
          <span>📊</span> Consumi Token per Periodo
        </h2>
        <p class="text-xs text-slate-400 mt-0.5">Aggregazione Input, Output, Cache Read e sessioni nel tempo</p>
      </div>
      <div class="inline-flex rounded-lg bg-slate-900 p-1 border border-darkborder text-xs gap-1">
        <button id="period-daily" onclick="setPeriod('daily')" class="period-btn px-3 py-1 rounded-md font-medium bg-indigo-600 text-white transition">Giorni</button>
        <button id="period-weekly" onclick="setPeriod('weekly')" class="period-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">Settimane</button>
        <button id="period-monthly" onclick="setPeriod('monthly')" class="period-btn px-3 py-1 rounded-md font-medium text-slate-300 hover:text-white transition">Mesi</button>
      </div>
    </div>
    <div class="rounded-lg border border-darkborder max-h-[300px] overflow-y-auto overflow-x-auto">
      <table class="w-full text-left text-xs border-collapse">
        <thead class="bg-slate-900 text-slate-400 uppercase font-semibold text-[11px] sticky top-0 z-10 border-b border-darkborder">
          <tr>
            <th class="py-2.5 px-4">Periodo</th>
            <th class="py-2.5 px-3 text-right">Sessioni</th>
            <th class="py-2.5 px-3 text-right">Step</th>
            <th class="py-2.5 px-3 text-right">Tools</th>
            <th class="py-2.5 px-3 text-right">Input Tok</th>
            <th class="py-2.5 px-3 text-right">Output Tok</th>
            <th class="py-2.5 px-4 text-right">Cache Read</th>
            <th class="py-2.5 px-4 w-48">Volume Input</th>
          </tr>
        </thead>
        <tbody id="periodTbody" class="divide-y divide-darkborder text-slate-300"></tbody>
      </table>
    </div>
  </div>

  <!-- 3. Distribuzione Progetti e Modelli -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <!-- Progetti -->
    <div class="bg-darkcard border border-darkborder rounded-xl p-5 glow">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
          <span>📁</span> Sessioni per Progetto
        </h2>
        <span class="text-xs text-slate-400">Tutti i workspace</span>
      </div>
      <div id="projectsList" class="space-y-3 max-h-[300px] overflow-y-auto pr-1"></div>
    </div>

    <!-- Modelli AI -->
    <div class="bg-darkcard border border-darkborder rounded-xl p-5 glow">
      <div class="flex justify-between items-center mb-2">
        <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
          <span>🧠</span> Modelli AI (Sessioni Recenti & Telemetria Attiva)
        </h2>
        <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-950 text-purple-300 border border-purple-800">100% Modelli Reali</span>
      </div>
      <p class="text-xs text-slate-400 mb-4">Ripartizione precisa dei modelli rilevati nei prompt vivi di Antigravity:</p>
      <div id="modelsList" class="space-y-3.5 max-h-[260px] overflow-y-auto pr-1"></div>
      <div id="archivedNote" class="mt-4 pt-3 border-t border-darkborder text-xs text-slate-500 flex justify-between items-center"></div>
    </div>
  </div>

  <script>
    let currentFilter = 'today';
    let currentPeriod = 'daily';
    let allSessions = [];
    let latestTotals = {};
    let isFetching = false;

    function formatNumber(num) {
      return (num || 0).toLocaleString();
    }

    function formatTokens(num) {
      if (!num || num === 0) return "0";
      if (num >= 1000000) return (num / 1000000).toFixed(2) + "M";
      if (num >= 1000) return (num / 1000).toFixed(1) + "k";
      return num.toLocaleString();
    }

    const DELTA_KEY = "agy_delta_baseline_v2";

    function getDeltaBaseline() {
      try {
        const raw = localStorage.getItem(DELTA_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch {
        return null;
      }
    }

    function buildDeltaSnapshot() {
      const b = latestTotals.by_bucket || {};
      return {
        ts: Date.now(),
        in: latestTotals.in_tokens || 0,
        out: latestTotals.out_tokens || 0,
        cache: latestTotals.cache_tokens || 0,
        tools: latestTotals.tool_calls || 0,
        by_bucket: {
          gemini: { ...(b.gemini || { in: 0, out: 0 }) },
          argon: { ...(b.argon || { in: 0, out: 0 }) },
          claude_gpt: { ...(b.claude_gpt || { in: 0, out: 0 }) }
        }
      };
    }

    function resetDeltaCounter() {
      if (!latestTotals || typeof latestTotals.in_tokens !== "number") return;
      localStorage.setItem(DELTA_KEY, JSON.stringify(buildDeltaSnapshot()));
      renderDeltaCounter();
    }

    function renderDeltaCounter() {
      if (!latestTotals || typeof latestTotals.in_tokens !== "number") return;
      let base = getDeltaBaseline();
      if (!base) {
        base = buildDeltaSnapshot();
        localStorage.setItem(DELTA_KEY, JSON.stringify(base));
      }
      const dIn = Math.max(0, (latestTotals.in_tokens || 0) - base.in);
      const dOut = Math.max(0, (latestTotals.out_tokens || 0) - base.out);
      const dCache = Math.max(0, (latestTotals.cache_tokens || 0) - base.cache);
      const dTools = Math.max(0, (latestTotals.tool_calls || 0) - base.tools);
      const sinceStr = new Date(base.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      document.getElementById("winDeltaMeta").textContent = `Dal ${sinceStr} • +${formatNumber(dTools)} tools`;
      document.getElementById("winDeltaInOut").textContent = `+${formatTokens(dIn)} in / +${formatTokens(dOut)} out`;
      document.getElementById("winDeltaCache").textContent = `+cache ${formatTokens(dCache)}`;

      const curB = latestTotals.by_bucket || {};
      const baseB = base.by_bucket || {};
      const defs = [
        { k: "gemini", label: "Gemini", color: "text-blue-400" },
        { k: "argon", label: "Argon", color: "text-amber-400" },
        { k: "claude_gpt", label: "Claude/GPT", color: "text-purple-400" }
      ];
      document.getElementById("winDeltaBuckets").innerHTML = defs.map(d => {
        const c = curB[d.k] || { in: 0, out: 0 };
        const p = baseB[d.k] || { in: 0, out: 0 };
        const bi = Math.max(0, (c.in || 0) - (p.in || 0));
        const bo = Math.max(0, (c.out || 0) - (p.out || 0));
        return `<div class="bg-slate-900/70 rounded px-2 py-1"><div class="${d.color} font-semibold">${d.label}</div><div class="text-slate-300">+${formatTokens(bi)} / +${formatTokens(bo)}</div></div>`;
      }).join("");
    }

    function setFilter(filter) {
      currentFilter = filter;
      document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.remove('bg-indigo-600', 'text-white');
        b.classList.add('text-slate-300');
      });
      const activeBtn = document.getElementById('btn-' + filter);
      if (activeBtn) {
        activeBtn.classList.add('bg-indigo-600', 'text-white');
        activeBtn.classList.remove('text-slate-300');
      }
      renderTable();
    }

    function setPeriod(period) {
      currentPeriod = period;
      document.querySelectorAll('.period-btn').forEach(b => {
        b.classList.remove('bg-indigo-600', 'text-white');
        b.classList.add('text-slate-300');
      });
      const activeBtn = document.getElementById('period-' + period);
      if (activeBtn) {
        activeBtn.classList.add('bg-indigo-600', 'text-white');
        activeBtn.classList.remove('text-slate-300');
      }
      renderPeriods();
    }

    function renderPeriods() {
      const tbody = document.getElementById("periodTbody");
      const mapObj = latestTotals[currentPeriod] || {};
      const entries = Object.entries(mapObj).sort((a, b) => b[0].localeCompare(a[0]));
      const maxIn = entries.reduce((mx, cur) => Math.max(mx, cur[1].in || 0), 1);

      let html = "";
      entries.forEach(([label, stat]) => {
        const pct = Math.max(2, (((stat.in || 0) / maxIn) * 100)).toFixed(1);
        html += `
          <tr class="hover:bg-slate-800/40 transition">
            <td class="py-2.5 px-4 font-mono font-semibold text-slate-200 whitespace-nowrap">${label}</td>
            <td class="py-2.5 px-3 text-right font-mono text-slate-300">${stat.count} <span class="text-emerald-400 text-[10px]">(${stat.active} vive)</span></td>
            <td class="py-2.5 px-3 text-right font-mono text-slate-400">${formatNumber(stat.steps)}</td>
            <td class="py-2.5 px-3 text-right font-mono text-indigo-400">${formatNumber(stat.tools)}</td>
            <td class="py-2.5 px-3 text-right font-mono text-blue-400">${formatTokens(stat.in)}</td>
            <td class="py-2.5 px-3 text-right font-mono text-purple-400">${formatTokens(stat.out)}</td>
            <td class="py-2.5 px-4 text-right font-mono text-emerald-400">${formatTokens(stat.cache)}</td>
            <td class="py-2.5 px-4">
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-blue-500 h-1.5 rounded-full" style="width: ${pct}%"></div>
              </div>
            </td>
          </tr>
        `;
      });
      tbody.innerHTML = html || '<tr><td colspan="8" class="py-6 text-center text-slate-500">Nessun dato nel periodo</td></tr>';
    }

    function renderTable() {
      const input = document.getElementById("searchInput");
      const textFilter = (input.value || "").toLowerCase();
      const tbody = document.getElementById("sessionsTbody");
      
      let html = "";
      allSessions.forEach(s => {
        const typeMatch = (currentFilter === 'all') ||
                          (currentFilter === 'today' && s.is_today) ||
                          (currentFilter === 'recent48' && s.is_recent_48h) ||
                          (currentFilter === 'active' && s.is_active) ||
                          (currentFilter === 'archived' && !s.is_active);
        
        const fullText = (s.title + " " + s.project + " " + s.model + " " + s.status).toLowerCase();
        const searchMatch = fullText.indexOf(textFilter) > -1;

        if (typeMatch && searchMatch) {
          const in_fmt = s.in_tokens > 0 ? formatNumber(s.in_tokens) : "-";
          const out_fmt = s.out_tokens > 0 ? formatNumber(s.out_tokens) : "-";
          const cache_fmt = s.cache_tokens > 0 ? formatNumber(s.cache_tokens) : "-";

          let badgeHtml, modelHtml;
          if (s.is_active) {
            badgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">VIVA</span>';
            modelHtml = `<span class="font-medium text-purple-400 block max-w-[200px] truncate" title="${s.model}">${s.model}</span>`;
          } else {
            badgeHtml = '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">ARCH.</span>';
            modelHtml = '<span class="text-slate-500 italic whitespace-nowrap">Compattata</span>';
          }

          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2 px-3 whitespace-nowrap">${badgeHtml}</td>
              <td class="py-2 px-2.5 font-mono text-slate-400 whitespace-nowrap">${s.date}</td>
              <td class="py-2 px-3 font-semibold text-slate-200 max-w-[280px] truncate" title="${s.title}">${s.title}</td>
              <td class="py-2 px-2.5"><span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 whitespace-nowrap">${s.project}</span></td>
              <td class="py-2 px-2.5">${modelHtml}</td>
              <td class="py-2 px-2 text-right font-mono text-slate-400">${s.steps}</td>
              <td class="py-2 px-2 text-right font-mono text-indigo-400">${s.tool_calls}</td>
              <td class="py-2 px-2.5 text-right font-mono text-blue-400">${in_fmt}</td>
              <td class="py-2 px-2.5 text-right font-mono text-purple-400">${out_fmt}</td>
              <td class="py-2 px-3 text-right font-mono text-emerald-400">${cache_fmt}</td>
            </tr>
          `;
        }
      });
      tbody.innerHTML = html || '<tr><td colspan="10" class="py-6 text-center text-slate-500">Nessuna sessione trovata per questo filtro</td></tr>';
    }

    async function fetchData() {
      if (isFetching) return;
      isFetching = true;
      const icon = document.getElementById("refreshIcon");
      if (icon) icon.classList.add("animate-spin");

      try {
        const res = await fetch("/api/stats?t=" + Date.now());
        if (!res.ok) throw new Error("Errore API");
        const data = await res.json();
        
        allSessions = data.sessions;
        const totals = data.totals;
        latestTotals = totals;

        // KPI
        document.getElementById("kpiSessions").textContent = totals.sessions;
        document.getElementById("kpiSessionsSub").textContent = `${totals.active_sessions} attive • ${totals.archived_sessions} arch.`;
        document.getElementById("kpiToolCalls").textContent = formatNumber(totals.tool_calls);
        document.getElementById("kpiToolCallsSub").textContent = `${formatNumber(totals.steps)} step totali`;
        document.getElementById("kpiInTokens").textContent = formatTokens(totals.in_tokens);
        document.getElementById("kpiInTokensSub").textContent = `${formatNumber(totals.in_tokens)} token inviati`;
        document.getElementById("kpiOutTokens").textContent = formatTokens(totals.out_tokens);
        document.getElementById("kpiOutTokensSub").textContent = `${formatNumber(totals.out_tokens)} generati`;
        document.getElementById("kpiCacheTokens").textContent = formatTokens(totals.cache_tokens);
        document.getElementById("kpiProjects").textContent = totals.unique_projects;

        // Contatore da Reset (localStorage) + Oggi / 7d
        const w = totals.windows || {};
        const renderWin = (prefix, obj) => {
          const o = obj || { count: 0, tools: 0, in: 0, out: 0, cache: 0 };
          document.getElementById(prefix + "Meta").textContent = `${o.count} sess. • ${formatNumber(o.tools)} tools`;
          document.getElementById(prefix + "InOut").textContent = `${formatTokens(o.in)} in / ${formatTokens(o.out)} out`;
          document.getElementById(prefix + "Cache").textContent = `cache ${formatTokens(o.cache)}`;
        };
        renderDeltaCounter();
        renderWin("winToday", w.today);
        renderWin("win7d", w.d7);

        document.getElementById("countToday").textContent = totals.today_sessions;
        document.getElementById("countRecent48").textContent = totals.recent48_sessions;
        document.getElementById("countAll").textContent = totals.sessions;
        document.getElementById("countActive").textContent = totals.active_sessions;
        document.getElementById("countArchived").textContent = totals.archived_sessions;

        // Progetti
        const projSorted = Object.entries(totals.projects).sort((a,b) => b[1].count - a[1].count);
        let projHtml = "";
        const maxProjCount = projSorted.length > 0 ? projSorted[0][1].count : 1;
        projSorted.forEach(([pName, pStat]) => {
          const pct = ((pStat.count / maxProjCount) * 100).toFixed(1);
          const inFmt = pStat.in > 0 ? `${formatTokens(pStat.in)} in-tok` : 'storico';
          projHtml += `
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span class="font-medium text-slate-300">${pName}</span>
                <span class="text-slate-400">${pStat.count} sess. • ${inFmt}</span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-indigo-500 h-1.5 rounded-full" style="width: ${pct}%"></div>
              </div>
            </div>
          `;
        });
        document.getElementById("projectsList").innerHTML = projHtml;

        // Modelli
        const modSorted = Object.entries(totals.models).sort((a,b) => b[1].count - a[1].count);
        const totalModPrompts = modSorted.reduce((acc, cur) => acc + cur[1].count, 0) || 1;
        let modHtml = "";
        modSorted.forEach(([mName, mStat]) => {
          const share = ((mStat.count / totalModPrompts) * 100).toFixed(1);
          modHtml += `
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span class="font-medium text-purple-300">${mName}</span>
                <span class="text-slate-400">${mStat.count} sessioni (${share}%)</span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-purple-500 h-1.5 rounded-full" style="width: ${share}%"></div>
              </div>
            </div>
          `;
        });
        document.getElementById("modelsList").innerHTML = modHtml;
        document.getElementById("archivedNote").innerHTML = `
          <span>📦 Sessioni storiche compattate da Antigravity:</span>
          <span class="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono">${totals.archived_sessions} sessioni</span>
        `;

        renderTable();
        renderPeriods();
      } catch (e) {
        console.error("Poll error:", e);
      } finally {
        isFetching = false;
        if (icon) icon.classList.remove("animate-spin");
      }
    }

    // Polling automatico ogni 3 secondi
    fetchData();
    setInterval(fetchData, 3000);
  </script>
</body>
</html>
"""

class LiveHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/stats"):
            try:
                sessions, totals = collect_data(limit=250)
                data = json.dumps({"sessions": sessions, "totals": totals})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        # Mute console request logging to keep terminal clean
        return

def main():
    socketserver.TCPServer.allow_reuse_address = True
    try:
        server = http.server.ThreadingHTTPServer(("", PORT), LiveHandler)
    except Exception:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), LiveHandler)
    with server as httpd:
        url = f"http://localhost:{PORT}"
        if sys.stdout is not None:
            print(f"🚀 Antigravity Live Server attivo su: {url}")
            print("⚡ Polling automatico attivo ogni 3 secondi.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            if sys.stdout is not None:
                print("\nServer arrestato.")

if __name__ == "__main__":
    main()
