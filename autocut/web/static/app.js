const form = document.getElementById("job-form");
const jobsRoot = document.getElementById("jobs");
const formError = document.getElementById("form-error");
const template = document.getElementById("job-template");
const cards = new Map();
const activeJobs = new Set();
const feedRoot = document.getElementById("feed");
const feedState = document.getElementById("feed-state");
const feedMore = document.getElementById("feed-more");
const feedRefresh = document.getElementById("feed-refresh");
const feedTemplate = document.getElementById("feed-card-template");
const feedSeen = new Set();
let feedOffset = 0;
let feedLoading = false;
let pollTimer = null;

const playlistPanel = document.getElementById("playlist-panel");
const playlistTitle = document.getElementById("playlist-title");
const playlistCount = document.getElementById("playlist-count");
const playlistItemsRoot = document.getElementById("playlist-items");
const playlistRun = document.getElementById("playlist-run");
const playlistTemplate = document.getElementById("playlist-item-template");
const selectedPlaylist = new Map();
let mode = "video";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

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

function formatTime(seconds) {
  const value = Number(seconds);
  return Number.isFinite(value) ? value.toFixed(1) : "?";
}

function apiError(data, status) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail.length) {
    const messages = data.detail
      .map((item) => item && item.msg)
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
    return "Проверьте параметры запроса";
  }
  return `HTTP ${status}`;
}

function showError(message) {
  formError.textContent = message;
  formError.classList.remove("hidden");
}

function hideError() {
  formError.textContent = "";
  formError.classList.add("hidden");
}

function fallbackImage(image) {
  image.addEventListener("error", () => {
    image.remove();
    image.closest(".feed-item, .playlist-item")?.classList.add("no-thumb");
  }, { once: true });
}

function setMode(next) {
  mode = next;
  document.querySelectorAll(".mode").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === next);
    button.setAttribute("aria-pressed", String(button.dataset.mode === next));
  });
  document.getElementById("submit").textContent =
    next === "playlist" ? "Показать список" : "Сделать клипы";
  if (next === "video") playlistPanel.classList.add("hidden");
}

function parseTime(value) {
  if (!value.trim()) {
    throw new Error("Пустое время в диапазоне");
  }
  const parts = value.trim().split(":").map(Number);
  if (parts.some((part) => !Number.isFinite(part))) {
    throw new Error(`Время «${value}» не понято. Пример: 1:05`);
  }
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  throw new Error(`Слишком много частей во времени «${value}»`);
}

function parseRanges(raw) {
  const items = raw.split(/[\n;]+/).map((part) => part.trim()).filter(Boolean);
  const result = [];
  for (const item of items) {
    const normalized = item.replace(/[–—]/g, "-").trim();
    let left;
    let right;
    const dash = normalized.lastIndexOf("-");
    if (dash > 0) {
      left = normalized.slice(0, dash).trim();
      right = normalized.slice(dash + 1).trim();
    } else {
      const colon = normalized.indexOf(":");
      if (colon < 0) {
        throw new Error(`Диапазон «${item}» не понят. Пример: 12-42`);
      }
      left = normalized.slice(0, colon).trim();
      right = normalized.slice(colon + 1).trim();
    }
    const start = parseTime(left);
    const end = parseTime(right);
    if (start < 0 || end <= start) {
      throw new Error(`Некорректный диапазон «${item}»`);
    }
    if (end - start < 1 || end - start > 300) {
      throw new Error(`Диапазон «${item}» должен быть от 1 до 300 секунд`);
    }
    result.push([start, end]);
  }
  return result.length ? result : null;
}

function currentOptions() {
  return {
    clips: Number(document.getElementById("clips").value),
    min_duration: Number(document.getElementById("min-duration").value),
    max_duration: Number(document.getElementById("max-duration").value),
    ranges: parseRanges(document.getElementById("ranges").value),
    layout: document.getElementById("layout").value,
    crop_focus: document.getElementById("crop-focus").value,
    subtitles: document.getElementById("subtitles").checked,
    variation: document.getElementById("variation").value,
    style: document.getElementById("style").value,
    caption_mode: document.getElementById("caption-mode").value,
    hook: document.getElementById("hook").checked,
    end_card: document.getElementById("end-card").checked,
    watermark: document.getElementById("watermark").value.trim() || null,
    loudnorm: document.getElementById("loudnorm").checked,
    safe_zones: document.getElementById("safe-zones").checked,
    proxy: document.getElementById("proxy").value.trim() || null,
  };
}

function updatePlaylistCount() {
  const count = selectedPlaylist.size;
  playlistRun.textContent = `Запустить выбранные (${count})`;
  playlistRun.disabled = count === 0;
}

