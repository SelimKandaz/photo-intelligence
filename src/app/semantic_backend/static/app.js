const statusGrid = document.getElementById("statusGrid");
const lastRunBox = document.getElementById("lastRunBox");
const ingestSummary = document.getElementById("ingestSummary");
const failedFilesBody = document.getElementById("failedFilesBody");
const answerBox = document.getElementById("answerBox");
const sourcesBody = document.getElementById("sourcesBody");
const auditSummaryBox = document.getElementById("auditSummaryBox");
const auditBody = document.getElementById("auditBody");

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || JSON.stringify(payload));
  }
  return payload;
}

function renderKeyValueCards(rows, target) {
  target.innerHTML = rows
    .map(([label, value]) => `<article class="status-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderFailedFiles(items) {
  if (!items || !items.length) {
    failedFilesBody.innerHTML = `<tr><td colspan="3" class="muted">No failed or unsupported files.</td></tr>`;
    return;
  }
  failedFilesBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.file_name || ""}</td>
          <td>${item.relative_path || ""}</td>
          <td>${item.error_message || item.status || ""}</td>
        </tr>
      `
    )
    .join("");
}

function renderSources(items) {
  if (!items || !items.length) {
    sourcesBody.innerHTML = `<tr><td colspan="6" class="muted">No sources yet.</td></tr>`;
    return;
  }
  sourcesBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.file_name}</td>
          <td>${item.source_category || ""}</td>
          <td>${item.chunk_id}</td>
          <td>${item.score}</td>
          <td>${item.boost_reason || ""}</td>
          <td>${item.preview || ""}</td>
        </tr>
      `
    )
    .join("");
}

function renderAuditItems(items) {
  if (!items || !items.length) {
    auditBody.innerHTML = `<tr><td colspan="6" class="muted">No findings.</td></tr>`;
    return;
  }
  auditBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.severity || ""}</td>
          <td>${item.issue_type || ""}</td>
          <td>${item.summary || ""}</td>
          <td>${item.source_file || ""}</td>
          <td>${item.evidence_snippet || ""}</td>
          <td>${item.recommended_action || ""}</td>
        </tr>
      `
    )
    .join("");
}

async function refreshStatus() {
  try {
    const payload = await getJson("/stats");
    renderKeyValueCards(
      [
        ["Ollama reachable", payload.ollama.reachable ? "Yes" : "No"],
        ["Qdrant reachable", payload.qdrant.reachable ? "Yes" : "No"],
        ["LLM model", payload.settings.llm_model],
        ["Embedding model", payload.settings.embedding_model],
        ["Indexed files", String(payload.indexed_files)],
        ["Indexed chunks", String(payload.indexed_chunks)],
        ["Failed files", String(payload.failed_files.length)],
        ["Unsupported files", String(payload.unsupported_files)],
      ],
      statusGrid
    );
    const lastRun = payload.last_ingestion_run;
    if (!lastRun) {
      lastRunBox.textContent = "No ingestion run yet.";
    } else {
      lastRunBox.textContent =
        `Last run: ${lastRun.started_at} | status: ${lastRun.status} | ` +
        `imported: ${lastRun.imported_count} | updated: ${lastRun.updated_count} | ` +
        `skipped: ${lastRun.skipped_count} | failed: ${lastRun.failed_count} | ` +
        `unsupported: ${lastRun.unsupported_count} | chunks: ${lastRun.chunks_created}`;
    }
    renderFailedFiles(payload.failed_files);
  } catch (error) {
    statusGrid.innerHTML = `<article class="status-card error"><span>Status error</span><strong>${error.message}</strong></article>`;
    lastRunBox.textContent = error.message;
  }
}

async function runIngest(force) {
  ingestSummary.innerHTML = `<article class="status-card"><span>Ingestion</span><strong>Running...</strong></article>`;
  try {
    const payload = await getJson(`/ingest?force=${force ? "true" : "false"}`, {
      method: "POST",
    });
    renderKeyValueCards(
      [
        ["Imported", String(payload.imported)],
        ["Updated", String(payload.updated)],
        ["Skipped", String(payload.skipped)],
        ["Failed", String(payload.failed)],
        ["Unsupported", String(payload.unsupported)],
        ["Chunks created", String(payload.chunks_created)],
      ],
      ingestSummary
    );
    renderFailedFiles(payload.failed_files);
    await refreshStatus();
  } catch (error) {
    ingestSummary.innerHTML = `<article class="status-card error"><span>Ingestion error</span><strong>${error.message}</strong></article>`;
  }
}

async function runAsk(event) {
  event.preventDefault();
  const question = document.getElementById("questionInput").value.trim();
  if (!question) {
    answerBox.textContent = "Please enter a question.";
    return;
  }
  answerBox.textContent = "Thinking...";
  renderSources([]);
  try {
    const payload = await getJson("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const warnings = payload.warnings?.length ? `\n\nWarnings: ${payload.warnings.join(" | ")}` : "";
    answerBox.textContent = `${payload.answer}${warnings}`;
    renderSources(payload.sources);
  } catch (error) {
    answerBox.textContent = error.message;
    renderSources([]);
  }
}

async function runAudit(endpoint) {
  auditSummaryBox.textContent = "Running audit...";
  try {
    const payload = await getJson(endpoint);
    const items = payload.items || [];
    auditSummaryBox.textContent = items.length ? `Returned ${items.length} finding(s).` : "No findings.";
    renderAuditItems(items);
  } catch (error) {
    auditSummaryBox.textContent = error.message;
    renderAuditItems([]);
  }
}

async function runPoSoSummary(event) {
  event.preventDefault();
  const query = document.getElementById("poSoQuery").value.trim();
  if (!query) {
    auditSummaryBox.textContent = "Enter a PO or SO query first.";
    return;
  }
  try {
    const payload = await getJson(`/audit/po-so-summary?query=${encodeURIComponent(query)}`);
    auditSummaryBox.textContent = payload.summary;
    renderAuditItems(
      (payload.conflicts_found || []).map((item) => ({
        severity: item.barcode_serial && item.printed_serial && item.barcode_serial !== item.printed_serial ? "high" : "medium",
        issue_type: "po_so_evidence",
        summary: item.summary,
        source_file: item.source_file,
        evidence_snippet: `${item.printed_serial || ""} ${item.barcode_serial || ""}`.trim() || "See summary panel.",
        recommended_action: "Review the related sources and confirm the current PO/SO state.",
      }))
    );
    if (!payload.conflicts_found.length) {
      auditBody.innerHTML = `
        <tr>
          <td>info</td>
          <td>po_so_summary</td>
          <td>${payload.summary}</td>
          <td>${(payload.related_source_files || []).join(", ")}</td>
          <td>${(payload.evidence_snippets || []).join(" | ")}</td>
          <td>Use the evidence to answer the PO/SO question or narrow the query further.</td>
        </tr>
      `;
    }
  } catch (error) {
    auditSummaryBox.textContent = error.message;
    renderAuditItems([]);
  }
}

document.getElementById("refreshStatus").addEventListener("click", refreshStatus);
document.getElementById("ingestChanged").addEventListener("click", () => runIngest(false));
document.getElementById("forceReindex").addEventListener("click", () => runIngest(true));
document.getElementById("askForm").addEventListener("submit", runAsk);
document.getElementById("poSoForm").addEventListener("submit", runPoSoSummary);

document.querySelectorAll("[data-audit]").forEach((button) => {
  button.addEventListener("click", () => runAudit(button.dataset.audit));
});

refreshStatus();
