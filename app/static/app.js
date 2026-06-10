const state = {
  projects: [],
  activeProjectId: "p-demo",
  inventory: [],
  reservations: [],
  knowledgeDocs: [],
  selectedParts: [],
  recommendedParts: [],
  pendingSelection: null,
  pendingKnowledgeImport: null,
  currentTraceId: null,
  sending: false,
};

const qs = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const response = await fetch(path, { headers, ...options });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || "请求失败");
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function setPage(page) {
  qs("#agentPage").classList.toggle("active", page === "agent");
  qs("#libraryPage").classList.toggle("active", page === "library");
  qs("#navAgent").classList.toggle("active", page === "agent");
  qs("#navLibrary").classList.toggle("active", page === "library");
}

function renderProjects() {
  const list = qs("#projectList");
  list.innerHTML = "";
  for (const project of state.projects) {
    const item = document.createElement("div");
    item.className = "project-item" + (project.id === state.activeProjectId ? " active" : "");
    item.innerHTML = `<button class="project-delete" data-delete-project="${project.id}">×</button><strong>${escapeHtml(project.name)}</strong><span>${escapeHtml(project.category)}</span><p>${escapeHtml(project.description || "暂无描述")}</p>`;
    item.onclick = async () => {
      if (state.activeProjectId === project.id) return;
      state.activeProjectId = project.id;
      state.recommendedParts = [];
      state.pendingSelection = null;
      state.currentTraceId = null;
      renderProjects();
      renderActiveProject();
      await Promise.all([loadMessages(), loadSelectedParts()]);
    };
    list.appendChild(item);
  }
  list.querySelectorAll("[data-delete-project]").forEach((button) => {
    button.onclick = async (event) => {
      event.stopPropagation();
      await deleteProject(button.dataset.deleteProject);
    };
  });
}

function renderActiveProject() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (project) qs("#activeProjectName").textContent = project.name;
}

function appendMessage(role, content = "") {
  const box = qs("#chatMessages");
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = content;
  box.appendChild(item);
  box.scrollTop = box.scrollHeight;
  return item;
}

function renderMessages(messages) {
  const box = qs("#chatMessages");
  box.innerHTML = "";
  if (!messages.length) {
    appendMessage("assistant", "直接说板子目标或器件需求。我会给工程判断，并在右侧同步候选器件。");
    return;
  }
  for (const msg of messages) appendMessage(msg.role, msg.content);
}

function partKey(item) {
  return item.part_id || item.mpn || item.id;
}

function renderPartHints() {
  const list = qs("#partHints");
  const selectedKeys = new Set(state.selectedParts.map(partKey));
  const visibleRecommendations = state.recommendedParts.filter((item) => !selectedKeys.has(partKey(item)));
  qs("#hintCount").textContent = `${state.selectedParts.length + visibleRecommendations.length}`;
  qs("#usePlan").disabled = state.selectedParts.length === 0 && visibleRecommendations.length === 0;
  list.innerHTML = "";
  if (!state.selectedParts.length && !visibleRecommendations.length) {
    list.innerHTML = `<div class="empty-state">对话后这里显示推荐和已采用器件。</div>`;
    return;
  }
  for (const part of state.selectedParts) {
    const node = document.createElement("div");
    node.className = "part-hint";
    node.innerHTML = `<button class="hint-close" data-remove-selected="${escapeHtml(partKey(part))}">×</button><strong>${escapeHtml(part.mpn)}</strong><span>已采用 · ${escapeHtml(part.category || "part")} · ${escapeHtml(part.source || "user")}</span><input type="number" min="0" value="${Number(part.quantity || 0)}" data-selected-qty="${escapeHtml(partKey(part))}" />`;
    list.appendChild(node);
  }
  for (const part of visibleRecommendations) {
    const node = document.createElement("div");
    node.className = "part-hint";
    node.innerHTML = `<button class="hint-close" data-drop-recommendation="${escapeHtml(partKey(part))}">×</button><strong>${escapeHtml(part.mpn)}</strong><span>推荐 · ${escapeHtml(part.category || "part")} · ${part.score ? `${part.score}分` : "候选"}</span><input type="number" min="0" value="${Number(part.quantity || 0)}" data-rec-qty="${escapeHtml(partKey(part))}" /><div class="actions"><button data-adopt="${escapeHtml(partKey(part))}">采用</button></div>`;
    list.appendChild(node);
  }
  list.querySelectorAll("[data-selected-qty]").forEach((input) => {
    input.onchange = () => {
      const part = state.selectedParts.find((item) => partKey(item) === input.dataset.selectedQty);
      if (part) {
        part.quantity = Math.max(0, Number(input.value || 0));
        syncSelectedParts().catch((error) => alert(error.message));
      }
    };
  });
  list.querySelectorAll("[data-remove-selected]").forEach((button) => {
    button.onclick = () => {
      state.selectedParts = state.selectedParts.filter((item) => partKey(item) !== button.dataset.removeSelected);
      syncSelectedParts().catch((error) => alert(error.message));
    };
  });
  list.querySelectorAll("[data-drop-recommendation]").forEach((button) => {
    button.onclick = () => {
      state.recommendedParts = state.recommendedParts.filter((item) => partKey(item) !== button.dataset.dropRecommendation);
      renderPartHints();
    };
  });
  list.querySelectorAll("[data-rec-qty]").forEach((input) => {
    input.onchange = () => {
      const part = state.recommendedParts.find((item) => partKey(item) === input.dataset.recQty);
      if (part) part.quantity = Math.max(0, Number(input.value || 0));
      renderPartHints();
    };
  });
  list.querySelectorAll("[data-adopt]").forEach((button) => {
    button.onclick = () => {
      const part = state.recommendedParts.find((item) => partKey(item) === button.dataset.adopt);
      if (part) adoptPart(part).catch((error) => alert(error.message));
    };
  });
}

