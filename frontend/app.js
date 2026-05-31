const holoCanvas = document.querySelector("#holoCanvas");
const transcript = document.querySelector("#transcript");
const commandForm = document.querySelector("#commandForm");
const commandInput = document.querySelector("#commandInput");
const modeValue = document.querySelector("#modeValue");
const toneValue = document.querySelector("#toneValue");
const queueValue = document.querySelector("#queueValue");
const voiceValue = document.querySelector("#voiceValue");
const controlValue = document.querySelector("#controlValue");
const micVisualizer = document.querySelector("#micVisualizer");
const micBars = [...document.querySelectorAll("#micVisualizer span")];
const reactor = document.querySelector(".reactor");
const clearChat = document.querySelector("#clearChat");
const muteSpeech = document.querySelector("#muteSpeech");
const interruptSpeech = document.querySelector("#interruptSpeech");
const voiceToggle = document.querySelector("#voiceToggle");
const browserMicToggle = document.querySelector("#browserMicToggle");
const micDeviceSelect = document.querySelector("#micDeviceSelect");
const toneButtons = [...document.querySelectorAll("[data-tone]")];
const assistantName = document.querySelector("#assistantName");
const assistantAcronym = document.querySelector("#assistantAcronym");
const matrixRain = document.querySelector("#matrixRain");
const fileUploadButton = document.querySelector("#fileUploadButton");
const fileInput = document.querySelector("#fileInput");
const filePreview = document.querySelector("#filePreview");
const filePreviewName = document.querySelector("#filePreviewName");
const filePreviewMeta = document.querySelector("#filePreviewMeta");
const filePreviewClear = document.querySelector("#filePreviewClear");
const todoList = document.querySelector("#todoList");
const todoCount = document.querySelector("#todoCount");
const clearTasks = document.querySelector("#clearTasks");

let lastEventId = 0;
let silentTTS = false;
let cachedStatus = null;
let lastStatusRefreshAt = 0;
let statusRefreshPromise = null;
let browserGreetingRequested = false;
let browserMicRunning = false;
let browserWakeActive = false;
let browserVoiceMode = "wake";
let browserVoiceStatus = "Asleep - say Friday";
let browserWakeTimer = 0;
let browserSttPending = false;
let queuedBrowserBlob = null;
let browserUtteranceCount = 0;
let browserTextCount = 0;
let browserLastLevel = 0;
let browserLastNoticeAt = 0;
let browserSilenceTimer = 0;
let selectedMicDeviceId = "";
let mediaRecorder = null;
let wakeChunks = [];
let wakeCaptureMode = "";
let wakeStartedAt = 0;
let wakeLastVoiceAt = 0;
let wakeHeardVoice = false;
let discardWakeCapture = false;
let commandRecorder = null;
let commandChunks = [];
let commandStartedAt = 0;
let commandLastVoiceAt = 0;
let commandHeardVoice = false;
let commandSilenceFrame = 0;
let returningIdleTimer = 0;
let lastDirectAssistantResponseText = "";
let lastDirectAssistantResponseAt = 0;
let lastAssistantSpeechText = "";
let lastAssistantSpeechAt = 0;
let speechMonitorToken = 0;
let mediaStream = null;
let audioContext = null;
let analyser = null;
let micAnimationFrame = 0;
let ambientNoiseLevel = 0.012;
let selectedUploadFile = null;
let eventPollDelayMs = 250;
let eventStreamPaused = false;
let lastEventStreamWarningAt = 0;
const COMMAND_SILENCE_MS = 2000;
const COMMAND_NO_SPEECH_MS = 9000;
const COMMAND_MAX_MS = 60000;
const WAKE_SILENCE_MS = 1800;
const WAKE_MAX_MS = 30000;
const SPEAKING_INTERRUPT_SILENCE_MS = 550;
const SPEAKING_WAKE_MAX_MS = 4500;
const VOICE_START_MIN_LEVEL = 0.034;
const PURE_SILENCE_MIN_LEVEL = 0.018;
const MIC_ENABLED_KEY = "friday.browserMicEnabled";
const MAX_UPLOAD_BYTES = 120 * 1024 * 1024;
const MAX_VISION_EDGE = 1280;
const VIDEO_FRAME_COUNT = 5;
const WAKE_PATTERN = /\b(?:(?:hey|yo|okay|ok)[\s,;:\-]+)?(?:fri\s*day|jarvis)\b[\s,;:\-]*(.*)$/i;
const INTENTIONAL_COMMAND_PATTERN = /\b(open|launch|start|stop|pause|interrupt|cancel|quiet|mute|close|search|google|look up|what|when|where|who|why|how|tell|show|check|send|write|read|create|run|explain|summarize|set|turn|add|todo|to do|task|done|complete|finish)\b/i;
const MATRIX_STREAM_CHARS = "01FRIDAYCORENETSYSIO<>/{}[]::";

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildMatrixStream(length) {
  let stream = "";
  for (let index = 0; index < length; index += 1) {
    stream += MATRIX_STREAM_CHARS[Math.floor(Math.random() * MATRIX_STREAM_CHARS.length)];
  }
  return stream;
}

function startMatrixRain() {
  if (!matrixRain) {
    return;
  }
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let resizeTimer = 0;
  const build = () => {
    const width = Math.max(320, matrixRain.getBoundingClientRect().width || window.innerWidth);
    const streamCount = prefersReducedMotion ? 10 : Math.min(54, Math.max(22, Math.floor(width / 24)));
    const nodes = [];
    for (let index = 0; index < streamCount; index += 1) {
      const stream = document.createElement("span");
      const length = 10 + Math.floor(Math.random() * 18);
      stream.textContent = buildMatrixStream(length);
      stream.style.setProperty("--x", `${((index + Math.random() * 0.72) / streamCount) * 100}%`);
      stream.style.setProperty("--stream-alpha", (0.1 + Math.random() * 0.16).toFixed(2));
      stream.style.setProperty("--stream-size", `${10 + Math.random() * 4}px`);
      stream.style.setProperty("--stream-duration", `${7.5 + Math.random() * 8.5}s`);
      stream.style.setProperty("--stream-delay", `${-Math.random() * 11}s`);
      nodes.push(stream);
    }
    matrixRain.replaceChildren(...nodes);
  };
  build();
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(build, 220);
  });
}

