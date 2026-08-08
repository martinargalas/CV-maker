/* The form. It edits a plain object, posts it to the server, and shows back
   whatever the server draws. No markup from the user, and none shown to them:
   the fields are structured, and the preview is a picture of a layout.

   The form is only rebuilt when its shape changes — adding or removing a job,
   a bullet, a skill. Typing updates the state object in place, so the caret
   stays where it is. */

const MAX = {
  jobs: 20, groups: 12, bullets: 20, skills: 40,
  education: 15, courses: 15, links: 10, languages: 15,
};

const LABEL_FIELDS = [
  ["contact", "Contact"], ["about", "About Me"], ["education", "Education"],
  ["skills", "Skills"], ["links", "Links"], ["languages", "Languages"],
  ["interests", "Interests"], ["courses", "Courses"], ["work", "Work Experience"],
];

const blank = () => ({
  name: "", role: "", uppercase_name: true,
  phone: "", email: "", location: "", photo: "",
  about: "",
  education: [], skills: [], links: [], languages: [],
  interests: "", courses: [],
  jobs: [],
  labels: Object.fromEntries(LABEL_FIELDS),
});

const NEW = {
  job: () => ({ title: "", company: "", city: "", when: "", intro: "", groups: [NEW.group()] }),
  group: () => ({ label: "", bullets: [""] }),
  entry: () => ({ title: "", subtitle: "", meta: "" }),
  link: () => ({ label: "", url: "" }),
  text: () => "",
};

/* An imported file is someone else's data, not necessarily ours. Force it into
   the shape the form expects so a hand-edited or hostile cv.json produces a
   sane form rather than a broken page. */
function normalize(loaded) {
  const base = blank();
  const out = { ...base, ...(loaded || {}) };
  for (const key of ["education", "courses"]) {
    out[key] = Array.isArray(out[key]) ? out[key].map((e) => ({ ...NEW.entry(), ...e })) : [];
  }
  for (const key of ["skills", "languages"]) {
    out[key] = Array.isArray(out[key]) ? out[key].map((v) => String(v ?? "")) : [];
  }
  out.links = Array.isArray(out.links) ? out.links.map((l) => ({ ...NEW.link(), ...l })) : [];
  out.jobs = Array.isArray(out.jobs) ? out.jobs.map((job) => ({
    ...NEW.job(),
    ...job,
    groups: Array.isArray(job?.groups) ? job.groups.map((group) => ({
      ...NEW.group(),
      ...group,
      bullets: Array.isArray(group?.bullets) ? group.bullets.map((b) => String(b ?? "")) : [],
    })) : [],
  })) : [];
  out.labels = { ...base.labels, ...(loaded?.labels || {}) };
  out.uppercase_name = Boolean(out.uppercase_name);
  // Only the shape /api/photo produces. Anything else is dropped rather than
  // put into an <img src>.
  out.photo = /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(out.photo) ? out.photo : "";
  return out;
}

let state = blank();
let previewTimer = null;

const $ = (sel) => document.querySelector(sel);
const form = $("#form");
const noticeEl = $("#notice");
const statusEl = $("#preview-status");
const frame = $("#preview");

/* ------------------------------------------------------------- utilities */

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

function getPath(path) {
  return path.split(".").reduce((node, key) => node?.[key], state);
}

function setPath(path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const node = keys.reduce((n, key) => n[key], state);
  node[last] = value;
}

function notice(message) {
  noticeEl.textContent = message || "";
  noticeEl.hidden = !message;
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).error || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------- field HTML */

function text(path, label, placeholder = "") {
  return `<label><span>${esc(label)}</span>
    <input type="text" data-path="${path}" value="${esc(getPath(path))}"
           placeholder="${esc(placeholder)}"></label>`;
}

function area(path, label, placeholder = "", rows = 3) {
  return `<label><span>${esc(label)}</span>
    <textarea data-path="${path}" rows="${rows}"
              placeholder="${esc(placeholder)}">${esc(getPath(path))}</textarea></label>`;
}

function addButton(list, kind, caption) {
  const full = (getPath(list) || []).length >= (MAX[list.split(".").pop()] ?? 99);
  return `<button type="button" class="tiny" data-action="add" data-list="${list}"
    data-kind="${kind}"${full ? " disabled" : ""}>+ ${esc(caption)}</button>`;
}

function removeButton(list, index, caption = "Remove") {
  return `<button type="button" class="tiny remove" data-action="remove"
    data-list="${list}" data-index="${index}">${esc(caption)}</button>`;
}