async function adoptPart(part) {
  const requestedQuantity = Number(part.quantity || 0);
  state.selectedParts.push({
    id: part.part_id ? `sel-${part.part_id}` : `sel-${part.mpn}`,
    part_id: part.part_id || null,
    mpn: part.mpn,
    category: part.category || "",
    quantity: requestedQuantity > 0 ? requestedQuantity : 1,
    source: "user_adopted",
    user_modified: true,
  });
  state.recommendedParts = state.recommendedParts.filter((item) => partKey(item) !== partKey(part));
  await syncSelectedParts();
}

async function syncSelectedParts() {
  const data = await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/selected-parts`, {
    method: "PATCH",
    body: JSON.stringify({ trace_id: state.currentTraceId, parts: state.selectedParts }),
  });
  state.selectedParts = data.parts;
  renderPartHints();
}

async function sendDiscuss() {
  if (state.sending) return;
  const message = qs("#messageInput").value.trim();
  if (!message || !state.activeProjectId) return;
  state.sending = true;
  qs("#workflowBadge").textContent = "LLM 协商中";
  qs("#messageInput").value = "";
  appendMessage("user", message);
  const assistantNode = appendMessage("assistant", "");
  try {
    const response = await fetch("/api/agent/discuss/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.activeProjectId, message }),
    });
    if (!response.ok || !response.body) throw new Error("LLM 流式响应失败");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let metaPayload = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.trace_id) state.currentTraceId = event.trace_id;
        if (event.type === "delta") assistantNode.textContent += event.text;
        if (event.type === "meta") metaPayload = event.payload || {};
      }
      qs("#chatMessages").scrollTop = qs("#chatMessages").scrollHeight;
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      if (event.trace_id) state.currentTraceId = event.trace_id;
      if (event.type === "delta") assistantNode.textContent += event.text;
      if (event.type === "meta") metaPayload = event.payload || {};
    }
    if (metaPayload) {
      state.pendingSelection = metaPayload.pending_selection || null;
      state.recommendedParts = metaPayload.recommended_parts || [];
      state.selectedParts = metaPayload.selected_parts_snapshot || state.selectedParts;
      renderPartHints();
    }
    qs("#workflowBadge").textContent = state.currentTraceId ? `trace ${state.currentTraceId}` : "已回复";
  } finally {
    state.sending = false;
  }
}

function summarizeParams(params) {
  const labels = { vin_min: "最小输入电压", vin_max: "最大输入电压", vout: "输出电压", vout_min: "最小输出电压", vout_max: "最大输出电压", iout_max: "最大输出电流", dropout_mv: "压差", noise_uvrms: "噪声", iq_ua: "静态电流", switching_frequency_khz: "开关频率", efficiency_pct: "效率", resolution_bits: "分辨率", sample_rate_ksps: "采样率", update_rate_ksps: "更新率", channels: "通道数", interface: "接口", input_type: "输入类型", output_type: "输出类型", reference: "参考源", flash_kb: "Flash", ram_kb: "RAM", gpio: "GPIO", interfaces: "外设接口", core: "内核" };
  return Object.entries(params || {}).slice(0, 8).map(([key, value]) => `${labels[key] || key}: ${Array.isArray(value) ? value.join("/") : value}`).join(" · ");
}

function renderInventory() {
  const body = qs("#inventoryTable");
  body.innerHTML = "";
  for (const part of state.inventory) {
    const row = document.createElement("tr");
    row.innerHTML = `<td><strong>${escapeHtml(part.mpn)}</strong><br><span>${escapeHtml(part.manufacturer || "未知厂商")} · ${escapeHtml(part.package || "未填封装")}</span></td><td>${escapeHtml(part.category)}</td><td class="param-cell">${escapeHtml(summarizeParams(part.parameters))}</td><td><input class="location-input" value="${escapeHtml(part.location || "")}" data-location="${part.id}" /></td><td>${part.quantity_available} / ${part.quantity_total}</td><td><div class="stock-controls"><input type="number" min="0" value="${part.quantity_total}" data-stock="${part.id}" /><button data-save-stock="${part.id}">保存</button></div></td>`;
    body.appendChild(row);
  }
  body.querySelectorAll("[data-save-stock]").forEach((button) => {
    button.onclick = () => {
      const id = button.dataset.saveStock;
      adjustStock(id, Number(body.querySelector(`[data-stock="${id}"]`).value), body.querySelector(`[data-location="${id}"]`).value).catch((error) => alert(error.message));
    };
  });
  const select = qs("#datasheetPart");
  select.innerHTML = `<option value="">自动识别并新建芯片（库存=0）</option>`;
  for (const part of state.inventory) select.insertAdjacentHTML("beforeend", `<option value="${part.id}">${escapeHtml(part.mpn)} · ${escapeHtml(part.location || "")}</option>`);
}

function renderReservations() {
  const list = qs("#reservationList");
  list.innerHTML = "";
  if (!state.reservations.length) {
    list.innerHTML = `<div class="empty-state">暂无预占记录。</div>`;
    return;
  }
  for (const reservation of state.reservations) {
    const part = state.inventory.find((item) => item.id === reservation.part_id);
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `<strong>${escapeHtml(part ? part.mpn : reservation.part_id)}</strong><span>数量 ${reservation.quantity} · 状态 ${reservation.status}</span>${reservation.status === "reserved" ? `<div class="actions"><button data-confirm="${reservation.id}">确认出库</button><button class="warning" data-cancel="${reservation.id}">取消</button></div>` : ""}`;
    const confirm = item.querySelector("[data-confirm]");
    const cancel = item.querySelector("[data-cancel]");
    if (confirm) confirm.onclick = () => confirmReservation(reservation.id);
    if (cancel) cancel.onclick = () => cancelReservation(reservation.id);
    list.appendChild(item);
  }
}

function renderKnowledgeDocs() {
  const list = qs("#knowledgeDocs");
  qs("#knowledgeCount").textContent = `${state.knowledgeDocs.length} 份文档`;
  list.innerHTML = "";
  if (!state.knowledgeDocs.length) {
    list.innerHTML = `<div class="empty-state">还没有导入数据手册。</div>`;
    return;
  }
  for (const doc of state.knowledgeDocs) {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `<strong>${escapeHtml(doc.filename)}</strong><span>${doc.pages} 页 · ${doc.chunks} 个片段 · ${escapeHtml(doc.part_id || "未绑定")}</span>`;
    list.appendChild(item);
  }
}

function renderDatasheetPreview(data) {
  const box = qs("#datasheetPreview");
  const part = data.editable_part;
  if (!part) {
    box.classList.remove("hidden");
    box.innerHTML = `<strong>已解析文档，但未识别新芯片。</strong><p>该数据手册将绑定到所选芯片。</p>`;
    return;
  }
  const warnings = (data.warnings || []).map((item) => `<div class="empty-state">${escapeHtml(item)}</div>`).join("");
  box.classList.remove("hidden");
  box.innerHTML = `
    <strong>解析结果预览，可修改后入库</strong>
    ${warnings}
    <div class="library-grid">
      <input id="previewMpn" value="${escapeHtml(part.mpn || "")}" placeholder="型号" />
      <input id="previewManufacturer" value="${escapeHtml(part.manufacturer || "")}" placeholder="厂商" />
      <select id="previewCategory">
        ${["ldo", "buck", "adc", "dac", "mcu", "unknown"].map((category) => `<option value="${category}" ${part.category === category ? "selected" : ""}>${category}</option>`).join("")}
      </select>
      <input id="previewPackage" value="${escapeHtml(part.package || "")}" placeholder="封装" />
      <input id="previewLocation" value="${escapeHtml(part.location || "待入库")}" placeholder="库位" />
    </div>
    <textarea id="previewDescription" placeholder="描述">${escapeHtml(part.description || "")}</textarea>
    <label>参数 JSON</label>
    <textarea id="previewParameters" spellcheck="false">${escapeHtml(JSON.stringify(part.parameters || {}, null, 2))}</textarea>
    <div class="empty-state">建议参数：${escapeHtml((data.parameters_schema || []).join(", ") || "无")}</div>
    <div class="list-stack">${(data.chunks_preview || []).map((chunk) => `<div class="list-item"><strong>${escapeHtml(chunk.title)} · p${chunk.page}</strong><span>${escapeHtml((chunk.text || "").slice(0, 240))}...</span></div>`).join("")}</div>
  `;
}

function collectEditedPart() {
  const raw = qs("#previewParameters")?.value || "{}";
  let parameters;
  try {
    parameters = JSON.parse(raw);
  } catch {
    throw new Error("参数 JSON 格式不正确");
  }
  return {
    ...(state.pendingKnowledgeImport?.editable_part || {}),
    mpn: qs("#previewMpn").value.trim(),
    manufacturer: qs("#previewManufacturer").value.trim(),
    category: qs("#previewCategory").value,
    package: qs("#previewPackage").value.trim(),
    location: qs("#previewLocation").value.trim() || "待入库",
    description: qs("#previewDescription").value.trim(),
    parameters,
  };
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects;
  if (!state.projects.some((project) => project.id === state.activeProjectId)) state.activeProjectId = state.projects[0]?.id || "";
  renderProjects();
  renderActiveProject();
}

async function loadMessages() {
  if (!state.activeProjectId) return;
  const data = await api(`/api/agent/messages?project_id=${encodeURIComponent(state.activeProjectId)}`);
  renderMessages(data.messages);
}

async function loadSelectedParts() {
  if (!state.activeProjectId) return;
  const data = await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/selected-parts`);
  state.selectedParts = data.parts;
  renderPartHints();
}

