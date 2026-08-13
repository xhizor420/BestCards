"use strict";

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const folderInput = document.getElementById("folderInput");
const pickFilesBtn = document.getElementById("pickFilesBtn");
const pickFolderBtn = document.getElementById("pickFolderBtn");

const progressSection = document.getElementById("progressSection");
const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");

const summarySection = document.getElementById("summarySection");
const successCountEl = document.getElementById("successCount");
const failCountEl = document.getElementById("failCount");
const failuresList = document.getElementById("failuresList");
const toggleFailuresBtn = document.getElementById("toggleFailuresBtn");

const exportSection = document.getElementById("exportSection");
const formatSelect = document.getElementById("formatSelect");
const sortSelect = document.getElementById("sortSelect");
const tokenizerSelect = document.getElementById("tokenizerSelect");
const fullCheckbox = document.getElementById("fullCheckbox");
const maxCharsLabel = document.getElementById("maxCharsLabel");
const maxCharsInput = document.getElementById("maxCharsInput");
const fieldCheckboxes = Array.from(document.querySelectorAll(".field-checkbox"));
const totalTokensEl = document.getElementById("totalTokens");
const tokenMethodEl = document.getElementById("tokenMethod");
const cardGrid = document.getElementById("cardGrid");
const exportBtn = document.getElementById("exportBtn");
const exportResult = document.getElementById("exportResult");
const resetBtn = document.getElementById("resetBtn");

// Each entry: { card: {...extracted fields...}, file: File, thumbUrl: string }
let entries = [];
let extractionFailures = [];
let isProcessing = false;
let estimateRequestId = 0;

const CONCURRENCY = 6;
const PNG_RE = /\.png$/i;

function readEntryFile(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

function readAllDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    let all = [];
    (function readBatch() {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(all);
        } else {
          all = all.concat(batch);
          readBatch();
        }
      }, reject);
    })();
  });
}

async function traverseEntry(entry) {
  if (!entry) return [];
  if (entry.isFile) {
    return [await readEntryFile(entry)];
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const dirEntries = await readAllDirectoryEntries(reader);
    const nested = await Promise.all(dirEntries.map(traverseEntry));
    return nested.flat();
  }
  return [];
}

async function filesFromDataTransfer(dataTransfer) {
  const items = dataTransfer.items;
  if (items && items.length && items[0].webkitGetAsEntry) {
    const fsEntries = Array.from(items)
      .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
      .filter(Boolean);
    const nested = await Promise.all(fsEntries.map(traverseEntry));
    return nested.flat();
  }
  return Array.from(dataTransfer.files || []);
}

function setProgressVisible(visible) {
  progressSection.classList.toggle("hidden", !visible);
}

function updateProgress(done, total) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  progressBar.style.width = `${pct}%`;
  progressText.textContent = `Processing ${done} / ${total} PNGs…`;
}

