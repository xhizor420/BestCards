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
const fullCheckbox = document.getElementById("fullCheckbox");
const maxCharsLabel = document.getElementById("maxCharsLabel");
const maxCharsInput = document.getElementById("maxCharsInput");
const exportBtn = document.getElementById("exportBtn");
const exportResult = document.getElementById("exportResult");
const resetBtn = document.getElementById("resetBtn");

let extractedCards = [];
let extractionFailures = [];
let isProcessing = false;

const CONCURRENCY = 6;
const PNG_RE = /\.png$/i;

function readEntryFile(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

function readAllDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    let all = [];
    (function readBatch() {
      reader.readEntries((entries) => {
        if (!entries.length) {
          resolve(all);
        } else {
          all = all.concat(entries);
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
    const entries = await readAllDirectoryEntries(reader);
    const nested = await Promise.all(entries.map(traverseEntry));
    return nested.flat();
  }
  return [];
}

async function filesFromDataTransfer(dataTransfer) {
  const items = dataTransfer.items;
  if (items && items.length && items[0].webkitGetAsEntry) {
    const entries = Array.from(items)
      .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
      .filter(Boolean);
    const nested = await Promise.all(entries.map(traverseEntry));
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
          successes.push(data.card);
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
  successCountEl.textContent = String(extractedCards.length);
  failCountEl.textContent = String(extractionFailures.length);
  summarySection.classList.toggle("hidden", extractedCards.length === 0 && extractionFailures.length === 0);
  exportSection.classList.toggle("hidden", extractedCards.length === 0);

  failuresList.innerHTML = "";
  for (const f of extractionFailures) {
    const li = document.createElement("li");
    li.textContent = `${f.name}: ${f.error}`;
    failuresList.appendChild(li);
  }
}

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
  extractedCards = extractedCards.concat(successes);
  extractionFailures = extractionFailures.concat(failures);

  isProcessing = false;
  setProgressVisible(false);
  renderSummary();
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

// --- export ----------------------------------------------------------------

function updateMaxCharsVisibility() {
  maxCharsLabel.classList.toggle("hidden", fullCheckbox.checked);
}
fullCheckbox.addEventListener("change", updateMaxCharsVisibility);
updateMaxCharsVisibility();

exportBtn.addEventListener("click", async () => {
  if (!extractedCards.length) return;
  exportBtn.disabled = true;
  exportResult.textContent = "Generating export…";
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cards: extractedCards,
        format: formatSelect.value,
        sort: sortSelect.value,
        full: fullCheckbox.checked,
        max_chars: parseInt(maxCharsInput.value, 10) || 600,
      }),
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
  extractedCards = [];
  extractionFailures = [];
  renderSummary();
  exportResult.textContent = "";
  setProgressVisible(false);
});
