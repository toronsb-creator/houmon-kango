from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
import sqlite3
from datetime import date, datetime, timedelta
import calendar
import html
import os
from urllib.parse import quote

app = FastAPI()


def make_tel_link(phone: str, label: str = None) -> str:
    """電話番号を安全な tel: リンクにする。"""
    phone = phone or ""
    tel_number = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not tel_number:
        return html.escape(label if label is not None else phone)
    shown = html.escape(label if label is not None else phone)
    return f'<a href="tel:{html.escape(tel_number, quote=True)}">{shown}</a>'
# =========================================================
# PWA（iPhone・Androidのホーム画面に追加）
# =========================================================

@app.get("/manifest.webmanifest")
def pwa_manifest():
    return JSONResponse({
        "name": "訪問看護システム",
        "short_name": "訪問看護",
        "description": "訪問予定・休暇申請管理",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f7fa",
        "theme_color": "#1677c8",
        "icons": [{"src": "/pwa-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]
    })

@app.get("/pwa-icon.svg")
def pwa_icon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="90" fill="#1677c8"/><path d="M80 245 256 95 432 245v175H305V300h-98v120H80z" fill="white"/><path d="M235 175h42v105h-42zM204 206h104v42H204z" fill="#1677c8"/></svg>'
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/service-worker.js")
def service_worker():
    # 個人情報を含む画面はキャッシュしない。オフライン時は案内だけ表示。
    js = """const CACHE_NAME = 'houmon-kango-static-v1';
self.addEventListener('install', (event) => { self.skipWaiting(); });
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => key !== CACHE_NAME ? caches.delete(key) : Promise.resolve()));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(fetch(req).catch(() => {
    if (req.mode === 'navigate') return new Response(
      '<!doctype html><html lang=\\"ja\\"><meta charset=\\"utf-8\\"><meta name=\\"viewport\\" content=\\"width=device-width,initial-scale=1\\"><title>オフライン</title><body style=\\"font-family:sans-serif;padding:24px\\"><h2>インターネットに接続できません</h2><p>通信を復旧して、もう一度お試しください。</p></body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } }
    );
    return new Response('', { status: 503, statusText: 'Offline' });
  }));
});"""
    return Response(content=js, media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

@app.middleware("http")
async def add_pwa_to_html(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    html_text = body.decode("utf-8", errors="replace")
    head_addition = (
        '<link rel="manifest" href="/manifest.webmanifest">'
        '<meta name="theme-color" content="#1677c8">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
        '<meta name="apple-mobile-web-app-title" content="訪問看護">'
        '<link rel="apple-touch-icon" href="/pwa-icon.svg">'
    )
    script_addition = (
        '<script>if ("serviceWorker" in navigator) {'
        'window.addEventListener("load", function(){navigator.serviceWorker.register("/service-worker.js").catch(function(e){console.error("PWA service worker:",e);});});'
        '}</script>'
    )
    if "</head>" in html_text:
        html_text = html_text.replace("</head>", head_addition + "</head>", 1)
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", script_addition + "</body>", 1)
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type", "content-encoding")}
    return HTMLResponse(content=html_text, status_code=response.status_code, headers=headers)