function startHologramCanvas() {
  if (!holoCanvas) {
    return;
  }
  const context = holoCanvas.getContext("2d", { alpha: true });
  if (!context) {
    return;
  }
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const particles = [];
  const dataStreaks = [];
  const matrixColumns = [];
  const matrixGlyphs = "01FRIDAYSYSCORENETIO<>/{}[]::";
  let width = 0;
  let height = 0;
  let animationFrame = 0;

  const buildMatrixText = (length) => {
    let text = "";
    for (let index = 0; index < length; index += 1) {
      text += matrixGlyphs[Math.floor(Math.random() * matrixGlyphs.length)];
    }
    return text;
  };

  const resize = () => {
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    holoCanvas.width = Math.floor(width * scale);
    holoCanvas.height = Math.floor(height * scale);
    holoCanvas.style.width = `${width}px`;
    holoCanvas.style.height = `${height}px`;
    context.setTransform(scale, 0, 0, scale, 0, 0);
    particles.length = 0;
    dataStreaks.length = 0;
    matrixColumns.length = 0;
    const count = prefersReducedMotion ? 28 : Math.min(120, Math.max(56, Math.floor((width * height) / 17000)));
    for (let index = 0; index < count; index += 1) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.34,
        vy: (Math.random() - 0.5) * 0.28,
        size: 0.8 + Math.random() * 1.8,
        phase: Math.random() * Math.PI * 2,
      });
    }
    const laneCount = prefersReducedMotion ? 3 : Math.min(12, Math.max(6, Math.floor(height / 92)));
    for (let index = 0; index < laneCount; index += 1) {
      dataStreaks.push({
        x: Math.random() * width,
        y: 44 + Math.random() * Math.max(1, height - 88),
        length: 70 + Math.random() * 170,
        speed: 0.8 + Math.random() * 1.65,
        alpha: 0.07 + Math.random() * 0.12,
      });
    }
    const rainCount = prefersReducedMotion ? 7 : Math.min(44, Math.max(16, Math.floor(width / 38)));
    for (let index = 0; index < rainCount; index += 1) {
      const length = 7 + Math.floor(Math.random() * 14);
      matrixColumns.push({
        x: (index + Math.random() * 0.65) * (width / rainCount),
        y: -Math.random() * height,
        speed: 0.55 + Math.random() * 1.25,
        fontSize: 11 + Math.random() * 4,
        length,
        alpha: 0.035 + Math.random() * 0.055,
        glyphs: buildMatrixText(length),
        nextShuffle: Math.random() * 900,
      });
    }
  };

  const draw = (time) => {
    context.clearRect(0, 0, width, height);
    context.save();
    context.globalCompositeOperation = "lighter";
    context.textAlign = "center";
    context.textBaseline = "top";
    for (const column of matrixColumns) {
      column.y += column.speed;
      if (time > column.nextShuffle) {
        column.glyphs = buildMatrixText(column.length);
        column.nextShuffle = time + 160 + Math.random() * 360;
      }
      if (column.y - column.length * column.fontSize > height + 40) {
        column.y = -column.length * column.fontSize - Math.random() * height * 0.45;
        column.x += (Math.random() - 0.5) * 18;
        if (column.x < 0) column.x = width + column.x;
        if (column.x > width) column.x -= width;
      }
      context.font = `${column.fontSize}px "SFMono-Regular", Consolas, "Liberation Mono", monospace`;
      for (let index = 0; index < column.glyphs.length; index += 1) {
        const depth = 1 - index / column.glyphs.length;
        const char = column.glyphs[index];
        const alpha = column.alpha * (0.24 + depth * 1.8);
        context.fillStyle = index === 0
          ? `rgba(255, 244, 214, ${Math.min(alpha * 1.8, 0.24)})`
          : `rgba(64, 190, 255, ${Math.min(alpha, 0.17)})`;
        context.fillText(char, column.x, column.y - index * column.fontSize * 1.18);
      }
    }
    for (const particle of particles) {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.phase += 0.018;
      if (particle.x < -20) particle.x = width + 20;
      if (particle.x > width + 20) particle.x = -20;
      if (particle.y < -20) particle.y = height + 20;
      if (particle.y > height + 20) particle.y = -20;
      const pulse = 0.45 + Math.sin(particle.phase) * 0.25;
      context.fillStyle = `rgba(255, 178, 74, ${0.2 + pulse * 0.32})`;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.size + pulse, 0, Math.PI * 2);
      context.fill();
    }
    for (let index = 0; index < particles.length; index += 1) {
      const a = particles[index];
      for (let next = index + 1; next < particles.length; next += 1) {
        const b = particles[next];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distance = Math.hypot(dx, dy);
        if (distance < 112) {
          context.strokeStyle = `rgba(64, 190, 255, ${0.12 * (1 - distance / 112)})`;
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
          context.stroke();
        }
      }
    }
    for (const streak of dataStreaks) {
      streak.x += streak.speed;
      if (streak.x > width + streak.length + 40) {
        streak.x = -streak.length - 40;
        streak.y = 44 + Math.random() * Math.max(1, height - 88);
      }
      const line = context.createLinearGradient(streak.x - streak.length, streak.y, streak.x, streak.y);
      line.addColorStop(0, "rgba(255, 178, 74, 0)");
      line.addColorStop(0.18, `rgba(255, 178, 74, ${streak.alpha})`);
      line.addColorStop(0.72, `rgba(64, 190, 255, ${streak.alpha * 1.25})`);
      line.addColorStop(1, "rgba(255, 244, 214, 0)");
      context.strokeStyle = line;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(streak.x - streak.length, streak.y);
      context.lineTo(streak.x, streak.y);
      context.stroke();
    }
    const sweepX = ((time / 36) % (width + 240)) - 120;
    const gradient = context.createLinearGradient(sweepX - 90, 0, sweepX + 90, height);
    gradient.addColorStop(0, "rgba(255, 178, 74, 0)");
    gradient.addColorStop(0.5, "rgba(255, 178, 74, 0.14)");
    gradient.addColorStop(1, "rgba(64, 190, 255, 0)");
    context.strokeStyle = gradient;
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(sweepX, 0);
    context.lineTo(sweepX + 120, height);
    context.stroke();
    context.restore();
    if (!prefersReducedMotion) {
      animationFrame = window.requestAnimationFrame(draw);
    }
  };

  window.addEventListener("resize", resize);
  resize();
  animationFrame = window.requestAnimationFrame(draw);
  window.addEventListener("pagehide", () => window.cancelAnimationFrame(animationFrame), { once: true });
}

function addMessage(role, text, variant = "") {
  const node = document.createElement("article");
  node.className = `message ${variant || role}`;
  const label = document.createElement("strong");
  label.textContent = role;
  const body = document.createElement("div");
  body.className = "message-body";
  body.append(renderMessageContent(text));
  node.append(label, body);
  transcript.append(node);
  transcript.scrollTop = transcript.scrollHeight;
  return node;
}

function addTypingIndicator(role = "FRIDAY") {
  const node = document.createElement("article");
  node.className = `message ${role} typing`;
  const label = document.createElement("strong");
  label.textContent = role;
  const body = document.createElement("div");
  body.className = "message-body typing-dots";
  body.innerHTML = '<span></span><span></span><span></span>';
  node.append(label, body);
  transcript.append(node);
  transcript.scrollTop = transcript.scrollHeight;
  return node;
}

function removeNode(node) {
  if (node && node.parentNode) {
    node.parentNode.removeChild(node);
  }
}

// ------------------------------------------------------------------
// Phone-call event rendering
// ------------------------------------------------------------------

const phoneCallCards = new Map(); // call_id -> { node, statusNode, turnsNode, footerNode }

function renderPhoneCallPlanned(payload) {
  if (!payload || !payload.call_id) return;
  // Remove a stale card if FRIDAY restarted mid-call.
  closePhoneCallCard(payload.call_id);

  const node = document.createElement("article");
  node.className = "message system phone-call";
  node.dataset.callId = payload.call_id;

  const label = document.createElement("strong");
  label.textContent = "PHONE";
  node.append(label);

  const headline = document.createElement("div");
  headline.className = "message-body";
  const name = payload.recipient_name || "(unknown recipient)";
  const number = payload.recipient_number_masked || "";
  const objective = payload.objective || "";
  headline.innerHTML = `📞 Calling <strong>${escapeHTML(name)}</strong>${number ? ` (${escapeHTML(number)})` : ""}<br><small>${escapeHTML(objective)}</small>`;
  node.append(headline);

  const statusNode = document.createElement("div");
  statusNode.className = "phone-call-status";
  statusNode.textContent = "Dialing...";
  node.append(statusNode);

  const turnsNode = document.createElement("div");
  turnsNode.className = "phone-call-turns";
  node.append(turnsNode);

  const footerNode = document.createElement("div");
  footerNode.className = "phone-call-footer";
  node.append(footerNode);

  transcript.append(node);
  transcript.scrollTop = transcript.scrollHeight;
  phoneCallCards.set(payload.call_id, { node, statusNode, turnsNode, footerNode });
}

