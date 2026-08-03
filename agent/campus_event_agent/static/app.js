/* 前端状态：保存当前会话历史，并用 localStorage 持久化会话 ID。 */
const state = {
  history: [],
  sessionId: localStorage.getItem("campus_event_session") || `session-${Date.now()}`,
};

// 查询 DOM 的简写。
const $ = (selector) => document.querySelector(selector);

// 统一封装 fetch：自动解析 JSON，并把非 2xx 转成可读错误。
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `请求失败 ${response.status}`);
  }
  return data;
}

// 把 ISO 时间格式化为页面展示用的 YYYY-MM-DD HH:mm。
function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// 转义 HTML，防止活动名称等文本被当作标签执行。
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// 加载活动数、LLM 状态、调用统计、待审核数和提醒/推送条。
async function loadStats() {
  try {
    const data = await api("/api/status");
    $("#event-count").textContent = `活动：${data.event_count}`;
    $("#llm-status").textContent = data.llm.enabled ? `LLM：${data.llm.model}` : "LLM：离线";
    $("#usage-text").textContent = `调用 ${data.usage.total_calls} 次`;
    const pending = await api("/api/pending");
    $("#pending-count").textContent = `待审核：${pending.pending.length}`;
    await renderReminderAlerts();
    await renderNotifications();
  } catch (error) {
    console.error(error);
  }
}

// 加载类别下拉框。
async function loadCategories() {
  const data = await api("/api/categories");
  const select = $("#category-select");
  select.innerHTML = '<option value="">全部类别</option>';
  for (const category of data.categories) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    select.appendChild(option);
  }
}

// 加载用户兴趣标签，并回填勾选状态和自定义标签。
async function loadPreferences() {
  const [prefs, cats] = await Promise.all([api("/api/preferences"), api("/api/categories")]);
  const options = $("#pref-category-options");
  options.innerHTML = "";
  const selected = new Set(prefs.preferences.tags || []);
  const allTags = [...new Set([...cats.categories, ...selected])];
  for (const tag of allTags) {
    const label = document.createElement("label");
    label.className = "pref-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = tag;
    input.checked = selected.has(tag);
    label.appendChild(input);
    label.appendChild(document.createTextNode(tag));
    options.appendChild(label);
  }
  const custom = [...selected].filter((tag) => !cats.categories.includes(tag));
  $("#pref-custom").value = custom.join(", ");
}

// 保存类别标签和自定义标签，随后刷新推送。
async function savePreferences() {
  const selected = [...document.querySelectorAll("#pref-category-options input:checked")].map((input) => input.value);
  const custom = $("#pref-custom").value.split(/[,\uFF0C\u3001\s]+/).map((item) => item.trim()).filter(Boolean);
  const tags = [...new Set([...selected, ...custom])];
  await api("/api/preferences", {
    method: "POST",
    body: JSON.stringify({ tags }),
  });
  await loadPreferences();
  await renderNotifications();
  $("#pref-status").textContent = `\u5df2\u4fdd\u5b58\uff1a${tags.join("\u3001") || "\u6682\u65e0\u6807\u7b7e"}\uff1b\u65b0\u6d3b\u52a8\u547d\u4e2d\u4efb\u4e00\u6807\u7b7e\u5373\u63a8\u9001\u3002`;
}

// 按关键词、类别和日期查询活动。
async function loadEvents() {
  const params = new URLSearchParams();
  const q = $("#search-input").value.trim();
  const category = $("#category-select").value;
  const from = $("#from-input").value;
  if (q) params.set("q", q);
  if (category) params.set("category", category);
  if (from) {
    params.set("from", `${from}T00:00:00`);
    params.set("to", `${from}T23:59:59`);
  }
  const data = await api(`/api/events?${params.toString()}`);
  renderEvents(data.events);
}

