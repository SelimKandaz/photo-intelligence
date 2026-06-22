from __future__ import annotations

from app.config import Settings


def render_index(settings: Settings) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Photo Intelligence</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #5c6670;
      --line: #d8dee4;
      --accent: #176b57;
      --accent-2: #914f1e;
      --danger: #a53232;
      --focus: #1f6feb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 20px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 5;
    }}
    h1 {{
      font-size: 20px;
      margin: 0;
      font-weight: 650;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(300px, 380px) 1fr;
      gap: 16px;
      padding: 16px;
      max-width: 1500px;
      margin: 0 auto;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 15px;
    }}
    label {{
      display: block;
      margin: 10px 0 5px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 600;
    }}
    input, select, textarea {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      background: #fff;
    }}
    textarea {{ min-height: 72px; resize: vertical; }}
    button {{
      min-height: 36px;
      border: 1px solid #0f5c49;
      border-radius: 6px;
      padding: 7px 12px;
      font: inherit;
      font-weight: 650;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
    }}
    button.secondary {{
      color: var(--ink);
      border-color: var(--line);
      background: #fff;
    }}
    button.warning {{
      background: var(--accent-2);
      border-color: var(--accent-2);
    }}
    .row {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .row > * {{ flex: 1; }}
    .stack {{ display: grid; gap: 12px; }}
    .muted {{ color: var(--muted); font-size: 12px; }}
    .status {{
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 76px;
      max-height: 150px;
      overflow: auto;
      padding: 8px;
      white-space: pre-wrap;
      font-family: Consolas, monospace;
      font-size: 12px;
      background: #fbfcfd;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 8px 6px;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      background: #fbfcfd;
      position: sticky;
      top: 0;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: calc(100vh - 275px);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      margin: 0 4px 4px 0;
      font-size: 12px;
      background: #fff;
    }}
    .pill.review {{ border-color: #d89a9a; color: var(--danger); }}
    .split {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 16px;
      align-items: start;
    }}
    .detail {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 200px;
      background: #fff;
      overflow: auto;
    }}
    .thumb {{
      width: 64px;
      height: 64px;
      object-fit: cover;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #edf0f2;
    }}
    .path {{
      max-width: 460px;
      word-break: break-word;
      font-family: Consolas, monospace;
      font-size: 12px;
    }}
    @media (max-width: 1000px) {{
      main, .split {{ grid-template-columns: 1fr; }}
      header {{ align-items: flex-start; gap: 8px; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Photo Intelligence</h1>
    <div class="muted">DB: {settings.database_url} | Import: {settings.import_folder}</div>
  </header>
  <main>
    <section class="stack">
      <div>
        <h2>Import</h2>
        <label for="importPath">Folder</label>
        <input id="importPath" value="{settings.import_folder}">
        <div class="row" style="margin-top:8px;">
          <select id="backend">
            <option value="audit">audit</option>
            <option value="barcode">barcode</option>
            <option value="tesseract">tesseract</option>
            <option value="auto">auto</option>
          </select>
          <button onclick="startImport()">Import</button>
        </div>
      </div>
      <div>
        <h2>Search</h2>
        <input id="query" placeholder="PO 11234 SN MT2331FT15720">
        <div class="row" style="margin-top:8px;">
          <select id="searchMode">
            <option value="fast">Fast Search</option>
            <option value="deep">Deep Search</option>
          </select>
          <button onclick="runSearch()">Search</button>
          <button class="secondary" onclick="loadPhotos()">Photos</button>
          <button class="secondary" onclick="exportSerials()">Export CSV</button>
        </div>
      </div>
      <div>
        <h2>Jobs</h2>
        <div id="jobs" class="status"></div>
      </div>
      <div>
        <h2>Review</h2>
        <div id="review" class="status"></div>
      </div>
      <div>
        <h2>Failed</h2>
        <div id="failed" class="status"></div>
      </div>
    </section>
    <section class="split">
      <div>
        <div class="row" style="margin-bottom:10px;">
          <h2 id="resultsTitle">Photos</h2>
          <button class="secondary" onclick="loadReview()">Refresh Review</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Image</th><th>Path</th><th>Status</th><th>Evidence</th><th>Why</th></tr>
            </thead>
            <tbody id="results"></tbody>
          </table>
        </div>
      </div>
      <div class="detail" id="detail"></div>
    </section>
  </main>
  <script>
    let activeJob = null;
    let currentQueryId = null;
    let currentQueryFingerprint = '';

    async function api(path, options = {{}}) {{
      const response = await fetch(path, {{
        headers: {{ 'Content-Type': 'application/json' }},
        ...options
      }});
      if (!response.ok) throw new Error(await response.text());
      return await response.json();
    }}

    function entityPills(entities, context = []) {{
      const parts = [];
      for (const e of entities || []) {{
        const cls = e.metadata_json && e.metadata_json.includes('review') ? 'pill review' : 'pill';
        parts.push(`<span class="${{cls}}">${{e.entity_type}}: ${{e.value}}</span>`);
      }}
      for (const c of context || []) {{
        parts.push(`<span class="pill">context ${{c.entity_type}}: ${{c.value}}</span>`);
      }}
      return parts.join(' ');
    }}

    function renderRows(items, isSearch = false) {{
      const tbody = document.getElementById('results');
      tbody.innerHTML = '';
      for (const item of items) {{
        const photoId = item.photo_id || item.id;
        const row = document.createElement('tr');
        const thumb = item.thumbnail_path ? `<img class="thumb" src="/media/thumb/${{photoId}}" alt="">` : '';
        row.innerHTML = `
          <td>${{thumb}}</td>
          <td><button class="secondary" onclick="openResult('${{photoId}}', ${{item.rank || 0}}, '${{item.query_id || ''}}', '${{item.query_fingerprint || ''}}')">Open</button><div class="path">${{item.path}}</div></td>
          <td>${{item.status || ''}}</td>
          <td>${{entityPills(item.entities, item.context)}}</td>
          <td>${{isSearch ? ((item.match_sources || []).join(', ') + '<br>' + (item.reasons || []).join('<br>')) : ''}}</td>
        `;
        tbody.appendChild(row);
      }}
    }}

    async function startImport() {{
      const payload = {{
        source_path: document.getElementById('importPath').value,
        backend: document.getElementById('backend').value
      }};
      const data = await api('/api/import', {{ method: 'POST', body: JSON.stringify(payload) }});
      activeJob = data.job_id;
      pollJobs();
    }}

    async function pollJobs() {{
      const jobs = await api('/api/jobs');
      document.getElementById('jobs').textContent = jobs.map(j => {{
        const lines = (j.progress || []).slice(-5).join('\\n');
        return `${{j.id}} ${{j.status}}\\n${{lines}}`;
      }}).join('\\n\\n');
      if (jobs.some(j => j.status === 'running' || j.status === 'queued')) {{
        setTimeout(pollJobs, 1600);
      }} else {{
        loadPhotos();
        loadReview();
        loadFailed();
      }}
    }}

    async function loadPhotos() {{
      document.getElementById('resultsTitle').textContent = 'Photos';
      const data = await api('/api/photos?limit=100');
      renderRows(data.items || []);
    }}

    async function runSearch() {{
      const q = encodeURIComponent(document.getElementById('query').value);
      const mode = encodeURIComponent(document.getElementById('searchMode').value);
      document.getElementById('resultsTitle').textContent = 'Search';
      const data = await api('/api/search?q=' + q + '&mode=' + mode);
      currentQueryId = data.query_id || null;
      currentQueryFingerprint = data.query_fingerprint || '';
      renderRows(data.results || [], true);
    }}

    async function openResult(photoId, rank = 0, queryId = '', queryFingerprint = '') {{
      if (queryId) {{
        await api('/api/search-click', {{
          method: 'POST',
          body: JSON.stringify({{
            photo_id: photoId,
            query_id: queryId,
            query_fingerprint: queryFingerprint,
            rank: rank,
            action: 'open'
          }})
        }});
      }}
      loadDetail(photoId, queryId || currentQueryId || '', queryFingerprint || currentQueryFingerprint || '', rank);
    }}

    async function loadDetail(photoId, queryId = '', queryFingerprint = '', rank = 0) {{
      const item = await api('/api/photos/' + photoId);
      const raw = (item.raw_ocr || []).map(r => r.text).join('\\n---\\n');
      const previous = item.navigation && item.navigation.previous ? `<button class="secondary" onclick="loadDetail('${{item.navigation.previous.id}}', '${{queryId}}', '${{queryFingerprint}}', ${{rank}})">Previous</button>` : '';
      const next = item.navigation && item.navigation.next ? `<button class="secondary" onclick="loadDetail('${{item.navigation.next.id}}', '${{queryId}}', '${{queryFingerprint}}', ${{rank}})">Next</button>` : '';
      document.getElementById('detail').innerHTML = `
        <h2>Photo Detail</h2>
        <div class="path">${{item.path}}</div>
        <div class="row" style="margin:10px 0;">
          <a class="secondary" href="/media/photo/${{photoId}}" target="_blank"><button class="secondary">Full Photo</button></a>
          ${{previous}}
          ${{next}}
        </div>
        <div style="margin:10px 0;">${{entityPills(item.entities, item.context)}}</div>
        <label>Correction</label>
        <div class="row">
          <select id="corrType">
            <option value="serial_number">serial_number</option>
            <option value="purchase_order">purchase_order</option>
            <option value="sales_order">sales_order</option>
            <option value="part_number">part_number</option>
            <option value="model_number">model_number</option>
          </select>
          <input id="corrValue" placeholder="Correct value">
          <button class="warning" onclick="saveCorrection('${{photoId}}')">Save</button>
        </div>
        <label>Feedback</label>
        <div class="row">
          <button class="secondary" onclick="sendFeedback('${{photoId}}','correct','${{queryId}}','${{queryFingerprint}}', ${{rank}})">Correct</button>
          <button class="secondary" onclick="sendFeedback('${{photoId}}','wrong','${{queryId}}','${{queryFingerprint}}', ${{rank}})">Wrong</button>
          <button class="secondary" onclick="sendFeedback('${{photoId}}','needs_review','${{queryId}}','${{queryFingerprint}}', ${{rank}})">Review</button>
        </div>
        <label>Raw OCR</label>
        <textarea readonly>${{raw}}</textarea>
      `;
    }}

    async function saveCorrection(photoId) {{
      await api('/api/photos/' + photoId + '/corrections', {{
        method: 'POST',
        body: JSON.stringify({{
          entity_type: document.getElementById('corrType').value,
          corrected_value: document.getElementById('corrValue').value
        }})
      }});
      loadDetail(photoId);
    }}

    async function sendFeedback(photoId, rating, queryId = '', queryFingerprint = '', rank = 0) {{
      await api('/api/photos/' + photoId + '/feedback', {{
        method: 'POST',
        body: JSON.stringify({{
          rating,
          query_id: queryId || currentQueryId,
          query_fingerprint: queryFingerprint || currentQueryFingerprint,
          rank
        }})
      }});
      loadDetail(photoId, queryId, queryFingerprint, rank);
    }}

    async function loadReview() {{
      const data = await api('/api/review-queue');
      document.getElementById('review').innerHTML = (data.items || []).map(i => `
        <div style="border-bottom:1px solid var(--line); padding:6px 0;">
          <div>${{i.priority}} ${{i.reason}}</div>
          <div class="path">${{i.path}}</div>
          <div class="row" style="margin-top:4px;">
            <button class="secondary" onclick="resolveReview('${{i.id}}','resolved')">Resolved</button>
            <button class="secondary" onclick="resolveReview('${{i.id}}','confirmed_mismatch')">Confirm</button>
            <button class="secondary" onclick="resolveReview('${{i.id}}','false_positive')">False</button>
          </div>
        </div>
      `).join('');
    }}

    async function resolveReview(reviewId, action) {{
      await api('/api/review-queue/' + reviewId + '/resolve', {{
        method: 'POST',
        body: JSON.stringify({{ action }})
      }});
      loadReview();
    }}

    async function loadFailed() {{
      const data = await api('/api/failed-files');
      document.getElementById('failed').innerHTML = (data.items || []).map(i => `
        <div style="border-bottom:1px solid var(--line); padding:6px 0;">
          <div class="path">${{i.path}}</div>
          <div>${{i.error}}</div>
          <button class="secondary" onclick="retryFailed('${{i.id}}')">Retry</button>
        </div>
      `).join('');
    }}

    async function retryFailed(failedId) {{
      const data = await api('/api/failed-files/' + failedId + '/retry', {{ method: 'POST' }});
      activeJob = data.job_id;
      pollJobs();
    }}

    function exportSerials() {{
      window.location = '/api/export/serial-rows';
    }}

    loadPhotos();
    loadReview();
    loadFailed();
    pollJobs();
  </script>
</body>
</html>"""