function updatePhoneCallStatus(payload) {
  if (!payload || !payload.call_id) return;
  const card = phoneCallCards.get(payload.call_id);
  if (!card) return;
  const labels = {
    dialing: "Dialing...",
    ringing: "Ringing...",
    connected: "Connected",
    talking: "Talking",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  const status = String(payload.status || "").toLowerCase();
  card.statusNode.textContent = labels[status] || status || "In progress";
  card.statusNode.dataset.status = status;
}

function appendPhoneCallTurn(payload) {
  if (!payload || !payload.call_id) return;
  const card = phoneCallCards.get(payload.call_id);
  if (!card) return;
  const speaker = String(payload.speaker || "system").toLowerCase();
  const text = String(payload.text || "");
  if (!text) return;
  const line = document.createElement("div");
  line.className = `phone-call-turn phone-call-turn--${speaker}`;
  const speakerLabel = speaker === "friday" ? "FRIDAY" : speaker === "recipient" ? "Recipient" : "System";
  line.innerHTML = `<strong>${escapeHTML(speakerLabel)}:</strong> ${escapeHTML(text)}`;
  card.turnsNode.append(line);
  transcript.scrollTop = transcript.scrollHeight;
}

function finalisePhoneCall(payload, kind) {
  if (!payload || !payload.call_id) return;
  const card = phoneCallCards.get(payload.call_id);
  if (!card) return;
  card.statusNode.textContent = kind === "completed" ? "Completed" : "Failed";
  card.statusNode.dataset.status = kind;
  const summary = String(payload.summary || "").trim();
  const outcome = String(payload.outcome || "").trim();
  const followUps = Array.isArray(payload.follow_ups) ? payload.follow_ups : [];

  const parts = [];
  if (summary) parts.push(`<strong>Summary:</strong> ${escapeHTML(summary)}`);
  if (outcome) parts.push(`<strong>Outcome:</strong> ${escapeHTML(outcome)}`);
  if (followUps.length) {
    parts.push(`<strong>Follow-ups:</strong><ul>${followUps.map((item) => `<li>${escapeHTML(String(item))}</li>`).join("")}</ul>`);
  }
  if (payload.error) parts.push(`<strong>Error:</strong> ${escapeHTML(String(payload.error))}`);
  card.footerNode.innerHTML = parts.join("<br>");
  transcript.scrollTop = transcript.scrollHeight;
  // Keep the card around so the user can read it; drop the cache entry.
  phoneCallCards.delete(payload.call_id);
}

function closePhoneCallCard(callId) {
  const card = phoneCallCards.get(callId);
  if (!card) return;
  phoneCallCards.delete(callId);
  removeNode(card.node);
}

function escapeHTML(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function splitTableRow(line) {
  const trimmed = line.trim();
  const clean = trimmed.startsWith("|") && trimmed.endsWith("|")
    ? trimmed.slice(1, -1)
    : trimmed;
  return clean.split("|").map((cell) => cell.trim());
}

function isTableSeparator(line) {
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isTableRow(line) {
  return line.includes("|") && splitTableRow(line).length > 1;
}

function renderMessageContent(text) {
  const fragment = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  const isListLine = (line) => /^\s*(?:[-*]\s+|\d+\.\s+)/.test(line);
  const isHorizontalRule = (line) => /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
  const isTableStart = (at) => at + 1 < lines.length && isTableRow(lines[at]) && isTableSeparator(lines[at + 1]);
  const isBlockStart = (line) => {
    const trimmed = line.trim();
    return !trimmed || trimmed.startsWith("```") || trimmed.startsWith("#") || trimmed.startsWith(">") || isHorizontalRule(line) || isListLine(line);
  };

  const appendInline = (parent, value) => {
    let cursor = 0;
    while (cursor < value.length) {
      const markers = [
        { type: "code", at: value.indexOf("`", cursor) },
        { type: "bold", at: value.indexOf("**", cursor) },
        { type: "link", at: value.indexOf("[", cursor) }
      ].filter((marker) => marker.at >= 0).sort((a, b) => a.at - b.at);
      const next = markers[0];
      if (!next) {
        parent.append(document.createTextNode(value.slice(cursor)));
        break;
      }
      if (next.at > cursor) {
        parent.append(document.createTextNode(value.slice(cursor, next.at)));
      }
      if (next.type === "code") {
        const end = value.indexOf("`", next.at + 1);
        if (end === -1) {
          parent.append(document.createTextNode(value.slice(next.at)));
          break;
        }
        const code = document.createElement("code");
        code.textContent = value.slice(next.at + 1, end);
        parent.append(code);
        cursor = end + 1;
        continue;
      }
      if (next.type === "bold") {
        const end = value.indexOf("**", next.at + 2);
        if (end === -1) {
          parent.append(document.createTextNode(value.slice(next.at, next.at + 2)));
          cursor = next.at + 2;
          continue;
        }
        const strong = document.createElement("strong");
        appendInline(strong, value.slice(next.at + 2, end));
        parent.append(strong);
        cursor = end + 2;
        continue;
      }
      const linkMatch = value.slice(next.at).match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/i);
      if (!linkMatch) {
        parent.append(document.createTextNode(value[next.at]));
        cursor = next.at + 1;
        continue;
      }
      const anchor = document.createElement("a");
      anchor.href = linkMatch[2];
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
      appendInline(anchor, linkMatch[1]);
      parent.append(anchor);
      cursor = next.at + linkMatch[0].length;
    }
  };

  const appendCodeBlock = (language, codeLines) => {
    const wrapper = document.createElement("div");
    wrapper.className = "code-block";
    const header = document.createElement("div");
    header.className = "code-block-header";
    const label = document.createElement("span");
    label.textContent = language ? language.toUpperCase() : "CODE";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(codeLines.join("\n"));
        copy.textContent = "Copied";
        window.setTimeout(() => {
          copy.textContent = "Copy";
        }, 1200);
      } catch {
        copy.textContent = "Blocked";
        window.setTimeout(() => {
          copy.textContent = "Copy";
        }, 1200);
      }
    });
    header.append(label, copy);
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    if (language) {
      code.className = `language-${language.replace(/[^a-z0-9_-]/gi, "")}`;
    }
    code.textContent = codeLines.join("\n");
    pre.append(code);
    wrapper.append(header, pre);
    fragment.append(wrapper);
  };

  const appendParagraph = (paragraphLines) => {
    const paragraph = document.createElement("p");
    appendInline(paragraph, paragraphLines.join(" ").trim());
    fragment.append(paragraph);
  };

  const appendTable = () => {
    const headers = splitTableRow(lines[index]);
    index += 2;
    const rows = [];
    while (index < lines.length && isTableRow(lines[index]) && lines[index].trim()) {
      rows.push(splitTableRow(lines[index]));
      index += 1;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach((header) => {
      const cell = document.createElement("th");
      appendInline(cell, header);
      headRow.append(cell);
    });
    thead.append(headRow);
    table.append(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tableRow = document.createElement("tr");
      headers.forEach((_, cellIndex) => {
        const cell = document.createElement("td");
        appendInline(cell, row[cellIndex] || "");
        tableRow.append(cell);
      });
      tbody.append(tableRow);
    });
    table.append(tbody);
    wrapper.append(table);
    fragment.append(wrapper);
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.replace(/^```/, "").trim().split(/\s+/)[0] || "";
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      appendCodeBlock(language, codeLines);
      continue;
    }

    if (isHorizontalRule(line)) {
      fragment.append(document.createElement("hr"));
      index += 1;
      continue;
    }

    if (isTableStart(index)) {
      appendTable();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      const heading = document.createElement(headingMatch[1].length === 1 ? "h3" : "h4");
      appendInline(heading, headingMatch[2]);
      fragment.append(heading);
      index += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quote = document.createElement("blockquote");
      const quoteLines = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      appendInline(quote, quoteLines.join(" "));
      fragment.append(quote);
      continue;
    }

    if (isListLine(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length && isListLine(lines[index]) && /^\s*\d+\.\s+/.test(lines[index]) === ordered) {
        const item = document.createElement("li");
        appendInline(item, lines[index].replace(/^\s*(?:[-*]\s+|\d+\.\s+)/, ""));
        list.append(item);
        index += 1;
      }
      fragment.append(list);
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length && !isBlockStart(lines[index]) && !isTableStart(index)) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    appendParagraph(paragraphLines);
  }

  if (!fragment.childNodes.length) {
    const empty = document.createElement("p");
    empty.textContent = "";
    fragment.append(empty);
  }
  return fragment;
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function setSelectedUploadFile(file) {
  if (!file) {
    return;
  }
  if (!/^image\/|^video\//.test(file.type || "")) {
    addMessage("FRIDAY", "I can analyze screenshots, images, and videos only right now.", "error");
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    addMessage("FRIDAY", "That upload is too large. Try a shorter video clip or a smaller screenshot.", "error");
    return;
  }
  selectedUploadFile = file;
  if (filePreview && filePreviewName && filePreviewMeta) {
    filePreview.hidden = false;
    filePreviewName.textContent = file.name || "Visual upload";
    filePreviewMeta.textContent = `${file.type || "visual file"} · ${formatBytes(file.size)}`;
  }
}

function clearSelectedUpload() {
  selectedUploadFile = null;
  if (fileInput) {
    fileInput.value = "";
  }
  if (filePreview) {
    filePreview.hidden = true;
  }
}

function drawScaledFrame(source, sourceWidth, sourceHeight) {
  const scale = Math.min(1, MAX_VISION_EDGE / Math.max(sourceWidth || 1, sourceHeight || 1));
  const width = Math.max(1, Math.round((sourceWidth || 1) * scale));
  const height = Math.max(1, Math.round((sourceHeight || 1) * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { alpha: false });
  context.drawImage(source, 0, 0, width, height);
  return canvas.toDataURL("image/jpeg", 0.86);
}

async function imageFileToDataUrl(file) {
  if ("createImageBitmap" in window) {
    const bitmap = await createImageBitmap(file);
    const dataUrl = drawScaledFrame(bitmap, bitmap.width, bitmap.height);
    if (bitmap.close) {
      bitmap.close();
    }
    return dataUrl;
  }
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.decoding = "async";
    image.src = objectUrl;
    await image.decode();
    return drawScaledFrame(image, image.naturalWidth, image.naturalHeight);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function waitForVideoEvent(video, eventName) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      video.removeEventListener(eventName, handleEvent);
      video.removeEventListener("error", handleError);
    };
    const handleEvent = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error("Video could not be decoded by the browser."));
    };
    video.addEventListener(eventName, handleEvent, { once: true });
    video.addEventListener("error", handleError, { once: true });
  });
}

async function seekVideo(video, time) {
  const target = Math.max(0, Math.min(time, Math.max(0, (video.duration || 0) - 0.08)));
  if (Math.abs((video.currentTime || 0) - target) < 0.04) {
    return;
  }
  const promise = waitForVideoEvent(video, "seeked");
  video.currentTime = target;
  await promise;
}

async function videoFileToFrames(file) {
  const objectUrl = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "metadata";
  video.src = objectUrl;
  try {
    await waitForVideoEvent(video, "loadedmetadata");
    if (!video.videoWidth || !video.videoHeight) {
      await waitForVideoEvent(video, "loadeddata");
    }
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 1;
    const rawTimes = duration <= 1
      ? [0]
      : [0.2, duration * 0.22, duration * 0.5, duration * 0.78, Math.max(0, duration - 0.25)];
    const uniqueTimes = [...new Set(rawTimes.map((time) => Number(time.toFixed(2))))].slice(0, VIDEO_FRAME_COUNT);
    const frames = [];
    const labels = [];
    for (const time of uniqueTimes) {
      await seekVideo(video, time);
      frames.push(drawScaledFrame(video, video.videoWidth, video.videoHeight));
      labels.push(`${time.toFixed(1)}s`);
    }
    return { frames, labels };
  } finally {
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(objectUrl);
  }
}

async function buildUploadPayload(file, prompt) {
  if ((file.type || "").startsWith("image/")) {
    return {
      file_name: file.name || "screenshot",
      mime_type: file.type || "image/jpeg",
      size: file.size,
      prompt: prompt || "Analyze this screenshot or image.",
      image_data_urls: [await imageFileToDataUrl(file)],
      frame_labels: ["image"],
    };
  }
  if ((file.type || "").startsWith("video/")) {
    const { frames, labels } = await videoFileToFrames(file);
    return {
      file_name: file.name || "video",
      mime_type: file.type || "video/mp4",
      size: file.size,
      prompt: prompt || "Analyze this video and summarize what is visible.",
      image_data_urls: frames,
      frame_labels: labels,
    };
  }
  throw new Error("Unsupported file type.");
}

async function clearVisibleChat() {
  transcript.replaceChildren();
  try {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 800);
    const response = await fetch("/api/events?since=0", { signal: controller.signal });
    window.clearTimeout(timeout);
    const payload = await response.json();
    if (payload.events && payload.events.length) {
      lastEventId = Math.max(...payload.events.map((event) => Number(event.id) || 0));
    }
  } catch (error) {
    return;
  }
}

function updateToneButtons(tone) {
  toneButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tone === tone);
  });
}

function displayMode(mode) {
  return mode === "active" ? "Active" : "Asleep";
}

function passiveVoiceLabel(voiceRunning, voiceLoaded, listeningForCommand) {
  if (listeningForCommand) {
    return "Listening for command";
  }
  if (!voiceRunning) {
    return "Off";
  }
  return voiceLoaded ? "Asleep - say Friday" : "Loading";
}

function displayControlStatus(status) {
  const clean = String(status || "idle").replace(/[_-]/g, " ").trim();
  return clean ? clean.replace(/\b\w/g, (letter) => letter.toUpperCase()) : "Idle";
}

function formatTodoDue(value) {
  if (!value) {
    return "";
  }
  const due = new Date(value);
  if (Number.isNaN(due.getTime())) {
    return value;
  }
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const timeText = due.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (sameDay(due, now)) {
    return `Today ${timeText}`;
  }
  if (sameDay(due, tomorrow)) {
    return `Tomorrow ${timeText}`;
  }
  return `${due.toLocaleDateString([], { month: "short", day: "numeric" })} ${timeText}`;
}

function formatTodoLimit(minutes) {
  const value = Number(minutes);
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  if (value < 60) {
    return `${value}m`;
  }
  const hours = Math.floor(value / 60);
  const mins = value % 60;
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function renderTodos(todoPayload) {
  if (!todoList || !todoCount) {
    return;
  }
  const active = todoPayload && Array.isArray(todoPayload.active) ? todoPayload.active : [];
  todoCount.textContent = String(active.length);
  if (!active.length) {
    const empty = document.createElement("li");
    empty.className = "todo-empty";
    empty.textContent = "No active tasks";
    todoList.replaceChildren(empty);
    return;
  }
  const nodes = active.slice(0, 6).map((task) => {
    const item = document.createElement("li");
    const title = document.createElement("span");
    title.className = "todo-title";
    title.textContent = task.title || "Untitled task";
    item.append(title);
    const metaBits = [];
    const due = formatTodoDue(task.due_at);
    if (due) metaBits.push(due);
    const limit = formatTodoLimit(task.time_limit_minutes);
    if (limit) metaBits.push(`${limit} limit`);
    if (metaBits.length) {
      const meta = document.createElement("small");
      meta.textContent = metaBits.join(" • ");
      item.append(meta);
    }
    return item;
  });
  todoList.replaceChildren(...nodes);
}

async function refreshStatus(force = false) {
  const now = Date.now();
  if (!force && cachedStatus && now - lastStatusRefreshAt < 350) {
    return cachedStatus;
  }
  if (statusRefreshPromise) {
    return statusRefreshPromise;
  }
  statusRefreshPromise = (async () => {
    try {
      const response = await fetch("/api/status");
      const status = await response.json();
      cachedStatus = status;
      lastStatusRefreshAt = Date.now();
      const mode = status.state.mode;
      const tone = status.state.tone;
      const personaTone = status.personality && status.personality.tone ? status.personality.tone : tone;
      if (assistantName && status.name) {
        assistantName.textContent = status.name;
        document.title = status.name;
      }
      if (assistantAcronym && status.full_name) {
        assistantAcronym.textContent = status.full_name;
      }
      modeValue.textContent = displayMode(mode);
      toneValue.textContent = personaTone.split(/[_-]/).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
      queueValue.textContent = String(status.queue_depth);
      const voiceRunning = status.voice && status.voice.running;
      const voiceLoaded = status.voice && status.voice.model_loaded;
      const listeningForCommand = status.voice && status.voice.listening_for_command;
      voiceValue.textContent = browserMicRunning ? browserVoiceStatus : passiveVoiceLabel(voiceRunning, voiceLoaded, listeningForCommand);
      const controlStatus = status.control && status.control.status ? status.control.status : "idle";
      if (controlValue) {
        controlValue.textContent = displayControlStatus(controlStatus);
      }
      renderTodos(status.todos);
      voiceToggle.textContent = voiceRunning ? "Voice On" : "Voice";
      browserMicToggle.textContent = browserMicRunning ? "Chrome On" : "Chrome Mic";
      browserMicToggle.classList.toggle("active", browserMicRunning);
      silentTTS = status.tts.silent;
      muteSpeech.textContent = silentTTS ? "Silent" : "TTS";
      const isListening = Boolean(voiceRunning || browserMicRunning);
      const isSpeaking = Boolean(status.tts && status.tts.speaking);
      micVisualizer.classList.toggle("listening", isListening);
      micVisualizer.classList.toggle("speaking", isSpeaking);
      document.body.classList.toggle("is-listening", isListening);
      document.body.classList.toggle("is-speaking", isSpeaking);
      document.body.classList.toggle("is-controlling", ["planning", "waiting for confirmation", "controlling browser", "controlling desktop"].includes(controlStatus));
      document.body.classList.toggle("is-stopped", controlStatus === "stopped");
      if (reactor) {
        reactor.classList.toggle("is-listening", isListening);
        reactor.classList.toggle("is-speaking", isSpeaking);
      }
      if (isSpeaking && browserLastLevel < 0.08) {
        setHudVoiceLevel(0.46);
      }
      updateToneButtons(tone);
      return status;
    } finally {
      statusRefreshPromise = null;
    }
  })();
  return statusRefreshPromise;
}

function setBrowserVoiceStatus(status) {
  browserVoiceStatus = status;
  if (browserMicRunning) {
    voiceValue.textContent = status;
  }
}

function updateMicLevel(level) {
  const safeLevel = Math.max(0, Math.min(Number(level) || 0, 1));
  setHudVoiceLevel(safeLevel);
  micBars.forEach((bar, index) => {
    const wave = Math.abs(2 - index) / 2;
    const height = 8 + safeLevel * (32 - wave * 10);
    bar.style.height = `${height}px`;
    bar.style.opacity = String(0.42 + safeLevel * 0.58);
  });
}

function setHudVoiceLevel(level) {
  const safeLevel = Math.max(0, Math.min(Number(level) || 0, 1));
  const hasVoiceActivity = safeLevel > 0.045;
  document.documentElement.style.setProperty("--voice-level", safeLevel.toFixed(3));
  document.body.classList.toggle("has-voice-activity", hasVoiceActivity);
  if (reactor) {
    reactor.style.setProperty("--voice-level", safeLevel.toFixed(3));
    reactor.classList.toggle("has-voice-activity", hasVoiceActivity);
  }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(value, max));
}

function speechStartThreshold() {
  return clamp(ambientNoiseLevel + 0.045, VOICE_START_MIN_LEVEL, 0.16);
}

function pureSilenceThreshold() {
  return clamp(ambientNoiseLevel + 0.02, PURE_SILENCE_MIN_LEVEL, 0.085);
}

function updateAmbientNoise(level) {
  if (mediaRecorder || commandRecorder || browserVoiceMode === "processing") {
    return;
  }
  if (level < 0.22) {
    ambientNoiseLevel = ambientNoiseLevel * 0.96 + level * 0.04;
  }
}

function noteBrowserStt(message, force = false) {
  const now = Date.now();
  if (!force && now - browserLastNoticeAt < 6500) {
    return;
  }
  browserLastNoticeAt = now;
  addMessage("STT", message, "system");
}

function getAudioConstraints() {
  const audio = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: { ideal: 1 },
    sampleRate: { ideal: 48000 },
    sampleSize: { ideal: 16 },
    latency: { ideal: 0.04 },
  };
  if (selectedMicDeviceId) {
    audio.deviceId = { exact: selectedMicDeviceId };
  }
  return { audio };
}

function createMediaRecorder(stream) {
  const preferredType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
  const highQualityOptions = {
    audioBitsPerSecond: 128000,
  };
  if (preferredType) {
    highQualityOptions.mimeType = preferredType;
  }
  try {
    return new MediaRecorder(stream, highQualityOptions);
  } catch (error) {
    return preferredType ? new MediaRecorder(stream, { mimeType: preferredType }) : new MediaRecorder(stream);
  }
}

function commandAfterWake(text) {
  const cleanText = text.trim();
  const match = cleanText.match(WAKE_PATTERN);
  if (match) {
    return match[1].trim();
  }
  return cleanText.replace(/\b(?:(?:hey|yo|okay|ok)[\s,;:\-]+)?(?:fri\s*day|jarvis)\b[\s,;:\-]*/i, "").trim();
}

function normalizeSpeechText(text) {
  return text.toLowerCase().replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
}

function isInterruptCommand(command) {
  return /\b(stop|stopped|stop it|stop now|stop talking|stop speaking|stahp|interrupt|cancel|abort|never ?mind|go idle|stop listening|sleep friday|quiet|be quiet|mute|pause|enough|that'?s enough|hold on|shut up|cut it|cut off|silence|hush|shush|quit talking)\b/i.test(command);
}

function isSessionStopPhrase(text) {
  return /\b(thanks friday|thank you friday|appreciate it friday|that'?s all friday|that is all friday|you'?re good friday|youre good friday|good night friday|night friday|sleep friday|go idle|go idle friday|stop listening|stop listening friday|never ?mind|cancel|abort)\b/i.test(text);
}

function looksLikeAssistantEcho(transcript, command) {
  if (browserVoiceMode !== "speaking") {
    return false;
  }
  const recentSpeech = Date.now() - lastAssistantSpeechAt < 30000;
  if (!recentSpeech) {
    return false;
  }
  const cleanTranscript = normalizeSpeechText(transcript);
  const cleanCommand = normalizeSpeechText(command);
  const cleanAssistant = normalizeSpeechText(lastAssistantSpeechText);
  if (!cleanCommand) {
    return true;
  }
  if (isInterruptCommand(cleanCommand)) {
    return false;
  }
  if (INTENTIONAL_COMMAND_PATTERN.test(cleanCommand)) {
    return false;
  }
  return cleanAssistant.includes(cleanTranscript) || cleanAssistant.includes(cleanCommand);
}

async function refreshMicDevices() {
  if (!micDeviceSelect || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    return;
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((device) => device.kind === "audioinput");
    const currentValue = selectedMicDeviceId || micDeviceSelect.value || "";
    micDeviceSelect.replaceChildren();
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = "Default mic";
    micDeviceSelect.append(defaultOption);
    inputs.forEach((device, index) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Microphone ${index + 1}`;
      micDeviceSelect.append(option);
    });
    if ([...micDeviceSelect.options].some((option) => option.value === currentValue)) {
      micDeviceSelect.value = currentValue;
    }
  } catch (error) {
    noteBrowserStt("Chrome could not list microphones. Check site microphone permission.", true);
  }
}