// 渲染统一活动列表，空结果时显示占位提示。
function renderEvents(events) {
  const body = $("#events-body");
  body.innerHTML = "";
  $("#result-count").textContent = `${events.length} 条结果`;
  $("#empty-events").classList.toggle("hidden", events.length > 0);
  for (const event of events) {
    const tr = document.createElement("tr");
    const tags = (event.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
    tr.innerHTML = `
      <td><div class="event-name">${escapeHtml(event.name)}</div>${tags}</td>
      <td>${escapeHtml(formatTime(event.standard_time))}</td>
      <td>${escapeHtml(event.duration || "-")}</td>
      <td>${escapeHtml(event.location)}</td>
      <td>${escapeHtml(event.category)}</td>
      <td>${escapeHtml(event.source)}</td>
    `;
    body.appendChild(tr);
  }
}

// 渲染提醒列表和状态按钮。
async function renderReminders() {
  const data = await api("/api/reminders");
  const container = $("#reminders-list");
  container.innerHTML = "";
  if (!data.reminders.length) {
    container.innerHTML = '<p class="empty">暂无提醒</p>';
    return;
  }
  for (const reminder of data.reminders) {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <strong>${escapeHtml(reminder.event_name)}</strong>
      <p>时间：${escapeHtml(formatTime(reminder.due_at))}</p>
      <p>状态：${escapeHtml(reminder.status === "pending" ? "\u5f85\u63d0\u9192" : reminder.status === "notified" ? "\u5df2\u5230\u63d0\u9192" : reminder.status === "done" ? "\u5df2\u5b8c\u6210" : reminder.status === "cancelled" ? "\u5df2\u53d6\u6d88" : reminder.status)}</p>
      <div class="item-actions">
        <button data-action="complete" data-id="${escapeHtml(reminder.id)}" type="button">完成</button>
        <button data-action="cancel" data-id="${escapeHtml(reminder.id)}" type="button" class="danger">取消</button>
      </div>
    `;
    container.appendChild(item);
  }
}

// 渲染待人工确认的抓取记录。
async function renderPending() {
  const data = await api("/api/pending");
  const container = $("#pending-list");
  container.innerHTML = "";
  if (!data.pending.length) {
    container.innerHTML = '<p class="empty">当前没有待人工确认记录</p>';
    return;
  }
  for (const item of data.pending) {
    const raw = item.raw || {};
    const title = raw.name || item.id || "未命名记录";
    const rawTime = raw.time || raw.raw_time || "时间缺失";
    const location = raw.location || "地点缺失";
    const sourceLink = raw.source_url
      ? ` <a href="${escapeHtml(raw.source_url)}" target="_blank" rel="noopener">查看原文</a>`
      : "";
    const card = document.createElement("div");
    card.className = "list-item";
    card.innerHTML = `
      <strong>${escapeHtml(title)}</strong>
      <p>时间：${escapeHtml(rawTime)}；地点：${escapeHtml(location)}</p>
      <p class="muted">${escapeHtml(item.reason || "")}</p>
      <p class="muted">${escapeHtml(raw.source || "校网")}${sourceLink}</p>
      <div class="item-actions">
        <button data-action="approve" data-id="${escapeHtml(item.id)}" type="button">批准入库</button>
        <button data-action="reject" data-id="${escapeHtml(item.id)}" type="button" class="danger">拒绝</button>
      </div>
    `;
    container.appendChild(card);
  }
}

// 在顶部条显示已到期的提醒。
async function renderReminderAlerts() {
  const data = await api("/api/reminders");
  const strip = $("#reminder-strip");
  const alerts = data.reminders.filter((item) => item.status === "notified");
  if (!alerts.length) {
    strip.classList.add("hidden");
    strip.innerHTML = "";
    return;
  }
  strip.innerHTML = `\u5230\u70b9\u63d0\u9192\uff1a${alerts.map((item) => `<span>${escapeHtml(item.event_name)}\uff08${escapeHtml(formatTime(item.due_at))}\uff09<button data-action="complete" data-id="${escapeHtml(item.id)}" type="button">\u5b8c\u6210</button></span>`).join("\uff1b")}`;
  strip.classList.remove("hidden");
}

// 在顶部条显示未读的兴趣推送。
async function renderNotifications() {
  const data = await api("/api/notifications");
  const strip = $("#notification-strip");
  const unread = data.notifications.filter((item) => !item.read);
  if (!unread.length) {
    strip.classList.add("hidden");
    strip.innerHTML = "";
    return;
  }
  strip.innerHTML = `兴趣推送：${unread.map((item) => `<span>${escapeHtml(item.event_name)}（${escapeHtml(formatTime(item.time))}）<button data-action="read-notification" data-id="${escapeHtml(item.event_id)}" type="button">已读</button></span>`).join("；")}`;
  strip.classList.remove("hidden");
}

// 把一条聊天消息追加到对话区并滚动到底部。
function addMessage(role, text) {
  const log = $("#chat-log");
  const item = document.createElement("div");
  item.className = `msg ${role}`;
  item.textContent = text;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

// 发送聊天消息，更新历史、LLM 状态、活动列表和推送/提醒。
async function sendChat(message) {
  if (!message) return;
  addMessage("user", message);
  $("#chat-input").value = "";
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        session_id: state.sessionId,
        history: state.history,
      }),
    });
    state.history = data.history || [];
    addMessage("assistant", data.reply);
    const toolInfo = data.tool_calls ? ` · ${data.tool_calls} 次工具` : "";
    $("#chat-mode").textContent = data.llm_used ? `LangChain Agent${toolInfo}` : "LangChain 离线回复";
    $("#usage-text").textContent = `调用 ${data.stats.total_calls} 次`;
    $("#llm-status").textContent = data.llm_status.enabled ? `LLM：${data.llm_status.model}` : "LLM：离线";
    localStorage.setItem("campus_event_session", state.sessionId);
    await Promise.all([loadEvents(), loadPreferences(), renderReminders(), renderPending(), renderNotifications(), loadStats()]);
    for (const action of data.actions || []) {
      if (action.type === "reminder_created") {
        await renderReminders();
      }
    }
  } catch (error) {
    addMessage("assistant", `请求失败：${error.message}`);
  }
}

// 手动触发一次抓取更新。
async function fetchEvents() {
  const button = $("#fetch-button");
  button.disabled = true;
  button.textContent = "抓取中";
  try {
    const data = await api("/api/fetch", { method: "POST", body: "{}" });
    const pushedText = data.pushed.length ? `，兴趣推送 ${data.pushed.length} 条` : "";
    addMessage("assistant", `抓取完成：读取 ${data.result.fetched} 条，新增 ${data.result.added} 条，待人工确认 ${data.result.pending} 条${pushedText}。`);
    await Promise.all([loadEvents(), renderPending(), renderNotifications(), loadStats()]);
  } catch (error) {
    addMessage("assistant", `抓取失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "抓取更新";
  }
}

// 初始化 Agent/偏好/提醒/待审核四个页签的切换。
function setupTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      $(`#tab-${button.dataset.tab}`).classList.add("active");
    });
  });
}