async function loadInventory() {
  const data = await api("/api/inventory");
  state.inventory = data.parts;
  renderInventory();
}

async function loadReservations() {
  const data = await api("/api/reservations");
  state.reservations = data.reservations;
  renderReservations();
}

async function loadKnowledgeDocs() {
  const data = await api("/api/knowledge/documents");
  state.knowledgeDocs = data.documents;
  renderKnowledgeDocs();
}

async function loadModelStatus() {
  const data = await api("/api/system/model");
  qs("#modelName").textContent = data.available ? `${data.model} 已接入` : "LLM 未配置";
}

async function adjustStock(partId, quantityTotal, location) {
  const data = await api(`/api/inventory/${partId}/stock`, { method: "PATCH", body: JSON.stringify({ quantity_total: quantityTotal, location }) });
  state.inventory = data.inventory;
  renderInventory();
}

async function confirmReservation(id) {
  const data = await api(`/api/reservations/${id}/confirm`, { method: "POST" });
  state.inventory = data.inventory;
  await loadReservations();
  renderInventory();
}

async function cancelReservation(id) {
  const data = await api(`/api/reservations/${id}/cancel`, { method: "POST" });
  state.inventory = data.inventory;
  await loadReservations();
  renderInventory();
}

async function createProject() {
  const name = qs("#projectName").value.trim();
  if (!name) return;
  const data = await api("/api/projects", { method: "POST", body: JSON.stringify({ name, description: qs("#projectDescription").value.trim() }) });
  state.activeProjectId = data.project.id;
  state.recommendedParts = [];
  state.selectedParts = [];
  qs("#projectName").value = "";
  qs("#projectDescription").value = "";
  await Promise.all([loadProjects(), loadMessages(), loadSelectedParts()]);
}