function playlistItem(item) {
  const node = playlistTemplate.content.firstElementChild.cloneNode(true);
  const checkbox = el("input", node);
  const image = el("img", node);
  if (item.thumbnail) {
    fallbackImage(image);
    image.src = item.thumbnail;
    image.alt = item.title;
  } else {
    image.remove();
    node.classList.add("no-thumb");
  }
  el(".playlist-item-title", node).textContent = item.title;
  el(".playlist-item-meta", node).textContent =
    `${item.channel} · ${formatDuration(item.duration)}`;
  checkbox.addEventListener("change", () => {
    if (checkbox.checked && selectedPlaylist.size >= 20) {
      checkbox.checked = false;
      showError("Можно выбрать не более 20 видео");
      return;
    }
    if (checkbox.checked) selectedPlaylist.set(item.url, item);
    else selectedPlaylist.delete(item.url);
    hideError();
    updatePlaylistCount();
  });
  return node;
}

async function loadPlaylist(url) {
  playlistPanel.classList.remove("hidden");
  playlistItemsRoot.replaceChildren();
  selectedPlaylist.clear();
  updatePlaylistCount();
  playlistTitle.textContent = "Загружаем плейлист…";
  playlistCount.textContent = "";

  const response = await fetch("/api/playlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      limit: 30,
      proxy: document.getElementById("proxy").value.trim() || null,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiError(data, response.status));
  }
  playlistTitle.textContent = data.title;
  playlistCount.textContent = data.truncated
    ? `первые ${data.items.length}`
    : `видео: ${data.items.length}`;
  for (const item of data.items) {
    playlistItemsRoot.append(playlistItem(item));
  }
  if (!data.items.length) {
    playlistTitle.textContent = "В плейлисте нет доступных видео";
  }
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

playlistRun.addEventListener("click", async () => {
  const sources = [...selectedPlaylist.values()].map((item) => item.url);
  if (!sources.length) return;
  const boxes = [...playlistItemsRoot.querySelectorAll("input")];
  boxes.forEach((box) => { box.disabled = true; });
  playlistRun.disabled = true;
  try {
    const response = await fetch("/api/jobs/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, options: currentOptions() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, response.status));
    }
    for (const job of data.jobs || []) renderJob(job);
    startPolling();
    selectedPlaylist.clear();
    playlistItemsRoot.replaceChildren();
    updatePlaylistCount();
    playlistTitle.textContent = "Задачи запущены";
    playlistCount.textContent = `${(data.jobs || []).length} шт.`;
    hideError();
  } catch (err) {
    showError(err.message);
  } finally {
    boxes.forEach((box) => { box.disabled = false; });
    playlistRun.disabled = selectedPlaylist.size === 0;
  }
});

function feedCard(item) {
  const node = feedTemplate.content.firstElementChild.cloneNode(true);
  const image = el("img", node);
  if (item.thumbnail) {
    fallbackImage(image);
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
    setMode("video");
  });
  return node;
}

async function loadFeed(reset = false) {
  if (feedLoading) return;
  feedLoading = true;
  feedRefresh.disabled = true;
  feedMore.disabled = true;
  feedState.classList.remove("error");
  feedState.textContent = "Загружаем ленту…";
  const previousCount = feedSeen.size;
  try {
    const response = await fetch(`/api/feed?offset=${feedOffset}&limit=12`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, response.status));
    }
    if (reset) {
      feedSeen.clear();
      feedRoot.replaceChildren();
      feedOffset = 0;
    }
    for (const item of data.items || []) {
      if (feedSeen.has(item.id)) continue;
      feedSeen.add(item.id);
      feedRoot.append(feedCard(item));
    }
    feedOffset = data.next_offset ?? feedOffset + 12;
    feedMore.classList.toggle("hidden", !data.has_more);
    if (!feedSeen.size) {
      feedState.textContent = "Лента пуста.";
    } else if (!reset && feedSeen.size === previousCount) {
      feedState.textContent = "Новых карточек нет — попробуйте ещё раз.";
    } else {
      feedState.textContent = "";
    }
  } catch (err) {
    feedState.textContent = err.message;
    feedState.classList.add("error");
  } finally {
    feedLoading = false;
    feedRefresh.disabled = false;
    feedMore.disabled = false;
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
    diversity: el(".diversity", node),
    folder: el(".folder", node),
    clips: el(".clips", node),
  };
  card.title.textContent = job.source;
  card.cancel.addEventListener("click", async () => {
    card.cancel.disabled = true;
    try {
      const response = await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(apiError(data, response.status));
      }
      await refresh();
    } catch (err) {
      showError(err.message);
    } finally {
      card.cancel.disabled = false;
    }
  });
  jobsRoot.prepend(node);
  cards.set(job.id, card);
  return card;
}