// 绑定查询、重置、抓取、偏好保存、聊天和列表操作按钮。
function setupActions() {
  $("#search-button").addEventListener("click", loadEvents);
  $("#reset-button").addEventListener("click", () => {
    $("#search-input").value = "";
    $("#category-select").value = "";
    $("#from-input").value = "";
    loadEvents();
  });
  $("#fetch-button").addEventListener("click", fetchEvents);
  $("#save-preferences").addEventListener("click", savePreferences);
  $("#search-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadEvents();
  });
  $("#chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sendChat($("#chat-input").value.trim());
  });
  document.querySelectorAll(".chip").forEach((button) => {
    button.addEventListener("click", () => sendChat(button.dataset.prompt));
  });
  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    const id = target.dataset.id;
    try {
      if (action === "complete" || action === "cancel") {
        await api(`/api/reminders/${action}`, {
          method: "POST",
          body: JSON.stringify({ id }),
        });
        await Promise.all([renderReminders(), renderReminderAlerts()]);
      } else if (action === "read-notification") {
        await api("/api/notifications/read", {
          method: "POST",
          body: JSON.stringify({ event_id: id }),
        });
        await renderNotifications();
      } else if (action === "approve" || action === "reject") {
        await api("/api/pending/review", {
          method: "POST",
          body: JSON.stringify({ id, approved: action === "approve" }),
        });
        await Promise.all([renderPending(), loadEvents(), loadStats()]);
      }
    } catch (error) {
      addMessage("assistant", `操作失败：${error.message}`);
    }
  });
}

// 页面初始化：先加载类别、偏好、活动、提醒、待审核和状态。
async function init() {
  state.sessionId = localStorage.getItem("campus_event_session") || state.sessionId;
  localStorage.setItem("campus_event_session", state.sessionId);
  addMessage("assistant", "你好，我可以查询活动、解析时间、设置兴趣标签并创建提醒。");
  setupTabs();
  setupActions();
  await Promise.all([loadCategories(), loadPreferences(), loadEvents(), renderReminders(), renderPending(), loadStats()]);
}

init();
// 每 30 秒刷新一次状态和提醒，保持后台任务结果及时可见。
setInterval(() => {
  loadStats();
  renderReminders();
}, 30000);

