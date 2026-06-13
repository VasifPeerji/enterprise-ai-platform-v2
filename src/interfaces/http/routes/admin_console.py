"""
Visual admin console for provisioning external chatbot widgets.

Served at ``GET /admin/console`` on the main app (strict CORS, internal). It is a
thin, dependency-free single page that drives the existing admin + grounded-
document APIs over same-origin fetch: create/edit/delete bots, live-preview the
theme as you change it, copy the embed snippet, and crawl a website into a bot's
knowledge collection. This is what makes the "re-skin per company with no code"
story usable without hand-writing JSON.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/admin", tags=["Admin · Console"])


ADMIN_CONSOLE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Widget Console</title>
<style>
  :root {
    --bg:#f5f1ea; --panel:#fffdf8; --ink:#1f2a2e; --muted:#5f6c70; --line:#e0d8cb;
    --accent:#0f766e; --accent-soft:#d7efe9; --danger:#9a3412;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    background:var(--bg); color:var(--ink); }
  header { padding:18px 24px; border-bottom:1px solid var(--line); background:var(--panel); }
  header h1 { margin:0; font-size:1.3rem; }
  header p { margin:4px 0 0; color:var(--muted); font-size:.85rem; }
  .wrap { max-width:1240px; margin:0 auto; padding:20px 24px 60px; }
  .grid { display:grid; grid-template-columns:1.1fr .9fr; gap:20px; align-items:start; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:18px; }
  .card h2 { margin:0 0 14px; font-size:1rem; }
  label { display:block; font-size:.78rem; color:var(--muted); margin:10px 0 4px; font-weight:600; }
  label.ck { display:flex; align-items:center; gap:8px; cursor:pointer; }
  label.ck input, .flags input { width:auto; }
  .flags { display:flex; gap:18px; flex-wrap:wrap; margin-top:12px; }
  .flags label { display:flex; align-items:center; gap:7px; margin:0; cursor:pointer; }
  input[type=text], input[type=url], textarea, select {
    width:100%; border:1px solid #cfc6b8; border-radius:9px; padding:9px 11px; font:inherit;
    background:#fff; color:var(--ink); }
  textarea { min-height:64px; resize:vertical; }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .row3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
  .swatch { display:flex; align-items:center; gap:8px; }
  .swatch input[type=color] { width:42px; height:34px; padding:0; border:1px solid #cfc6b8; border-radius:8px; background:#fff; }
  .btn { border:none; border-radius:9px; padding:10px 16px; font:inherit; font-weight:600; cursor:pointer; }
  .btn.primary { background:var(--accent); color:#fff; }
  .btn.ghost { background:transparent; border:1px solid var(--line); color:var(--ink); }
  .btn.danger { background:transparent; border:1px solid var(--danger); color:var(--danger); }
  .btn.sm { padding:6px 10px; font-size:.8rem; }
  .actions { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
  .hint { font-size:.74rem; color:var(--muted); margin-top:4px; }
  .toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff;
    padding:10px 16px; border-radius:9px; font-size:.85rem; opacity:0; transition:opacity .2s; pointer-events:none; z-index:50; }
  .toast.show { opacity:1; }
  .bot { border:1px solid var(--line); border-radius:11px; padding:12px 14px; margin-bottom:10px; }
  .bot .top { display:flex; justify-content:space-between; align-items:center; gap:10px; }
  .bot .name { font-weight:600; }
  .bot .meta { font-size:.74rem; color:var(--muted); }
  .snippet { background:#2b2b2b; color:#e8e8e8; font-family:ui-monospace,Consolas,monospace; font-size:.72rem;
    padding:8px 10px; border-radius:8px; margin-top:8px; word-break:break-all; }
  .warn { background:#fdf2e7; border:1px solid #f0c9a3; color:var(--danger); padding:8px 10px; border-radius:8px; font-size:.78rem; margin-top:8px; }
  .ok { background:var(--accent-soft); border:1px solid #aee0d6; color:#0c5b54; padding:8px 10px; border-radius:8px; font-size:.78rem; margin-top:8px; }

  /* ---- mode toggle + AutoPilot ---- */
  .modebar { display:flex; gap:6px; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:6px; margin-bottom:18px; }
  .modebar button { flex:1; border:none; background:transparent; color:var(--muted); font:inherit; font-weight:600; padding:10px; border-radius:9px; cursor:pointer; }
  .modebar button.on { background:var(--accent); color:#fff; }
  .ap-card { background:linear-gradient(135deg,rgba(15,118,110,.06),rgba(79,70,229,.06)); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:18px; }
  .ap-card h2 { margin:0 0 4px; font-size:1rem; }
  .ap-row { display:flex; gap:10px; margin-top:12px; }
  .ap-row input { flex:1; }
  .ap-run { white-space:nowrap; }
  .ap-run:disabled { opacity:.6; cursor:default; }
  .spin { display:inline-block; width:13px; height:13px; border:2px solid rgba(255,255,255,.5); border-top-color:#fff; border-radius:50%; animation:spin .7s linear infinite; vertical-align:-2px; margin-right:5px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .ap-clearbg { font-size:.72rem; color:var(--accent); cursor:pointer; text-decoration:underline; }
  .sw { width:18px; height:18px; border-radius:4px; border:1px solid rgba(0,0,0,.12); display:inline-block; }
  .hidden { display:none !important; }

  /* ---- live preview: faithful replica of the real widget panel (docked size 420x720) ----
     Mirrors widget.py's loader CSS values 1:1 so the console preview matches the embedded widget. */
  .preview-stage { position:relative; background:repeating-linear-gradient(45deg,#eee,#eee 12px,#e7e7e7 12px,#e7e7e7 24px);
    border:1px solid var(--line); border-radius:12px; height:830px; overflow:hidden; }
  .pv { position:absolute; bottom:92px; right:18px; width:420px; max-width:calc(100% - 28px); height:720px;
    background:var(--p-surface); color:var(--p-text); border-radius:var(--p-radius); overflow:hidden;
    box-shadow:0 28px 72px -18px rgba(0,0,0,.34),0 8px 24px -12px rgba(0,0,0,.16);
    display:flex; flex-direction:column; font-family:var(--p-font); line-height:1.5; }
  .pv.left { right:auto; left:18px; }
  .pv * { box-sizing:border-box; }
  /* header */
  .pv-head { position:relative; background:var(--p-primary);
    background-image:linear-gradient(135deg,rgba(255,255,255,.14),rgba(0,0,0,.10));
    color:#fff; padding:17px 16px 17px 18px; display:flex; align-items:center; gap:12px; flex-shrink:0; }
  .pv-av { position:relative; width:42px; height:42px; border-radius:50%; display:flex; align-items:center; justify-content:center;
    background:rgba(255,255,255,.22); color:#fff; font-weight:600; font-size:17px; overflow:hidden; flex-shrink:0; }
  .pv-av img { width:100%; height:100%; object-fit:cover; }
  .pv-av::after { content:""; position:absolute; bottom:-1px; right:-1px; width:11px; height:11px; border-radius:50%;
    background:#34d399; border:2.5px solid var(--p-primary); }
  .pv-hmeta { flex:1; min-width:0; }
  .pv-name { font-weight:600; font-size:16px; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .pv-status { font-size:12.5px; opacity:.92; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .pv-ib { background:transparent; border:none; color:#fff; opacity:.85; padding:7px; border-radius:9px; display:flex; cursor:default; }
  .pv-ib svg { width:19px; height:19px; }
  /* messages */
  .pv-body { flex:1; overflow-y:auto; padding:18px 16px 6px; display:flex; flex-direction:column; gap:14px; }
  .pv-body::-webkit-scrollbar { width:6px; }
  .pv-body::-webkit-scrollbar-thumb { background:var(--p-line); border-radius:3px; }
  .pv-welcome { padding:10px 4px 8px; }
  .pv-wt { font-size:17.5px; font-weight:600; line-height:1.4; letter-spacing:-.01em; color:var(--p-text); }
  .pv-ws { font-size:13.5px; color:var(--p-muted); line-height:1.55; margin-top:7px; }
  .pv-chips { display:flex; flex-direction:column; gap:8px; padding:2px 16px 14px; }
  .pv-chip { display:flex; align-items:center; justify-content:space-between; gap:8px; text-align:left;
    border:1px solid var(--p-line); background:var(--p-surface); color:var(--p-text); border-radius:14px; padding:12px 14px; font-size:13.5px; }
  .pv-chip .ar { color:var(--p-primary); opacity:.55; flex-shrink:0; display:flex; }
  .pv-chip .ar svg { width:15px; height:15px; }
  /* message rows */
  .pv-row { position:relative; display:flex; gap:8px; align-items:flex-end; max-width:90%; }
  .pv-row.user { align-self:flex-end; flex-direction:row-reverse; }
  .pv-row.bot { align-self:flex-start; }
  .pv-ava { width:28px; height:28px; border-radius:50%; flex-shrink:0; background:var(--p-primary); color:#fff;
    display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:600; overflow:hidden; }
  .pv-ava img { width:100%; height:100%; object-fit:cover; }
  .pv-bubble { padding:11px 15px; border-radius:18px; font-size:14.5px; line-height:1.55; word-wrap:break-word; }
  .pv-row.user .pv-bubble { background:var(--p-user); color:#fff; border-bottom-right-radius:6px; }
  .pv-row.bot .pv-bubble { background:var(--p-bubble); color:var(--p-text); border:1px solid var(--p-line); border-bottom-left-radius:6px; }
  .pv-sources { margin-top:10px; padding-top:9px; border-top:1px solid var(--p-line); display:flex; flex-direction:column; gap:5px; }
  .pv-sources .h { font-size:10px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; opacity:.5; }
  .pv-sources a { font-size:12.5px; color:var(--p-accent); text-decoration:none; line-height:1.35; }
  /* composer */
  .pv-composer { padding:10px 14px 12px; border-top:1px solid var(--p-line); flex-shrink:0; }
  .pv-inwrap { display:flex; align-items:center; gap:6px; background:var(--p-soft); border:1px solid var(--p-line);
    border-radius:24px; padding:5px 5px 5px 16px; }
  .pv-ta { flex:1; font-size:14.5px; color:var(--p-muted); padding:7px 0; }
  .pv-send { width:38px; height:38px; flex-shrink:0; border-radius:50%; background:var(--p-primary); color:#fff;
    display:flex; align-items:center; justify-content:center; }
  .pv-send svg { width:17px; height:17px; }
  .pv-pwr { text-align:center; font-size:11px; color:var(--p-muted); opacity:.85; padding:9px 0 1px; }
  /* launcher */
  .pv-launch { position:absolute; bottom:18px; right:18px; width:62px; height:62px; border-radius:50%;
    background:var(--p-primary); color:#fff; display:flex; align-items:center; justify-content:center;
    box-shadow:0 8px 24px -4px rgba(0,0,0,.30),0 3px 8px -2px rgba(0,0,0,.18); }
  .pv-launch.left { right:auto; left:18px; }
  .pv-launch svg { width:27px; height:27px; }
  @media (max-width:980px){ .grid{ grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Widget Console</h1>
  <p>Create, theme, and preview an embeddable chatbot for any company — then paste one script tag on their site.</p>
</header>
<div class="wrap">
  <div class="grid">
    <!-- LEFT: config -->
    <div>
      <div class="modebar">
        <button id="modeAuto" class="on" onclick="setMode('auto')">✨ AutoPilot</button>
        <button id="modeManual" onclick="setMode('manual')">✍️ Manual</button>
      </div>

      <div class="ap-card" id="apCard">
        <h2>✨ AutoPilot — build a bot from a URL</h2>
        <div class="hint" style="margin-top:0">Paste a website. AutoPilot screenshots it, picks brand colors, writes the copy, and floats the bot over the real site. Review, then Create.</div>
        <div class="ap-row">
          <input id="ap_url" type="url" placeholder="https://prospect-company.com" onkeydown="if(event.key==='Enter')runAutopilot()">
          <button class="btn primary ap-run" id="apRun" onclick="runAutopilot()">Run AutoPilot</button>
        </div>
        <label class="ck" style="margin-top:10px"><input id="ap_crawl" type="checkbox" checked> Also crawl the site into the knowledge base</label>
        <div id="apMsg"></div>
      </div>

      <div class="card">
        <h2 id="formTitle">Create a bot</h2>
        <div class="row">
          <div><label>Tenant ID</label><input id="tenant_id" type="text" value="acme"></div>
          <div><label>Collection ID (knowledge base)</label><input id="collection_id" type="text" value="acme-kb"></div>
        </div>
        <label>Display name</label><input id="display_name" type="text" value="Acme Assistant">
        <label>Greeting</label><input id="greeting" type="text" value="Hi! How can I help you today?">
        <div class="row">
          <div><label>Subtitle (header status)</label><input id="subtitle" type="text" value="Typically replies instantly"></div>
          <div><label>Branding footer <span class="hint">(blank = hidden)</span></label><input id="branding" type="text" value="Powered by Smart Routing"></div>
        </div>
        <label>Teaser bubble <span class="hint">— proactive nudge near the launcher</span></label>
        <input id="teaser" type="text" value="Hi there 👋 Have a question? I'm here to help.">
        <label class="ck"><input id="show_teaser" type="checkbox" checked> Show the proactive teaser bubble</label>
        <label>Suggested prompts <span class="hint">— one per line, format: <code>Label | the actual question</code></span></label>
        <textarea id="prompts">Pricing | What are your prices?
Support | How do I contact support?</textarea>
        <label>Allowed origins <span class="hint">— one per line (exact scheme://host[:port]); required to enable</span></label>
        <textarea id="origins">http://localhost:5500</textarea>
      </div>

      <div class="card">
        <h2>Theme</h2>
        <div class="row3">
          <div><label>Primary</label><div class="swatch"><input id="primary_color" type="color" value="#4f46e5"></div></div>
          <div><label>Accent</label><div class="swatch"><input id="accent_color" type="color" value="#4f46e5"></div></div>
          <div><label>Surface</label><div class="swatch"><input id="surface_color" type="color" value="#ffffff"></div></div>
        </div>
        <div class="row3">
          <div><label>Text</label><div class="swatch"><input id="text_color" type="color" value="#1f2937"></div></div>
          <div><label>User bubble <span class="hint">(visitor)</span></label><div class="swatch"><input id="user_bubble_color" type="color" value="#4f46e5"></div></div>
          <div><label>Bot bubble <span class="hint">(assistant message)</span></label>
            <div class="swatch"><input id="bot_bubble_color" type="color" value="#f3f4f6">
              <label class="ck" style="margin:0;font-weight:600;font-size:.74rem"><input id="bot_bubble_auto" type="checkbox" checked> Auto</label></div></div>
        </div>
        <div class="row3">
          <div><label>Corner radius</label><input id="corner_radius_px" type="range" min="0" max="32" value="18"></div>
          <div><label>Launcher position</label>
            <select id="launcher_position"><option value="bottom-right">bottom-right</option><option value="bottom-left">bottom-left</option></select></div>
          <div><label>Font family</label><input id="font_family" type="text" value="system-ui, sans-serif"></div>
        </div>
        <div class="row3">
          <div><label>Logo URL (optional)</label><input id="logo_url" type="url" placeholder="https://…"></div>
          <div><label>Web font URL (optional)</label><input id="font_url" type="url" placeholder="https://fonts.googleapis.com/…"></div>
          <div><label>Launcher icon URL (optional)</label><input id="launcher_icon_url" type="url" placeholder="https://…"></div>
        </div>
        <div class="flags">
          <label><input id="auto_dark" type="checkbox" checked> Auto dark mode</label>
          <label><input id="auto_brand" type="checkbox"> Match host brand color</label>
          <label><input id="dark_mode" type="checkbox"> Force dark</label>
        </div>
        <div class="actions">
          <button class="btn primary" id="saveBtn" onclick="createOrSave()">Create bot</button>
          <button class="btn ghost" onclick="resetForm()">Reset / New</button>
          <span id="editingNote" class="hint"></span>
        </div>
        <div id="formMsg"></div>
      </div>

      <div class="card">
        <h2>Knowledge — crawl a website</h2>
        <label>Start URL</label><input id="crawl_url" type="url" placeholder="https://company.com">
        <div class="row3" style="margin-top:10px">
          <div><label>Max pages</label><input id="crawl_pages" type="text" value="15"></div>
          <div><label>Max depth</label><input id="crawl_depth" type="text" value="2"></div>
          <div style="display:flex;align-items:flex-end"><button class="btn primary" style="width:100%" onclick="runCrawl()">Crawl into collection</button></div>
        </div>
        <div class="hint">Crawls into the Collection ID above. Static/SSR sites only — JS-rendered SPAs return little text.</div>
        <div id="crawlMsg"></div>
      </div>
    </div>

    <!-- RIGHT: live preview + bots -->
    <div>
      <div class="card">
        <h2>Live preview <span class="hint" style="font-weight:400">— exact structure &amp; docked size (420×720) of the embedded widget</span></h2>
        <div class="preview-stage">
          <div class="pv" id="pv">
            <div class="pv-head">
              <div class="pv-av" id="pvAv">A</div>
              <div class="pv-hmeta">
                <div class="pv-name" id="pvName">Acme Assistant</div>
                <div class="pv-status" id="pvStatus">Typically replies instantly</div>
              </div>
              <button class="pv-ib" title="New conversation"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/></svg></button>
              <button class="pv-ib" title="Full screen"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg></button>
              <button class="pv-ib" title="Minimize"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
            </div>
            <div class="pv-body">
              <div class="pv-welcome">
                <div class="pv-wt" id="pvGreeting">Hi! How can I help you today?</div>
                <div class="pv-ws" id="pvWelcomeSub">Pick a question below, or type your own.</div>
              </div>
              <div class="pv-chips" id="pvChips"></div>
              <div class="pv-row user"><div class="pv-bubble">What are your prices?</div></div>
              <div class="pv-row bot">
                <div class="pv-ava" id="pvAva">A</div>
                <div class="pv-bubble">Our Standard plan is $29/mo and Pro is $79/mo — both include unlimited chats and email support.
                  <div class="pv-sources"><div class="h">Sources</div><a href="#">[1] pricing (p.1)</a></div>
                </div>
              </div>
            </div>
            <div class="pv-composer">
              <div class="pv-inwrap">
                <span class="pv-ta">Type your message…</span>
                <span class="pv-send"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a1 1 0 00-1.4.92V9.5c0 .5.36.93.86 1l11.14 1.5-11.14 1.5c-.5.07-.86.5-.86 1v4.98a1 1 0 001.4.92z"/></svg></span>
              </div>
              <div class="pv-pwr" id="pvPwr">Powered by Smart Routing</div>
            </div>
          </div>
          <div class="pv-launch" id="pvLaunch"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C7 3 3 6.6 3 11c0 2 .9 3.8 2.4 5.2L4.5 20l4-1.3c1.1.4 2.3.6 3.5.6 5 0 9-3.6 9-8s-4-8.3-9-8.3z"/></svg></div>
        </div>
        <div class="hint">Updates live as you edit. Mirrors the embedded widget's structure, default content and docked size. After saving, use “Live preview” on a bot for the fully interactive widget.</div>
      </div>

      <div class="card">
        <h2>Bots <button class="btn ghost sm" onclick="loadBots()" style="float:right">Refresh</button></h2>
        <div id="botList"><div class="hint">Loading…</div></div>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const API = window.location.origin;
let editingBotId = null;

function $(id){ return document.getElementById(id); }
function toast(msg){ const t=$('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }

function themeFromForm(){
  return {
    primary_color:$('primary_color').value, accent_color:$('accent_color').value,
    surface_color:$('surface_color').value, text_color:$('text_color').value,
    user_bubble_color:$('user_bubble_color').value,
    bot_bubble_color:$('bot_bubble_auto').checked ? null : $('bot_bubble_color').value,
    font_family:$('font_family').value,
    font_url:$('font_url').value||null, logo_url:$('logo_url').value||null,
    launcher_icon_url:$('launcher_icon_url').value||null, launcher_position:$('launcher_position').value,
    corner_radius_px:parseInt($('corner_radius_px').value,10),
    dark_mode:$('dark_mode').checked, auto_dark:$('auto_dark').checked, auto_brand:$('auto_brand').checked
  };
}
function parsePrompts(){
  return $('prompts').value.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{
    const i=l.indexOf('|'); if(i<0) return {label:l, prompt:l};
    return {label:l.slice(0,i).trim(), prompt:l.slice(i+1).trim()};
  });
}
function parseOrigins(){ return $('origins').value.split('\n').map(s=>s.trim()).filter(Boolean); }

function setAvatar(id, logo, initial){
  const el=$(id); if(!el) return;
  if(logo){ el.innerHTML='<img src="'+encodeURI(logo)+'" alt="">'; }
  else { el.textContent=initial; }
}
function applyPreview(){
  const t=themeFromForm(); const pv=$('pv'); const s=pv.style;
  // Derive the neutral light/dark tints exactly as the real widget's css(t) does,
  // so the preview's lines, muted text, input field and default bot bubble match.
  const fg = t.dark_mode ? '255,255,255' : '17,24,39';
  const defaultBubble = t.dark_mode ? 'rgba(255,255,255,0.07)' : 'rgba(17,24,39,0.04)';
  s.setProperty('--p-primary',t.primary_color);
  s.setProperty('--p-accent',t.accent_color||t.primary_color);
  s.setProperty('--p-surface',t.surface_color); s.setProperty('--p-text',t.text_color);
  s.setProperty('--p-user',t.user_bubble_color||t.primary_color);
  s.setProperty('--p-bubble',t.bot_bubble_color||defaultBubble);
  s.setProperty('--p-font',t.font_family);
  s.setProperty('--p-radius',t.corner_radius_px+'px');
  s.setProperty('--p-line','rgba('+fg+',0.10)');
  s.setProperty('--p-muted','rgba('+fg+',0.55)');
  s.setProperty('--p-soft','rgba('+fg+',0.04)');
  $('pvLaunch').style.setProperty('--p-primary',t.primary_color);
  const left = t.launcher_position==='bottom-left';
  pv.classList.toggle('left', left);
  $('pvLaunch').classList.toggle('left', left);
  // header + welcome + branding content
  const dn=$('display_name').value||'Assistant';
  $('pvName').textContent=dn;
  $('pvStatus').textContent=$('subtitle').value||'Online';
  $('pvGreeting').textContent=$('greeting').value||('Hi! I’m '+dn);
  const branding=$('branding').value;
  $('pvPwr').textContent=branding;
  $('pvPwr').style.display=branding?'':'none';
  // avatars (header + bot row): logo image, else the name's initial
  const logo=$('logo_url').value;
  const initial=(dn.trim().charAt(0)||'A').toUpperCase();
  setAvatar('pvAv',logo,initial); setAvatar('pvAva',logo,initial);
  // the bot-bubble color picker is only meaningful when Auto is off
  $('bot_bubble_color').disabled=$('bot_bubble_auto').checked;
  // suggested-prompt chips + the welcome subline (matches the real widget copy)
  const prompts=parsePrompts();
  $('pvWelcomeSub').textContent = prompts.length ? 'Pick a question below, or type your own.' : 'Type a message below to get started.';
  const chips=$('pvChips'); chips.innerHTML=''; chips.style.display=prompts.length?'':'none';
  prompts.slice(0,4).forEach(p=>{
    const c=document.createElement('div'); c.className='pv-chip';
    const lab=document.createElement('span'); lab.textContent=p.label; c.appendChild(lab);
    const ar=document.createElement('span'); ar.className='ar';
    ar.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
    c.appendChild(ar); chips.appendChild(c);
  });
}
document.addEventListener('input', e=>{ if(e.target.closest('.card')) applyPreview(); });
// Picking a bot-bubble color is an explicit choice to override the adaptive default.
$('bot_bubble_color').addEventListener('input', ()=>{ $('bot_bubble_auto').checked=false; });

function payloadFromForm(){
  return {
    tenant_id:$('tenant_id').value.trim(), collection_id:$('collection_id').value.trim(),
    display_name:$('display_name').value.trim(), greeting:$('greeting').value.trim(),
    subtitle:$('subtitle').value.trim(), teaser:$('teaser').value, show_teaser:$('show_teaser').checked,
    branding:$('branding').value,
    suggested_prompts:parsePrompts(), allowed_origins:parseOrigins(), theme:themeFromForm()
  };
}

async function createOrSave(){
  const body=payloadFromForm();
  const url = editingBotId ? `${API}/admin/bots/${editingBotId}` : `${API}/admin/bots`;
  const method = editingBotId ? 'PUT' : 'POST';
  const r = await fetch(url,{method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j = await r.json();
  if(!r.ok){ $('formMsg').innerHTML=`<div class="warn">${(j.detail)||'Failed'}</div>`; return; }
  $('formMsg').innerHTML='';
  toast(editingBotId?'Saved':'Bot created');
  if(j.warnings && j.warnings.length) $('formMsg').innerHTML=`<div class="warn">${j.warnings.join(' ')}</div>`;
  editingBotId=j.config.bot_id; setEditing(j.config.bot_id);
  loadBots();
}

function setEditing(id){
  editingBotId=id;
  $('formTitle').textContent = id ? 'Edit bot' : 'Create a bot';
  $('saveBtn').textContent = id ? 'Save changes' : 'Create bot';
  $('editingNote').textContent = id ? ('editing '+id) : '';
}
function resetForm(){ setEditing(null); $('formMsg').innerHTML=''; $('crawlMsg').innerHTML=''; }

function editBot(c){
  $('tenant_id').value=c.tenant_id; $('collection_id').value=c.collection_id;
  $('display_name').value=c.display_name; $('greeting').value=c.greeting;
  $('subtitle').value=c.subtitle||''; $('teaser').value=c.teaser||''; $('show_teaser').checked=c.show_teaser!==false;
  $('branding').value=c.branding!=null?c.branding:'';
  $('prompts').value=(c.suggested_prompts||[]).map(p=>`${p.label} | ${p.prompt}`).join('\n');
  $('origins').value=(c.allowed_origins||[]).join('\n');
  const t=c.theme||{};
  ['primary_color','accent_color','surface_color','text_color','user_bubble_color'].forEach(k=>{ if(t[k]) $(k).value=t[k]; });
  if(t.bot_bubble_color){ $('bot_bubble_color').value=t.bot_bubble_color; $('bot_bubble_auto').checked=false; }
  else { $('bot_bubble_auto').checked=true; }
  $('font_family').value=t.font_family||''; $('font_url').value=t.font_url||''; $('logo_url').value=t.logo_url||'';
  $('launcher_icon_url').value=t.launcher_icon_url||'';
  $('launcher_position').value=t.launcher_position||'bottom-right';
  $('corner_radius_px').value=t.corner_radius_px!=null?t.corner_radius_px:18;
  $('dark_mode').checked=!!t.dark_mode; $('auto_dark').checked=t.auto_dark!==false; $('auto_brand').checked=!!t.auto_brand;
  setEditing(c.bot_id); applyPreview(); window.scrollTo({top:0,behavior:'smooth'});
}

async function deleteBot(id){
  if(!confirm('Delete '+id+'?')) return;
  await fetch(`${API}/admin/bots/${id}`,{method:'DELETE'});
  if(editingBotId===id) resetForm();
  toast('Deleted'); loadBots();
}

async function loadBots(){
  const r=await fetch(`${API}/admin/bots`); const list=await r.json();
  const el=$('botList');
  if(!list.length){ el.innerHTML='<div class="hint">No bots yet — create one above.</div>'; return; }
  el.innerHTML='';
  list.forEach(v=>{
    const c=v.config;
    const div=document.createElement('div'); div.className='bot';
    div.innerHTML=`<div class="top"><div><div class="name">${c.display_name}</div>
      <div class="meta">${c.bot_id} · tenant ${c.tenant_id} · ${c.enabled?'enabled':'disabled'}</div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn ghost sm" data-act="edit">Edit</button>
        <a class="btn ghost sm" target="_blank" href="${API}/widget/preview?bot_id=${c.bot_id}">Live preview</a>
        <button class="btn ghost sm" data-act="copy">Copy embed</button>
        <button class="btn danger sm" data-act="del">Delete</button>
      </div></div>
      <div class="snippet">${v.embed_snippet.replace(/</g,'&lt;')}</div>`;
    div.querySelector('[data-act=edit]').onclick=()=>editBot(c);
    div.querySelector('[data-act=del]').onclick=()=>deleteBot(c.bot_id);
    div.querySelector('[data-act=copy]').onclick=()=>{ navigator.clipboard.writeText(v.embed_snippet); toast('Embed snippet copied'); };
    el.appendChild(div);
  });
}

async function runCrawl(){
  const url=$('crawl_url').value.trim(); if(!url){ toast('Enter a URL'); return; }
  const body={ start_url:url, tenant_id:$('tenant_id').value.trim(), domain:'general',
    max_pages:parseInt($('crawl_pages').value,10)||15, max_depth:parseInt($('crawl_depth').value,10)||2 };
  $('crawlMsg').innerHTML='<div class="hint">Crawling… this can take a moment.</div>';
  const r=await fetch(`${API}/grounded-documents/collections/${$('collection_id').value.trim()}/crawl`,
    {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j=await r.json();
  if(!r.ok){ $('crawlMsg').innerHTML=`<div class="warn">${j.detail||'Crawl failed'}</div>`; return; }
  let html=`<div class="ok">Crawled ${j.pages_crawled} page(s); collection now has ${j.collection.document_count} document(s).</div>`;
  if(j.warnings && j.warnings.length) html+=`<div class="warn">${j.warnings.join(' ')}</div>`;
  $('crawlMsg').innerHTML=html; toast('Crawl complete');
}

// ---- AutoPilot: paste a URL -> fill the form, theme the preview, show the site ----
function setMode(m){
  const auto = m !== 'manual';
  $('apCard').classList.toggle('hidden', !auto);
  $('modeAuto').classList.toggle('on', auto);
  $('modeManual').classList.toggle('on', !auto);
}

function setStageBackground(url){
  const st=document.querySelector('.preview-stage');
  if(url){ st.style.backgroundImage=`url("${url}")`; st.style.backgroundSize='100% auto';
    st.style.backgroundPosition='top center'; st.style.backgroundRepeat='no-repeat'; }
  else { st.style.backgroundImage=''; }
}

function fillFromDraft(d){
  const t=d.theme||{};
  if(d.suggested_tenant_id) $('tenant_id').value=d.suggested_tenant_id;
  if(d.suggested_collection_id) $('collection_id').value=d.suggested_collection_id;
  if(d.display_name) $('display_name').value=d.display_name;
  if(d.greeting) $('greeting').value=d.greeting;
  if(d.subtitle) $('subtitle').value=d.subtitle;
  if(Array.isArray(d.suggested_prompts) && d.suggested_prompts.length)
    $('prompts').value=d.suggested_prompts.map(p=>`${p.label} | ${p.prompt}`).join('\n');
  if(Array.isArray(d.allowed_origins) && d.allowed_origins.length)
    $('origins').value=d.allowed_origins.join('\n');
  ['primary_color','accent_color','surface_color','text_color','user_bubble_color'].forEach(k=>{ if(t[k]) $(k).value=t[k]; });
  if(t.bot_bubble_color){ $('bot_bubble_color').value=t.bot_bubble_color; $('bot_bubble_auto').checked=false; }
  else { $('bot_bubble_auto').checked=true; }
  if(t.corner_radius_px!=null) $('corner_radius_px').value=t.corner_radius_px;
  if(t.logo_url) $('logo_url').value=t.logo_url;
  $('dark_mode').checked=!!t.dark_mode;
  applyPreview();
}

async function runAutopilot(){
  const url=$('ap_url').value.trim();
  if(!url){ toast('Paste a website URL'); return; }
  const btn=$('apRun'); const orig=btn.textContent; btn.disabled=true;
  btn.innerHTML='<span class="spin"></span>Analyzing…';
  $('apMsg').innerHTML='<div class="hint">Rendering the site, extracting brand colors, and writing the copy… this can take ~10–30s.</div>';
  try{
    const r=await fetch(`${API}/admin/autopilot/analyze`,{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({url})});
    const j=await r.json();
    if(!r.ok){ $('apMsg').innerHTML=`<div class="warn">${(j.detail)||'AutoPilot failed'}</div>`; return; }
    fillFromDraft(j);
    if(j.screenshot_url) setStageBackground(`${API}${j.screenshot_url}`);
    let html=`<div class="ok">Bot drafted from <b>${j.origin||url}</b>`;
    if(j.authored_by_model) html+=` · copy by <b>${j.authored_by_model}</b>`;
    html+='. Review the fields, then click <b>Create bot</b>.</div>';
    if(Array.isArray(j.palette) && j.palette.length){
      html+='<div style="display:flex;gap:5px;margin-top:8px;align-items:center;flex-wrap:wrap"><span class="hint" style="margin:0">Palette:</span>';
      j.palette.forEach(c=>{ html+=`<span class="sw" title="${c}" style="background:${c}"></span>`; });
      html+='<span class="ap-clearbg" style="margin-left:auto" onclick="setStageBackground(null)">remove background</span></div>';
    }
    if(Array.isArray(j.warnings)) j.warnings.forEach(w=>{ html+=`<div class="warn">${w}</div>`; });
    $('apMsg').innerHTML=html; toast('AutoPilot complete');
    if($('ap_crawl').checked){ $('crawl_url').value=j.final_url||url; runCrawl(); }
  }catch(e){ $('apMsg').innerHTML=`<div class="warn">AutoPilot error: ${e.message}</div>`; }
  finally{ btn.disabled=false; btn.textContent=orig; }
}

setMode('auto'); applyPreview(); loadBots();
</script>
</body>
</html>
"""


@router.get("/console", response_class=HTMLResponse, summary="Visual widget admin console")
async def admin_console() -> HTMLResponse:
    return HTMLResponse(content=ADMIN_CONSOLE_HTML)