async function sendMessage(text) {
  addMessage("User", text);
  const typingNode = addTypingIndicator("FRIDAY");
  let response;
  let result;
  try {
    response = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, source: "text" }),
    });
    result = await response.json();
  } catch (networkError) {
    removeNode(typingNode);
    addMessage(
      "FRIDAY",
      `Network error reaching FRIDAY: ${networkError.message || networkError}. Check that the server is running.`,
      "error",
    );
    return;
  }
  removeNode(typingNode);
  if (!response.ok) {
    const friendly = friendlyErrorMessage(result, response.status);
    addMessage("FRIDAY", friendly, "error");
    return;
  }
  addMessage("FRIDAY", result.final_output, "assistant");
  await refreshStatus(true);
}

function friendlyErrorMessage(result, status) {
  const raw = (result && result.error) || "Request failed.";
  const kind = result && result.kind;
  if (kind === "timeout" || status === 504) {
    return `${raw}\n\nThe local model is still warming up. Try the same prompt again — it should be faster the second time.`;
  }
  if (kind === "ollama_unavailable" || status === 503) {
    return `${raw}\n\nMake sure Ollama is running: \`ollama serve\` in a terminal, then retry.`;
  }
  return raw;
}

async function sendUploadMessage(text) {
  const file = selectedUploadFile;
  if (!file) {
    return;
  }
  const prompt = text.trim() || "Analyze this file.";
  addMessage("User", `Uploaded ${file.name || "visual file"} — ${prompt}`);
  if (fileUploadButton) {
    fileUploadButton.disabled = true;
    fileUploadButton.textContent = "Scanning";
  }
  try {
    const payload = await buildUploadPayload(file, prompt);
    addMessage("Vision", `${file.type && file.type.startsWith("video/") ? "Sampled video frames" : "Prepared image"} for Ollama vision analysis.`, "system");
    const response = await fetch("/api/file-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      addMessage("FRIDAY", result.error || "File analysis failed.", "error");
      return;
    }
    if (result.final_output) {
      lastDirectAssistantResponseText = result.final_output;
      lastDirectAssistantResponseAt = Date.now();
      lastAssistantSpeechText = result.final_output;
      lastAssistantSpeechAt = Date.now();
      addMessage("FRIDAY", result.final_output, "assistant");
    }
    clearSelectedUpload();
    await refreshStatus(true);
  } catch (error) {
    addMessage("FRIDAY", error.message || "I could not prepare that upload.", "error");
  } finally {
    if (fileUploadButton) {
      fileUploadButton.disabled = false;
      fileUploadButton.textContent = "Upload";
    }
  }
}