async function deleteProject(projectId) {
  if (!confirm("确认删除该项目及其对话、选型、预占、知识绑定和调试 trace？")) return;
  await api(`/api/projects/${projectId}`, { method: "DELETE" });
  await loadProjects();
  state.recommendedParts = [];
  state.selectedParts = [];
  await Promise.all([loadMessages(), loadSelectedParts(), loadReservations(), loadKnowledgeDocs()]);
}

async function uploadDatasheet() {
  const file = qs("#datasheetFile").files[0];
  if (!file) throw new Error("请先选择 PDF 数据手册");
  const form = new FormData();
  form.append("file", file);
  form.append("project_id", state.activeProjectId);
  form.append("part_id", qs("#datasheetPart").value);
  qs("#datasheetImportStatus").textContent = "正在分析数据手册...";
  qs("#commitDatasheet").disabled = true;
  const data = await api("/api/knowledge/preview", { method: "POST", body: form });
  state.pendingKnowledgeImport = data;
  qs("#datasheetFile").value = "";
  qs("#datasheetImportStatus").innerHTML = `<strong>分析成功，请检查并修改解析结果。</strong>`;
  renderDatasheetPreview(data);
  qs("#commitDatasheet").disabled = false;
}

async function commitDatasheet() {
  if (!state.pendingKnowledgeImport?.token) throw new Error("没有待确认的数据手册导入");
  const body = { token: state.pendingKnowledgeImport.token, edited_document: state.pendingKnowledgeImport.document };
  if (state.pendingKnowledgeImport.editable_part) body.edited_part = collectEditedPart();
  const data = await api("/api/knowledge/commit", { method: "POST", body: JSON.stringify(body) });
  state.pendingKnowledgeImport = null;
  qs("#commitDatasheet").disabled = true;
  qs("#datasheetPreview").classList.add("hidden");
  qs("#datasheetImportStatus").textContent = data.created_part ? `已新增芯片知识：${data.created_part.mpn}，库存为 0。` : "已新增芯片知识。";
  await Promise.all([loadInventory(), loadKnowledgeDocs()]);
}