function clipNode(clip) {
  const item = document.createElement("div");
  item.className = "clip";

  if (clip.preview_url) {
    const image = document.createElement("img");
    image.src = clip.preview_url;
    image.alt = `Клип ${clip.index}`;
    image.loading = "lazy";
    item.append(image);
  }

  const meta = document.createElement("div");
  meta.className = "clip-meta";
  const title = document.createElement("strong");
  title.textContent = `Клип ${clip.index}`;
  meta.append(title);

  const details = document.createElement("span");
  if (clip.error) {
    details.textContent = `Ошибка: ${clip.error}`;
    details.classList.add("clip-error");
  } else {
    details.textContent =
      `${formatTime(clip.start)}–${formatTime(clip.end)} с · score ${Number(clip.score || 0).toFixed(2)}`;
  }
  meta.append(details);

  if (clip.variant) {
    const variant = document.createElement("span");
    variant.className = "clip-variant";
    const parts = [`стиль: ${clip.variant.style}`];
    if (clip.variant.hook) parts.push(`хук: ${clip.variant.hook}`);
    variant.textContent = parts.join(" · ");
    meta.append(variant);
  }

  const links = document.createElement("div");
  links.className = "clip-links";
  if (clip.file_url) {
    const watch = document.createElement("button");
    watch.type = "button";
    watch.className = "ghost";
    watch.textContent = "смотреть";
    watch.addEventListener("click", () => {
      if (item.querySelector("video.clip-video")) return;
      const video = document.createElement("video");
      video.className = "clip-video";
      video.controls = true;
      video.playsInline = true;
      video.preload = "metadata";
      video.src = clip.file_url;
      if (clip.preview_url) video.poster = clip.preview_url;
      const image = item.querySelector("img");
      if (image) image.replaceWith(video);
      else item.prepend(video);
      video.play().catch(() => {});
    });
    links.append(watch);

    const download = document.createElement("a");
    download.href = clip.file_url;
    download.download = "";
    download.textContent = "скачать mp4";
    links.append(download);
  }
  if (clip.subtitle_url) {
    const subtitle = document.createElement("a");
    subtitle.href = clip.subtitle_url;
    subtitle.download = "";
    subtitle.textContent = "ass";
    links.append(subtitle);
  }
  if (clip.publish_url) {
    const publish = document.createElement("a");
    publish.href = clip.publish_url;
    publish.download = "";
    publish.textContent = "подпись";
    links.append(publish);
  }
  if (links.childElementCount) meta.append(links);

  item.append(meta);
  return item;
}

function renderJob(job) {
  const card = getCard(job);
  const active = ACTIVE_STATUSES.has(job.status);
  if (active) activeJobs.add(job.id);
  else activeJobs.delete(job.id);

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
  if (result && result.diversity) {
    const diversity = result.diversity;
    const similar = Math.round((diversity.max_similarity || 0) * 100);
    card.diversity.classList.toggle("warning", !diversity.ok);
    card.diversity.textContent = diversity.ok
      ? `Разнообразие клипов: ${Math.round((diversity.score || 1) * 100)}%`
      : `Клипы похожи на ${similar}% — замените один из них перед публикацией`;
  } else {
    card.diversity.textContent = "";
  }
  if (result && Array.isArray(result.clips)) {
    card.clips.replaceChildren();
    for (const clip of result.clips) {
      card.clips.append(clipNode(clip));
    }
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/jobs");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const jobs = await response.json();
    jobs.forEach(renderJob);
  } catch (err) {
    console.error(err);
  }
}

function startPolling() {
  if (pollTimer) return;
  const tick = async () => {
    await refresh();
    pollTimer = activeJobs.size ? setTimeout(tick, 1500) : null;
  };
  pollTimer = setTimeout(tick, 0);
}

async function uploadVideo(file) {
  const status = document.getElementById("upload-status");
  if (!file) return;
  status.textContent = `Загрузка ${file.name}…`;
  const data = new FormData();
  data.append("file", file);
  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: data,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    const uploaded = await response.json();
    setMode("video");
    document.getElementById("source").value = uploaded.path;
    status.textContent = `Загружено: ${uploaded.name}`;
  } catch (err) {
    status.textContent = `Ошибка загрузки: ${err.message}`;
  }
}

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
document.getElementById("file-pick").addEventListener("click", () => {
  fileInput.click();
});
fileInput.addEventListener("change", () => {
  uploadVideo(fileInput.files[0]);
  fileInput.value = "";
});
["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragover");
  });
});
dropZone.addEventListener("drop", (event) => {
  uploadVideo(event.dataTransfer.files[0]);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError();
  const source = document.getElementById("source").value.trim();
  if (!source) return;

  if (mode === "playlist") {
    const submitButton = document.getElementById("submit");
    submitButton.disabled = true;
    try {
      await loadPlaylist(source);
    } catch (err) {
      playlistTitle.textContent = "Не удалось загрузить плейлист";
      playlistCount.textContent = "";
      showError(err.message);
    } finally {
      submitButton.disabled = false;
    }
    return;
  }

  const submitButton = document.getElementById("submit");
  submitButton.disabled = true;
  try {
    const payload = { source, options: currentOptions() };
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(apiError(data, response.status));
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
  } catch (err) {
    showError(err.message);
  } finally {
    submitButton.disabled = false;
  }
});

refresh().then(() => {
  if (activeJobs.size) startPolling();
});