async function sendBrowserVoiceCommand(text) {
  const cleanText = text.trim();
  if (!cleanText) {
    returnToWakeListening();
    return;
  }
  browserVoiceMode = "processing";
  setBrowserVoiceStatus("Processing");
  addMessage("Voice", cleanText);
  const response = await fetch("/api/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: cleanText, source: "browser-voice" }),
  });
  const result = await response.json();
  if (!response.ok) {
    addMessage("FRIDAY", result.error || "Voice request failed.", "error");
    returnToWakeListening();
    return;
  }
  if (result.final_output) {
    lastDirectAssistantResponseText = result.final_output;
    lastDirectAssistantResponseAt = Date.now();
    lastAssistantSpeechText = result.final_output;
    lastAssistantSpeechAt = Date.now();
    addMessage("FRIDAY", result.final_output, "assistant");
  }
  await waitForSpeechThenIdle();
}

async function handleBrowserTranscript(text) {
  const cleanText = text.trim();
  if (!cleanText || !["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  if (browserVoiceMode === "speaking" && (isInterruptCommand(cleanText) || isSessionStopPhrase(cleanText))) {
    speechMonitorToken += 1;
    await fetch("/api/interrupt", { method: "POST" });
    if (isSessionStopPhrase(cleanText)) {
      await sendBrowserVoiceCommand(cleanText);
      return;
    }
    returnToWakeListening();
    refreshStatus();
    return;
  }
  if (browserVoiceMode === "wake" && isSessionStopPhrase(cleanText)) {
    sendBrowserVoiceCommand(cleanText);
    return;
  }
  const wakeMatch = cleanText.match(WAKE_PATTERN);
  if (wakeMatch) {
    const command = wakeMatch[1].trim();
    if (looksLikeAssistantEcho(cleanText, command)) {
      return;
    }
    if (browserVoiceMode === "speaking") {
      speechMonitorToken += 1;
      await fetch("/api/interrupt", { method: "POST" });
      if (isInterruptCommand(command)) {
        returnToWakeListening();
        refreshStatus();
        return;
      }
    }
    browserVoiceMode = "detected";
    browserWakeActive = true;
    setBrowserVoiceStatus("Friday detected");
    window.clearTimeout(browserWakeTimer);
    browserWakeTimer = window.setTimeout(() => {
      if (browserVoiceMode === "detected") {
        returnToWakeListening();
      }
    }, 9000);
    if (command) {
      browserWakeActive = false;
      window.clearTimeout(browserWakeTimer);
      browserVoiceMode = "processing";
      setBrowserVoiceStatus("Processing");
      sendBrowserVoiceCommand(command);
    } else {
      startBrowserCommandCapture();
    }
    refreshStatus();
  }
}

function returnToWakeListening() {
  window.clearTimeout(browserWakeTimer);
  window.clearTimeout(returningIdleTimer);
  browserWakeActive = false;
  browserVoiceMode = "returning";
  setBrowserVoiceStatus("Returning to idle");
  returningIdleTimer = window.setTimeout(() => {
    if (!browserMicRunning) {
      return;
    }
    cancelWakeUtteranceCapture();
    browserVoiceMode = "wake";
    queuedBrowserBlob = null;
    startWakeRecorder();
    setBrowserVoiceStatus("Asleep - say Friday");
    refreshStatus();
  }, 450);
}

async function waitForSpeechThenIdle() {
  const token = ++speechMonitorToken;
  browserVoiceMode = "speaking";
  setBrowserVoiceStatus("Speaking");
  restartWakeRecorderForCurrentMode();
  const startedAt = Date.now();
  let sawSpeaking = false;
  while (browserMicRunning && Date.now() - startedAt < 15000) {
    if (token !== speechMonitorToken) {
      return;
    }
    try {
      const response = await fetch("/api/status");
      const status = await response.json();
      const speaking = Boolean(status.tts && status.tts.speaking);
      if (speaking) {
        sawSpeaking = true;
      }
      if (!speaking && (sawSpeaking || Date.now() - startedAt > 450)) {
        break;
      }
    } catch (error) {
      break;
    }
    await delay(140);
  }
  if (token === speechMonitorToken) {
    returnToWakeListening();
  }
}

async function transcribeBrowserBlob(blob) {
  const response = await fetch("/api/stt", {
    method: "POST",
    headers: {
      "Content-Type": blob.type || "audio/webm",
      "X-Friday-Audio-Level": browserLastLevel.toFixed(3),
    },
    body: blob,
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "Speech transcription failed.");
  }
  return result;
}

async function sendBrowserAudioUtterance(blob) {
  if (!blob || blob.size < 300) {
    return;
  }
  if (!["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  if (browserSttPending) {
    queuedBrowserBlob = blob;
    return;
  }
  await processBrowserAudioUtterance(blob);
  while (queuedBrowserBlob && browserMicRunning) {
    const nextBlob = queuedBrowserBlob;
    queuedBrowserBlob = null;
    await processBrowserAudioUtterance(nextBlob);
  }
}

async function processBrowserAudioUtterance(blob) {
  browserSttPending = true;
  browserUtteranceCount += 1;
  try {
    const result = await transcribeBrowserBlob(blob);
    if (result.text) {
      browserTextCount += 1;
      await handleBrowserTranscript(result.text);
      return;
    }
  } catch (error) {
    addMessage("STT", error.message || "Chrome microphone transcription failed.", "error");
  } finally {
    browserSttPending = false;
  }
}

function startBrowserCommandCapture() {
  if (!browserMicRunning || !mediaStream || browserVoiceMode === "command" || browserVoiceMode === "processing" || browserVoiceMode === "speaking") {
    return;
  }
  window.clearTimeout(browserWakeTimer);
  browserVoiceMode = "command";
  setBrowserVoiceStatus("Listening for command");
  browserWakeActive = true;
  queuedBrowserBlob = null;
  commandChunks = [];
  commandStartedAt = Date.now();
  commandLastVoiceAt = 0;
  commandHeardVoice = false;
  cancelWakeUtteranceCapture();
  commandRecorder = createMediaRecorder(mediaStream);
  commandRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      commandChunks.push(event.data);
    }
  });
  commandRecorder.addEventListener("stop", finalizeBrowserCommandCapture);
  commandRecorder.start();
  monitorCommandSilence();
  refreshStatus();
}