/* simple list of strings — skills, languages, bullets */
function textList(list, placeholder) {
  return (getPath(list) || []).map((_, i) => `
    <div class="line">
      <input type="text" data-path="${list}.${i}" value="${esc(getPath(`${list}.${i}`))}"
             placeholder="${esc(placeholder)}">
      ${removeButton(list, i, "×")}
    </div>`).join("");
}

function entryList(list) {
  return (getPath(list) || []).map((_, i) => `
    <div class="block">
      <div class="block-head"><h3>#${i + 1}</h3>${removeButton(list, i)}</div>
      ${text(`${list}.${i}.title`, "Title", "Degree / certification")}
      <div class="row">
        ${text(`${list}.${i}.subtitle`, "Institution, city")}
        ${text(`${list}.${i}.meta`, "Year")}
      </div>
    </div>`).join("");
}

function groupBlock(jobIndex, groupIndex) {
  const base = `jobs.${jobIndex}.groups.${groupIndex}`;
  return `
    <div class="block group-block">
      <div class="block-head">
        <h3>Group ${groupIndex + 1}</h3>
        ${removeButton(`jobs.${jobIndex}.groups`, groupIndex)}
      </div>
      ${text(`${base}.label`, "Group label (optional)", "e.g. Delivery")}
      <label><span>Bullets — wrap text in **stars** to bold it</span></label>
      ${textList(`${base}.bullets`, "What you did and what came of it")}
      ${addButton(`${base}.bullets`, "text", "bullet")}
    </div>`;
}

function jobBlock(index) {
  const job = state.jobs[index];
  return `
    <div class="block">
      <div class="block-head">
        <h3>Job ${index + 1}</h3>
        ${removeButton("jobs", index)}
      </div>
      <div class="row">
        ${text(`jobs.${index}.title`, "Job title")}
        ${text(`jobs.${index}.company`, "Company")}
      </div>
      <div class="row">
        ${text(`jobs.${index}.city`, "City")}
        ${text(`jobs.${index}.when`, "Dates", "Jan 2024 - Present")}
      </div>
      ${area(`jobs.${index}.intro`, "Intro (optional)", "One or two sentences.", 2)}
      ${job.groups.map((_, gi) => groupBlock(index, gi)).join("")}
      <p>${addButton(`jobs.${index}.groups`, "group", "group of bullets")}</p>
    </div>`;
}

/* ------------------------------------------------------------- the form */

function draw() {
  form.innerHTML = `
    <fieldset>
      <legend>Basics</legend>
      <div class="row">
        ${text("name", "Name")}
        ${text("role", "Role", "Engineering Manager")}
      </div>
      <label class="check">
        <input type="checkbox" data-path="uppercase_name" ${state.uppercase_name ? "checked" : ""}>
        Show the name in capitals, as in the sample CV
      </label>
      <div class="photo-row">
        ${state.photo ? `<img src="${esc(state.photo)}" alt="">` : ""}
        <button type="button" class="tiny" data-action="photo">
          ${state.photo ? "Replace photo" : "Add photo"}</button>
        ${state.photo ? `<button type="button" class="tiny remove" data-action="drop-photo">Remove</button>` : ""}
      </div>
      <p class="hint">The photo is resized and re-encoded here, then kept in your
        browser. It is never stored on the server.</p>
    </fieldset>

    <fieldset>
      <legend>Contact</legend>
      <div class="row">
        ${text("phone", "Phone")}
        ${text("email", "Email")}
        ${text("location", "City, country")}
      </div>
    </fieldset>

    <fieldset>
      <legend>About</legend>
      ${area("about", "Short summary", "Two or three sentences.", 4)}
    </fieldset>

    <fieldset>
      <legend>Work experience</legend>
      ${state.jobs.map((_, i) => jobBlock(i)).join("")}
      <p>${addButton("jobs", "job", "job")}</p>
    </fieldset>

    <fieldset>
      <legend>Education</legend>
      ${entryList("education")}
      <p>${addButton("education", "entry", "education")}</p>
    </fieldset>

    <fieldset>
      <legend>Skills</legend>
      ${textList("skills", "One skill")}
      ${addButton("skills", "text", "skill")}
    </fieldset>

    <fieldset>
      <legend>Links</legend>
      ${(state.links || []).map((_, i) => `
        <div class="line">
          <input type="text" data-path="links.${i}.label" value="${esc(state.links[i].label)}"
                 placeholder="LinkedIn">
          <input type="text" data-path="links.${i}.url" value="${esc(state.links[i].url)}"
                 placeholder="https://...">
          ${removeButton("links", i, "×")}
        </div>`).join("")}
      ${addButton("links", "link", "link")}
      <p class="hint">Only http:// and https:// addresses are used; anything else is dropped.</p>
    </fieldset>

    <fieldset>
      <legend>Languages</legend>
      ${textList("languages", "English")}
      ${addButton("languages", "text", "language")}
    </fieldset>

    <fieldset>
      <legend>Interests</legend>
      ${area("interests", "One line", "What you do outside work.", 2)}
    </fieldset>

    <fieldset>
      <legend>Courses</legend>
      ${entryList("courses")}
      <p>${addButton("courses", "entry", "course")}</p>
    </fieldset>

    <fieldset>
      <legend>Section headings</legend>
      <details class="labels">
        <summary>Rename the headings, or translate them</summary>
        <div class="row">
          ${LABEL_FIELDS.map(([key, fallback]) => text(`labels.${key}`, fallback)).join("")}
        </div>
      </details>
    </fieldset>`;
}