function openConfirmModal() {
  const parts = state.selectedParts.length ? state.selectedParts : state.recommendedParts.filter((item) => Number(item.quantity || 0) > 0);
  qs("#modalSelection").innerHTML = `<div class="selection-card"><strong>将采用的器件</strong>${parts.length ? parts.map((item) => `<div class="list-item"><strong>${escapeHtml(item.mpn)}</strong><span>${escapeHtml(item.category || "part")} · 数量 ${Number(item.quantity || 0)}</span></div>`).join("") : "<div class='empty-state'>还没有数量大于 0 的器件，请先在右侧采用或设置数量。</div>"}</div>`;
  qs("#finalConfirm").disabled = parts.length === 0;
  qs("#confirmModal").classList.remove("hidden");
}

function closeConfirmModal() {
  qs("#confirmModal").classList.add("hidden");
}

async function confirmSelection() {
  const parts = state.selectedParts.length ? state.selectedParts : state.recommendedParts.filter((item) => Number(item.quantity || 0) > 0).map((item) => ({
    id: item.part_id ? `sel-${item.part_id}` : `sel-${item.mpn}`,
    part_id: item.part_id || null,
    mpn: item.mpn,
    category: item.category || "",
    quantity: Number(item.quantity || 0),
    source: "user_confirmed",
    user_modified: true,
  }));
  const payload = { project_id: state.activeProjectId, trace_id: state.currentTraceId, requirement: state.pendingSelection?.requirement || {}, summary: state.pendingSelection?.summary || "", parts };
  const data = await api("/api/agent/selection/confirm", { method: "POST", body: JSON.stringify(payload) });
  state.selectedParts = data.selected_parts || parts;
  state.recommendedParts = [];
  closeConfirmModal();
  renderPartHints();
  await loadMessages();
}

qs("#navAgent").onclick = () => setPage("agent");
qs("#navLibrary").onclick = () => setPage("library");
qs("#refreshProjects").onclick = () => loadProjects().catch((error) => alert(error.message));
qs("#refreshInventory").onclick = () => loadInventory().catch((error) => alert(error.message));
qs("#refreshReservations").onclick = () => loadReservations().catch((error) => alert(error.message));
qs("#createProject").onclick = () => createProject().catch((error) => alert(error.message));
qs("#sendDiscuss").onclick = () => sendDiscuss().catch((error) => alert(error.message));
qs("#messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendDiscuss().catch((error) => alert(error.message));
});
qs("#usePlan").onclick = () => openConfirmModal();
qs("#closeModal").onclick = () => closeConfirmModal();
qs("#finalConfirm").onclick = () => confirmSelection().catch((error) => alert(error.message));
qs("#uploadDatasheet").onclick = () => uploadDatasheet().catch((error) => alert(error.message));
qs("#commitDatasheet").onclick = () => commitDatasheet().catch((error) => alert(error.message));
qs("#refreshKnowledge").onclick = () => loadKnowledgeDocs().catch((error) => alert(error.message));

Promise.all([loadProjects(), loadInventory(), loadReservations(), loadKnowledgeDocs(), loadModelStatus()])
  .then(() => Promise.all([loadMessages(), loadSelectedParts()]))
  .catch((error) => alert(error.message));