function startWakeRecorder() {
  if (!browserMicRunning || !mediaStream || !["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  driveContinuousWakeCapture();
}

function startWakeUtteranceCapture() {
  if (!browserMicRunning || !mediaStream || mediaRecorder || commandRecorder || !["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  wakeChunks = [];
  wakeCaptureMode = browserVoiceMode;
  wakeStartedAt = Date.now();
  wakeLastVoiceAt = wakeStartedAt;
  wakeHeardVoice = true;
  discardWakeCapture = false;
  mediaRecorder = createMediaRecorder(mediaStream);
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      wakeChunks.push(event.data);
    }
  });
  mediaRecorder.addEventListener("stop", finalizeWakeUtteranceCapture);
  mediaRecorder.addEventListener("error", () => {
    addMessage("STT", "Chrome could not record microphone audio.", "error");
  });
  mediaRecorder.start();
}

function stopWakeUtteranceCapture() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

function cancelWakeUtteranceCapture() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    discardWakeCapture = true;
    mediaRecorder.stop();
    return;
  }
  mediaRecorder = null;
  wakeChunks = [];
  wakeCaptureMode = "";
  wakeStartedAt = 0;
  wakeLastVoiceAt = 0;
  wakeHeardVoice = false;
}

async function finalizeWakeUtteranceCapture() {
  const recorder = mediaRecorder;
  const type = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
  const blob = new Blob(wakeChunks, { type });
  const shouldDiscard = discardWakeCapture;
  const capturedMode = wakeCaptureMode;
  mediaRecorder = null;
  wakeChunks = [];
  wakeCaptureMode = "";
  wakeStartedAt = 0;
  wakeLastVoiceAt = 0;
  wakeHeardVoice = false;
  discardWakeCapture = false;
  if (shouldDiscard || !browserMicRunning || !["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  if (capturedMode === "speaking" && browserVoiceMode !== "speaking") {
    return;
  }
  await sendBrowserAudioUtterance(blob);
}

function driveContinuousWakeCapture() {
  if (!browserMicRunning || !mediaStream || browserSttPending || commandRecorder || !["wake", "speaking"].includes(browserVoiceMode)) {
    return;
  }
  const now = Date.now();
  if (!mediaRecorder) {
    if (browserLastLevel >= speechStartThreshold()) {
      startWakeUtteranceCapture();
    }
    return;
  }
  if (browserLastLevel >= pureSilenceThreshold()) {
    wakeHeardVoice = true;
    wakeLastVoiceAt = now;
  }
  const silenceMs = browserVoiceMode === "speaking" ? SPEAKING_INTERRUPT_SILENCE_MS : WAKE_SILENCE_MS;
  const maxMs = browserVoiceMode === "speaking" ? SPEAKING_WAKE_MAX_MS : WAKE_MAX_MS;
  if (wakeHeardVoice && now - wakeLastVoiceAt >= silenceMs) {
    stopWakeUtteranceCapture();
    return;
  }
  if (now - wakeStartedAt >= maxMs) {
    stopWakeUtteranceCapture();
  }
}

function restartWakeRecorderForCurrentMode() {
  cancelWakeUtteranceCapture();
  startWakeRecorder();
}

function monitorCommandSilence() {
  if (!browserMicRunning || browserVoiceMode !== "command") {
    return;
  }
  const now = Date.now();
  const threshold = commandHeardVoice ? pureSilenceThreshold() : speechStartThreshold();
  if (browserLastLevel >= threshold) {
    commandHeardVoice = true;
    commandLastVoiceAt = now;
  }
  if (commandHeardVoice && now - commandLastVoiceAt >= COMMAND_SILENCE_MS) {
    stopBrowserCommandCapture();
    return;
  }
  if (!commandHeardVoice && now - commandStartedAt >= COMMAND_NO_SPEECH_MS) {
    stopBrowserCommandCapture();
    return;
  }
  if (now - commandStartedAt >= COMMAND_MAX_MS) {
    stopBrowserCommandCapture();
    return;
  }
  commandSilenceFrame = window.requestAnimationFrame(monitorCommandSilence);
}

function stopBrowserCommandCapture() {
  window.cancelAnimationFrame(commandSilenceFrame);
  if (commandRecorder && commandRecorder.state !== "inactive") {
    commandRecorder.stop();
  }
}

async function finalizeBrowserCommandCapture() {
  const type = commandRecorder && commandRecorder.mimeType ? commandRecorder.mimeType : "audio/webm";
  const blob = new Blob(commandChunks, { type });
  if (!browserMicRunning) {
    commandRecorder = null;
    commandChunks = [];
    return;
  }
  browserVoiceMode = "wake";
  browserWakeActive = false;
  window.clearTimeout(browserWakeTimer);
  commandRecorder = null;
  commandChunks = [];
  browserVoiceMode = "processing";
  setBrowserVoiceStatus("Processing");
  await refreshStatus();
  if (!blob || blob.size < 300) {
    returnToWakeListening();
    return;
  }
  try {
    const result = await transcribeBrowserBlob(blob);
    if (result.text) {
      sendBrowserVoiceCommand(commandAfterWake(result.text));
      return;
    }
    returnToWakeListening();
  } catch (error) {
    addMessage("STT", error.message || "Command transcription failed.", "error");
    returnToWakeListening();
  }
}

function startMicLevelLoop() {
  if (!analyser) {
    return;
  }
  const data = new Uint8Array(analyser.fftSize);
  const tick = () => {
    if (!browserMicRunning || !analyser) {
      return;
    }
    analyser.getByteTimeDomainData(data);
    let total = 0;
    let peak = 0;
    for (const value of data) {
      const centered = (value - 128) / 128;
      total += centered * centered;
      peak = Math.max(peak, Math.abs(centered));
    }
    const rms = Math.sqrt(total / data.length);
    browserLastLevel = Math.min(Math.max(rms * 18, peak * 2.4), 1);
    updateAmbientNoise(browserLastLevel);
    updateMicLevel(browserLastLevel);
    driveContinuousWakeCapture();
    micAnimationFrame = window.requestAnimationFrame(tick);
  };
  tick();
}

async function startBrowserMic() {
  if (browserMicRunning) {
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    addMessage("STT", "Chrome microphone capture is not available in this browser.", "error");
    return;
  }
  try {
    selectedMicDeviceId = micDeviceSelect ? micDeviceSelect.value : "";
    mediaStream = await navigator.mediaDevices.getUserMedia(getAudioConstraints());
    const [track] = mediaStream.getAudioTracks();
    if (!track) {
      throw new Error("No microphone track was created.");
    }
    track.addEventListener("mute", () => {
      noteBrowserStt("Chrome says the selected microphone is muted. Pick another mic or check macOS input settings.", true);
    });
    track.addEventListener("ended", () => {
      addMessage("STT", "Chrome microphone stream ended.", "error");
      stopBrowserMic();
    });
    await refreshMicDevices();
    audioContext = new AudioContext();
    await audioContext.resume();
    const source = audioContext.createMediaStreamSource(mediaStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    browserMicRunning = true;
    browserWakeActive = false;
    browserVoiceMode = "wake";
    queuedBrowserBlob = null;
    browserUtteranceCount = 0;
    browserTextCount = 0;
    browserLastLevel = 0;
    browserLastNoticeAt = 0;
    ambientNoiseLevel = 0.012;
    startWakeRecorder();
    startMicLevelLoop();
    window.localStorage.setItem(MIC_ENABLED_KEY, "1");
    setBrowserVoiceStatus("Asleep - say Friday");
    window.clearTimeout(browserSilenceTimer);
    browserSilenceTimer = window.setTimeout(() => {
      if (browserMicRunning && browserLastLevel < 0.015) {
        noteBrowserStt("Chrome opened the microphone, but the signal is still 0%. Use the mic dropdown, then pick your MacBook or headset microphone.", true);
      }
    }, 3200);
    const sourceName = track.label || "selected microphone";
    addMessage("STT", `Chrome mic is armed through ${sourceName}. FRIDAY is asleep until the wake word.`);
    await refreshStatus();
  } catch (error) {
    browserMicRunning = false;
    addMessage("STT", `Chrome microphone failed: ${error.message || "permission was denied or no mic was found."}`, "error");
    await refreshStatus();
  }
}

function stopBrowserMic(forgetPreference = false) {
  if (forgetPreference) {
    window.localStorage.removeItem(MIC_ENABLED_KEY);
  }
  browserMicRunning = false;
  browserWakeActive = false;
  browserVoiceMode = "wake";
  window.clearTimeout(browserWakeTimer);
  window.clearTimeout(browserSilenceTimer);
  window.cancelAnimationFrame(commandSilenceFrame);
  cancelWakeUtteranceCapture();
  if (commandRecorder && commandRecorder.state !== "inactive") {
    commandRecorder.stop();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }
  if (audioContext) {
    audioContext.close();
  }
  window.cancelAnimationFrame(micAnimationFrame);
  mediaRecorder = null;
  wakeChunks = [];
  wakeCaptureMode = "";
  wakeStartedAt = 0;
  wakeLastVoiceAt = 0;
  wakeHeardVoice = false;
  discardWakeCapture = false;
  commandRecorder = null;
  commandChunks = [];
  mediaStream = null;
  audioContext = null;
  analyser = null;
  queuedBrowserBlob = null;
  browserLastLevel = 0;
  updateMicLevel(0);
  refreshStatus();
}

async function pollEvents() {
  try {
    const response = await fetch(`/api/events?since=${lastEventId}`);
    if (!response.ok) {
      throw new Error(`Event stream returned ${response.status}`);
    }
    const payload = await response.json();
    const events = Array.isArray(payload.events) ? payload.events : [];
    if (eventStreamPaused) {
      eventStreamPaused = false;
      console.info("FRIDAY event stream resumed.");
    }
    eventPollDelayMs = 25;
    for (const event of events) {
      lastEventId = Math.max(lastEventId, event.id);
      if (event.kind === "assistant_ready") {
        addMessage("FRIDAY", event.payload.message, "assistant");
        if (event.payload.message) {
          lastAssistantSpeechText = event.payload.message;
          lastAssistantSpeechAt = Date.now();
          if (browserMicRunning) {
            void waitForSpeechThenIdle();
          }
        }
      }
      if (event.kind === "wake_word_detected") {
        addMessage("FRIDAY", event.payload.message, "assistant");
      }
      if (event.kind === "assistant_response" && event.payload.source !== "text") {
        const duplicateDirectResponse = event.payload.message === lastDirectAssistantResponseText && Date.now() - lastDirectAssistantResponseAt < 5000;
        if (!duplicateDirectResponse) {
          addMessage("FRIDAY", event.payload.message, "assistant");
        }
        if (event.payload.message) {
          lastAssistantSpeechText = event.payload.message;
          lastAssistantSpeechAt = Date.now();
        }
        if (browserMicRunning && (browserVoiceMode === "processing" || browserVoiceMode === "speaking")) {
          browserVoiceMode = "speaking";
          setBrowserVoiceStatus("Speaking");
          restartWakeRecorderForCurrentMode();
        }
      }
      if (event.kind === "voice_command_detected") {
        addMessage("Voice", event.payload.text);
      }
      if (event.kind === "voice_level") {
        updateMicLevel(event.payload.level);
      }
      if (event.kind === "voice_error") {
        addMessage("FRIDAY", event.payload.message, "error");
      }
      if (event.kind === "phone_call_planned") {
        renderPhoneCallPlanned(event.payload);
      }
      if (event.kind === "phone_call_status") {
        updatePhoneCallStatus(event.payload);
      }
      if (event.kind === "phone_call_turn") {
        appendPhoneCallTurn(event.payload);
      }
      if (event.kind === "phone_call_completed") {
        finalisePhoneCall(event.payload, "completed");
      }
      if (event.kind === "phone_call_failed") {
        finalisePhoneCall(event.payload, "failed");
      }
    }
    if (events.length) {
      await refreshStatus(true);
    }
  } catch (error) {
    eventStreamPaused = true;
    eventPollDelayMs = Math.min(Math.max(eventPollDelayMs * 1.8, 500), 5000);
    const now = Date.now();
    if (now - lastEventStreamWarningAt > 10000) {
      lastEventStreamWarningAt = now;
      console.warn("FRIDAY event stream paused; reconnecting.", error);
    }
  } finally {
    setTimeout(pollEvents, eventPollDelayMs);
  }
}

commandForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = commandInput.value.trim();
  if (!text && !selectedUploadFile) {
    return;
  }
  commandInput.value = "";
  if (selectedUploadFile) {
    await sendUploadMessage(text);
    return;
  }
  await sendMessage(text);
});