/* ------------------------------------------------------------- preview */

function fitPreview() {
  const available = frame.parentElement.clientWidth - 20;
  const scale = Math.min(1, available / 794);
  frame.style.transform = `scale(${scale})`;
  const height = frame.contentDocument?.documentElement?.scrollHeight || 1123;
  frame.style.height = `${height}px`;
  frame.parentElement.style.height = `${height * scale + 20}px`;
}

async function refreshPreview() {
  statusEl.textContent = "updating…";
  try {
    const response = await postJSON("/api/preview", state);
    const { html } = await response.json();
    frame.srcdoc = html;
    frame.onload = () => { fitPreview(); statusEl.textContent = ""; };
    notice("");
  } catch (error) {
    statusEl.textContent = "";
    notice(`Preview failed — ${error.message}`);
  }
}

function changed({ redraw = false } = {}) {
  if (redraw) draw();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 350);
}

/* ------------------------------------------------------------- actions */

form.addEventListener("input", (event) => {
  const path = event.target.dataset.path;
  if (!path) return;
  setPath(path, event.target.type === "checkbox" ? event.target.checked : event.target.value);
  changed();
});

form.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, list, kind, index } = button.dataset;

  if (action === "add") {
    getPath(list).push(NEW[kind]());
    changed({ redraw: true });
  } else if (action === "remove") {
    getPath(list).splice(Number(index), 1);
    changed({ redraw: true });
  } else if (action === "photo") {
    $("#photo-input").click();
  } else if (action === "drop-photo") {
    state.photo = "";
    changed({ redraw: true });
  }
});

$("#photo-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch("/api/photo", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `${response.status}`);
    state.photo = data.photo;
    notice("");
    changed({ redraw: true });
  } catch (error) {
    notice(`Photo rejected — ${error.message}`);
  }
});

$("#json-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const loaded = JSON.parse(reader.result);
      if (!loaded || typeof loaded !== "object" || Array.isArray(loaded)) {
        throw new Error("that file is not a saved CV");
      }
      state = normalize(loaded);
      notice("");
      changed({ redraw: true });
    } catch (error) {
      notice(`Import failed — ${error.message}`);
    }
  };
  reader.readAsText(file);
});

document.querySelector(".bar-actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action } = button.dataset;

  if (action === "import") {
    $("#json-input").click();
  } else if (action === "export") {
    download(new Blob([JSON.stringify(state, null, 2)], { type: "application/json" }), "cv.json");
  } else if (action === "load-example") {
    const response = await fetch("/static/example.json");
    state = normalize(await response.json());
    changed({ redraw: true });
  } else if (action === "render") {
    button.disabled = true;
    button.textContent = "Rendering…";
    try {
      const response = await postJSON("/api/render", state);
      const pages = response.headers.get("X-CV-Pages");
      download(await response.blob(), "cv.pdf");
      notice(pages ? `Rendered, but it came out as ${pages} pages instead of one.` : "");
    } catch (error) {
      notice(`Render failed — ${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = "Download PDF";
    }
  }
});

window.addEventListener("resize", fitPreview);

/* Start on the example, so the first thing anyone sees is a filled-in CV
   rather than an empty sheet. */
(async () => {
  try {
    const response = await fetch("/static/example.json");
    state = normalize(await response.json());
  } catch (_) {
    state = blank();
    state.jobs = [NEW.job()];
  }
  draw();
  refreshPreview();
})();
