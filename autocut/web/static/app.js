const form = document.getElementById("job-form");
const jobsRoot = document.getElementById("jobs");
const formError = document.getElementById("form-error");
const template = document.getElementById("job-template");
const cards = new Map();
const feedRoot = document.getElementById("feed");
const feedState = document.getElementById("feed-state");
const feedMore = document.getElementById("feed-more");
const feedRefresh = document.getElementById("feed-refresh");
const feedTemplate = document.getElementById("feed-card-template");
const feedSeen = new Set();
let feedOffset = 0;
let feedLoading = false;
let pollTimer = null;

const stageNames = {
  queued: "в очереди", start: "запуск", download: "скачивание",
  analyze: "анализ", transcribe: "субтитры", score: "выбор фрагментов",
  render: "рендер", done: "готово", failed: "ошибка", cancelled: "отменено",
};

function el(selector, root = document) { return root.querySelector(selector); }

function formatViews(value) {
  const count = Number(value) || 0;
  if (count >= 1000000) {
    return `${(count / 1000000).toFixed(1).replace(".", ",")} млн`;
  }
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1).replace(".", ",")} тыс.`;
  }
  return String(count);
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(Number(seconds));
  if (!Number.isFinite(total)) return "—";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function feedCard(item) {
  const node = feedTemplate.content.firstElementChild.cloneNode(true);
  const image = el("img", node);
  if (item.thumbnail) {
    image.src = item.thumbnail;
    image.alt = item.title;
  } else {
    image.remove();
  }
  el(".feed-title", node).textContent = item.title;
  el(".feed-meta", node).textContent =
    `${item.channel} · ${formatDuration(item.duration)} · ${formatViews(item.views)}`;
  el(".feed-pick", node).addEventListener("click", () => {
    const input = document.getElementById("source");
    input.value = item.url;
    input.focus();
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.classList.add("flash");
    setTimeout(() => input.classList.remove("flash"), 1200);
  });
  return node;
}

async function loadFeed(reset = false) {
  if (feedLoading) return;
  feedLoading = true;
  if (reset) {
    feedSeen.clear();
    feedRoot.innerHTML = "";
    feedOffset = 0;
    feedMore.classList.add("hidden");
  }
  feedState.classList.remove("error");
  feedState.textContent = "Загружаем ленту…";
  try {
    const response = await fetch(`/api/feed?offset=${feedOffset}&limit=12`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    for (const item of data.items || []) {
      if (feedSeen.has(item.id)) continue;
      feedSeen.add(item.id);
      feedRoot.append(feedCard(item));
    }
    feedOffset = data.next_offset ?? feedOffset + 12;
    feedMore.classList.toggle("hidden", !data.has_more);
    feedState.textContent = feedSeen.size ? "" : "Лента пуста.";
  } catch (err) {
    feedState.textContent = `Лента недоступна: ${err.message}`;
    feedState.classList.add("error");
  } finally {
    feedLoading = false;
  }
}

feedMore.addEventListener("click", () => loadFeed(false));
feedRefresh.addEventListener("click", () => loadFeed(true));
loadFeed(true);

function getCard(job) {
  if (cards.has(job.id)) return cards.get(job.id);
  const node = template.content.firstElementChild.cloneNode(true);
  const card = {
    node,
    title: el(".job-title", node),
    cancel: el(".cancel", node),
    bar: el(".bar", node),
    status: el(".job-status", node),
    folder: el(".folder", node),
    clips: el(".clips", node),
  };
  card.title.textContent = job.source;
  card.cancel.addEventListener("click", async () => {
    await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
  });
  jobsRoot.prepend(node);
  cards.set(job.id, card);
  return card;
}

function renderJob(job) {
  const card = getCard(job);
  const active = ["queued", "running"].includes(job.status);
  card.node.dataset.status = job.status;
  card.cancel.classList.toggle("hidden", !active);
  card.bar.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
  const stage = stageNames[job.stage] || job.stage;
  card.status.textContent = job.error
    ? `${stage}: ${job.error}`
    : `${stage} — ${Math.round(job.progress || 0)}% ${job.message || ""}`;

  const result = job.result;
  if (result && result.result_dir) {
    card.folder.textContent = result.result_dir;
  }
  if (result && result.clips) {
    card.clips.innerHTML = "";
    for (const clip of result.clips) {
      const item = document.createElement("div");
      item.className = "clip";
      item.innerHTML = `
        ${clip.preview_url ? `<img src="${clip.preview_url}" alt="">` : ""}
        <div class="clip-meta">
          <strong>Клип ${clip.index}</strong>
          <span>${Number(clip.start).toFixed(1)}–${Number(clip.end).toFixed(1)} с · score ${Number(clip.score).toFixed(2)}</span>
          <div class="clip-links">
            ${clip.file_url ? `<a href="${clip.file_url}" download>скачать mp4</a>` : ""}
            ${clip.subtitle_url ? `<a href="${clip.subtitle_url}" download>ass</a>` : ""}
          </div>
        </div>`;
      card.clips.append(item);
    }
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/jobs");
    const jobs = await response.json();
    jobs.forEach(renderJob);
  } catch (err) {
    console.error(err);
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(refresh, 1200);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.classList.add("hidden");
  const source = document.getElementById("source").value.trim();
  if (!source) return;
  const payload = {
    source,
    options: {
      clips: Number(document.getElementById("clips").value),
      min_duration: Number(document.getElementById("min-duration").value),
      max_duration: Number(document.getElementById("max-duration").value),
      layout: document.getElementById("layout").value,
      proxy: document.getElementById("proxy").value.trim() || null,
    },
  };
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    const job = await response.json();
    renderJob(job);
    form.reset();
    startPolling();
    const events = new EventSource(`/api/jobs/${job.id}/events`);
    events.onmessage = (message) => {
      renderJob(JSON.parse(message.data));
    };
    events.onerror = () => {
      events.close();
      startPolling();
    };
    setTimeout(refresh, 300);
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove("hidden");
  }
});

refresh();
setInterval(refresh, 3000);