interruptSpeech.addEventListener("click", async () => {
  await fetch("/api/interrupt", { method: "POST" });
  await refreshStatus(true);
});

document.addEventListener("keydown", async (event) => {
  if (event.key !== "Escape" || event.repeat) {
    return;
  }
  await fetch("/api/interrupt", { method: "POST" });
  await refreshStatus(true);
});

if (clearChat) {
  clearChat.addEventListener("click", clearVisibleChat);
}

if (clearTasks) {
  clearTasks.addEventListener("click", async () => {
    await sendMessage("clear my todo list");
  });
}

if (fileUploadButton && fileInput) {
  fileUploadButton.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    if (file) {
      setSelectedUploadFile(file);
    }
  });
}

if (filePreviewClear) {
  filePreviewClear.addEventListener("click", clearSelectedUpload);
}

const uploadConsole = document.querySelector("#uploadConsole");
if (uploadConsole) {
  ["dragenter", "dragover"].forEach((eventName) => {
    uploadConsole.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadConsole.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    uploadConsole.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadConsole.classList.remove("dragging");
    });
  });
  uploadConsole.addEventListener("drop", (event) => {
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) {
      setSelectedUploadFile(file);
    }
  });
}

muteSpeech.addEventListener("click", async () => {
  const response = await fetch("/api/silent-tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ silent: !silentTTS }),
  });
  const payload = await response.json();
  silentTTS = payload.tts.silent;
  await refreshStatus(true);
});