async function extractOne(file) {
  const res = await fetch(`/api/extract?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    body: file,
  });
  if (!res.ok) {
    throw new Error(`server error ${res.status}`);
  }
  return res.json();
}

async function processFiles(files) {
  const total = files.length;
  let done = 0;
  const successes = [];
  const failures = [];
  updateProgress(0, total);

  let nextIndex = 0;
  async function worker() {
    while (nextIndex < files.length) {
      const i = nextIndex++;
      const file = files[i];
      try {
        const data = await extractOne(file);
        if (data.ok) {
          successes.push({ card: data.card, file, thumbUrl: URL.createObjectURL(file) });
        } else {
          failures.push({ name: file.name, error: data.error || "unknown error" });
        }
      } catch (err) {
        failures.push({ name: file.name, error: String(err) });
      }
      done++;
      updateProgress(done, total);
    }
  }

  const workerCount = Math.min(CONCURRENCY, Math.max(1, files.length));
  await Promise.all(Array.from({ length: workerCount }, worker));
  return { successes, failures };
}

function renderSummary() {
  successCountEl.textContent = String(entries.length);
  failCountEl.textContent = String(extractionFailures.length);
  summarySection.classList.toggle("hidden", entries.length === 0 && extractionFailures.length === 0);
  exportSection.classList.toggle("hidden", entries.length === 0);

  failuresList.innerHTML = "";
  for (const f of extractionFailures) {
    const li = document.createElement("li");
    li.textContent = `${f.name}: ${f.error}`;
    failuresList.appendChild(li);
  }
}

function renderCardGrid() {
  cardGrid.innerHTML = "";
  entries.forEach((entry, index) => {
    const tile = document.createElement("div");
    tile.className = "card-tile";

    const img = document.createElement("img");
    img.src = entry.thumbUrl;
    img.loading = "lazy";
    img.alt = entry.card.name || "card";
    tile.appendChild(img);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "card-tile-remove";
    removeBtn.title = "Remove from export";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => removeEntry(index));
    tile.appendChild(removeBtn);

    const info = document.createElement("div");
    info.className = "card-tile-info";

    const name = document.createElement("div");
    name.className = "card-tile-name";
    name.textContent = entry.card.name || entry.card.nickname || "(unnamed)";
    name.title = name.textContent;
    info.appendChild(name);

    const tokens = document.createElement("div");
    tokens.className = "card-tile-tokens";
    tokens.dataset.role = "tokens";
    tokens.textContent = "…";
    info.appendChild(tokens);

    tile.appendChild(info);
    cardGrid.appendChild(tile);
  });
}

function removeEntry(index) {
  const [removed] = entries.splice(index, 1);
  if (removed) URL.revokeObjectURL(removed.thumbUrl);
  renderSummary();
  renderCardGrid();
  refreshEstimate();
}

function currentExportOptions() {
  return {
    format: formatSelect.value,
    sort: sortSelect.value,
    full: fullCheckbox.checked,
    max_chars: parseInt(maxCharsInput.value, 10) || 600,
    fields: fieldCheckboxes.filter((cb) => cb.checked).map((cb) => cb.value),
    tokenizer: tokenizerSelect.value,
  };
}

function shortMethodLabel(method) {
  if (!method) return "";
  // A real tokenizer's label never starts with "heuristic"; a fallback
  // (package missing, download blocked, unreachable network) always does,
  // regardless of which one was requested - see cardpack/stats.py.
  return method.startsWith("heuristic") ? "(estimate - see title for why)" : "(exact)";
}

async function refreshEstimate() {
  if (!entries.length) {
    totalTokensEl.textContent = "0";
    tokenMethodEl.textContent = "";
    return;
  }
  const requestId = ++estimateRequestId;
  try {
    const res = await fetch("/api/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cards: entries.map((e) => e.card), ...currentExportOptions() }),
    });
    const data = await res.json();
    if (requestId !== estimateRequestId) return; // a newer request superseded this one
    if (!res.ok) throw new Error(data.error || `server error ${res.status}`);

    totalTokensEl.textContent = data.total_tokens.toLocaleString();
    tokenMethodEl.textContent = shortMethodLabel(data.method);
    tokenMethodEl.title = data.method;
    const tiles = cardGrid.querySelectorAll(".card-tile");
    data.cards.forEach((c, i) => {
      const badge = tiles[i] && tiles[i].querySelector('[data-role="tokens"]');
      if (badge) badge.textContent = `${c.tokens.toLocaleString()} tok`;
    });
  } catch (err) {
    if (requestId === estimateRequestId) {
      totalTokensEl.textContent = "?";
      tokenMethodEl.textContent = "";
    }
  }
}

function debounce(fn, delayMs) {
  let handle;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), delayMs);
  };
}
const debouncedEstimate = debounce(refreshEstimate, 300);

async function handleFiles(rawFiles) {
  if (isProcessing) return;
  const files = rawFiles.filter((f) => PNG_RE.test(f.name));
  if (!files.length) {
    exportResult.textContent = "No PNG files found in what you dropped/selected.";
    return;
  }

  isProcessing = true;
  exportResult.textContent = "";
  setProgressVisible(true);
  summarySection.classList.add("hidden");
  exportSection.classList.add("hidden");

  const { successes, failures } = await processFiles(files);
  entries = entries.concat(successes);
  extractionFailures = extractionFailures.concat(failures);

  isProcessing = false;
  setProgressVisible(false);
  renderSummary();
  renderCardGrid();
  refreshEstimate();
}

// --- drag and drop -------------------------------------------------------

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
  })
);
dropzone.addEventListener("drop", async (e) => {
  const files = await filesFromDataTransfer(e.dataTransfer);
  handleFiles(files);
});

// --- click-to-browse -------------------------------------------------------

pickFilesBtn.addEventListener("click", () => fileInput.click());
pickFolderBtn.addEventListener("click", () => folderInput.click());
fileInput.addEventListener("change", () => {
  handleFiles(Array.from(fileInput.files || []));
  fileInput.value = "";
});
folderInput.addEventListener("change", () => {
  handleFiles(Array.from(folderInput.files || []));
  folderInput.value = "";
});

// --- summary / failures toggle -------------------------------------------

toggleFailuresBtn.addEventListener("click", () => {
  const showing = !failuresList.classList.contains("hidden");
  failuresList.classList.toggle("hidden", showing);
  toggleFailuresBtn.textContent = showing ? "show details" : "hide details";
});

// --- export options: live token re-estimate -------------------------------

function updateMaxCharsVisibility() {
  maxCharsLabel.classList.toggle("hidden", fullCheckbox.checked);
}
fullCheckbox.addEventListener("change", () => {
  updateMaxCharsVisibility();
  refreshEstimate();
});
formatSelect.addEventListener("change", refreshEstimate);
sortSelect.addEventListener("change", refreshEstimate);
tokenizerSelect.addEventListener("change", refreshEstimate);
maxCharsInput.addEventListener("input", debouncedEstimate);
fieldCheckboxes.forEach((cb) => cb.addEventListener("change", refreshEstimate));
updateMaxCharsVisibility();

// --- export ----------------------------------------------------------------

exportBtn.addEventListener("click", async () => {
  if (!entries.length) return;
  exportBtn.disabled = true;
  exportResult.textContent = "Generating export…";
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cards: entries.map((e) => e.card), ...currentExportOptions() }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `server error ${res.status}`);
    }
    const blob = new Blob([data.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = data.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    exportResult.textContent = `Downloaded ${data.filename} (${data.content.length.toLocaleString()} chars).`;
  } catch (err) {
    exportResult.textContent = `Export failed: ${err}`;
  } finally {
    exportBtn.disabled = false;
  }
});

// --- reset -------------------------------------------------------------

resetBtn.addEventListener("click", () => {
  for (const entry of entries) URL.revokeObjectURL(entry.thumbUrl);
  entries = [];
  extractionFailures = [];
  renderSummary();
  renderCardGrid();
  totalTokensEl.textContent = "0";
  tokenMethodEl.textContent = "";
  exportResult.textContent = "";
  setProgressVisible(false);
});