voiceToggle.addEventListener("click", async () => {
  const statusResponse = await fetch("/api/status");
  const status = await statusResponse.json();
  const endpoint = status.voice && status.voice.running ? "/api/voice/stop" : "/api/voice/start";
  await fetch(endpoint, { method: "POST" });
  await refreshStatus(true);
});

browserMicToggle.addEventListener("click", async () => {
  if (browserMicRunning) {
    stopBrowserMic(true);
  } else {
    await startBrowserMic();
  }
});

micDeviceSelect.addEventListener("change", async () => {
  selectedMicDeviceId = micDeviceSelect.value;
  if (browserMicRunning) {
    stopBrowserMic();
    await startBrowserMic();
  }
});

toneButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    await sendMessage(`set tone to ${button.dataset.tone}`);
  });
});

if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", refreshMicDevices);
}

async function autoStartBrowserMicIfAllowed() {
  if (window.localStorage.getItem(MIC_ENABLED_KEY) !== "1" || browserMicRunning) {
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return;
  }
  try {
    if (navigator.permissions && navigator.permissions.query) {
      const permission = await navigator.permissions.query({ name: "microphone" });
      if (permission.state !== "granted") {
        return;
      }
    }
    await startBrowserMic();
  } catch (error) {
    window.localStorage.removeItem(MIC_ENABLED_KEY);
  }
}

async function requestBrowserGreeting() {
  if (browserGreetingRequested) {
    return;
  }
  browserGreetingRequested = true;
  try {
    await fetch("/api/browser-greeting", { method: "POST" });
  } catch (error) {
    return;
  }
}

startMatrixRain();
startHologramCanvas();
refreshStatus(true).then(requestBrowserGreeting);
refreshMicDevices().then(autoStartBrowserMicIfAllowed);
pollEvents();
