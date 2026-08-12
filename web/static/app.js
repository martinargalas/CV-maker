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

const LABEL_KEYS = [
  "contact", "about", "education", "skills", "links",
  "languages", "interests", "courses", "work",
];

/* What each section is called when nobody has said otherwise. These are shown
   as placeholders, so the field can stay empty and follow the CV's language. */
const DEFAULT_LABELS = {
  en: {
    contact: "Contact", about: "About Me", education: "Education",
    skills: "Skills", links: "Links", languages: "Languages",
    interests: "Interests", courses: "Courses", work: "Work Experience",
  },
  cs: {
    contact: "Kontakt", about: "O mně", education: "Vzdělání",
    skills: "Dovednosti", links: "Odkazy", languages: "Jazyky",
    interests: "Zájmy", courses: "Kurzy", work: "Pracovní zkušenosti",
  },
};

const blank = () => ({
  name: "", role: "", uppercase_name: true,
  phone: "", email: "", location: "", photo: "",
  about: "",
  education: [], skills: [], links: [], languages: [],
  interests: "", courses: [],
  jobs: [],
  language: "en", show_durations: false,
  labels: Object.fromEntries(LABEL_KEYS.map((key) => [key, ""])),
});

const NEW = {
  job: () => ({
    title: "", company: "", city: "",
    start: "", end: "", ongoing: false, when: "",
    intro: "", groups: [NEW.group()],
  }),
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
  out.show_durations = Boolean(out.show_durations);
  // duration_language is what this field was called when it only worded the
  // lengths; files exported before the switch covered everything still use it.
  const language = out.language ?? out.duration_language;
  out.language = language === "cs" ? "cs" : "en";
  delete out.duration_language;
  // Only the shape /api/photo produces. Anything else is dropped rather than
  // put into an <img src>.
  out.photo = /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(out.photo) ? out.photo : "";
  return out;
}

let state = blank();
let previewTimer = null;

/* Month names, only so that switching a job to free text can hand over what
   the pickers were showing. The server words the CV itself. */
const MONTHS = {
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  cs: ["leden", "únor", "březen", "duben", "květen", "červen",
       "červenec", "srpen", "září", "říjen", "listopad", "prosinec"],
};
const ONGOING_WORD = { en: "Present", cs: "současnost" };

function monthText(value, language) {
  const match = /^(\d{4})-(\d{2})$/.exec(value || "");
  if (!match) return /^\d{4}$/.test(value || "") ? value : "";
  return `${MONTHS[language][Number(match[2]) - 1]} ${match[1]}`;
}

function whenText(job) {
  const language = MONTHS[state.language] ? state.language : "en";
  const from = monthText(job.start, language);
  if (!from) return "";
  if (job.ongoing) return `${from} - ${ONGOING_WORD[language]}`;
  const to = monthText(job.end, language);
  return to ? `${from} - ${to}` : from;
}

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

function notice(message, { link, good = false } = {}) {
  noticeEl.textContent = message || "";
  noticeEl.hidden = !message;
  noticeEl.classList.toggle("good", Boolean(message) && good);
  if (message && link) {
    // Built as an element rather than markup: nothing that reaches this
    // function is ever parsed as HTML.
    const anchor = document.createElement("a");
    anchor.href = link.href;
    anchor.textContent = link.text;
    noticeEl.append(" ", anchor);
  }
}

async function postJSON(url, body, method = "POST") {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "X-CV-Client": "1" },
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

/* A CV is read in order, and the order people want is rarely the order they
   typed things in. Arrows rather than dragging: they work on a phone, with a
   keyboard, and with a screen reader. */
function moveButtons(list, index) {
  const last = (getPath(list) || []).length - 1;
  return `
    <button type="button" class="tiny" data-action="move" data-list="${list}"
      data-index="${index}" data-to="${index - 1}" title="Move up"
      aria-label="Move up"${index === 0 ? " disabled" : ""}>↑</button>
    <button type="button" class="tiny" data-action="move" data-list="${list}"
      data-index="${index}" data-to="${index + 1}" title="Move down"
      aria-label="Move down"${index === last ? " disabled" : ""}>↓</button>`;
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
        <span class="block-tools">
          ${moveButtons(`jobs.${jobIndex}.groups`, groupIndex)}
          ${removeButton(`jobs.${jobIndex}.groups`, groupIndex)}
        </span>
      </div>
      ${text(`${base}.label`, "Group label (optional)", "e.g. Delivery")}
      <label><span>Bullets — wrap text in **stars** to bold it</span></label>
      ${textList(`${base}.bullets`, "What you did and what came of it")}
      ${addButton(`${base}.bullets`, "text", "bullet")}
    </div>`;
}

/* Dates are pickers by default and free text when they have to be.

   Month pickers keep nonsense out and make every entry read the same way, but
   they cannot hold everything a real CV says — "2019 - 2021" with no months, a
   range recovered from a PDF, or a note somebody wants worded their own way.
   So the text field stays, one click away, and whatever is in it is used
   exactly as written. */
function dateFields(index) {
  const job = state.jobs[index];
  const typed = Boolean(job.when);

  if (typed) {
    return `
      <div class="dates">
        ${text(`jobs.${index}.when`, "Dates", "Jan 2024 - Present")}
        <button type="button" class="tiny" data-action="dates-pick" data-index="${index}">
          Use the date pickers instead</button>
      </div>`;
  }

  const backwards = job.start && job.end && !job.ongoing && job.end < job.start;
  return `
    <div class="dates">
      <div class="row">
        <label><span>From</span>
          <input type="month" data-path="jobs.${index}.start" value="${esc(job.start)}"></label>
        <label><span>To</span>
          <input type="month" data-path="jobs.${index}.end" value="${esc(job.end)}"
                 ${job.ongoing ? "disabled" : ""}></label>
      </div>
      <label class="check">
        <input type="checkbox" data-path="jobs.${index}.ongoing" ${job.ongoing ? "checked" : ""}>
        Still here
      </label>
      ${backwards ? `<p class="warn">That ends before it starts.</p>` : ""}
      <button type="button" class="tiny" data-action="dates-type" data-index="${index}">
        Type the dates instead</button>
    </div>`;
}

function jobBlock(index) {
  const job = state.jobs[index];
  return `
    <div class="block">
      <div class="block-head">
        <h3>Job ${index + 1}</h3>
        <span class="block-tools">
          ${moveButtons("jobs", index)}
          ${removeButton("jobs", index)}
        </span>
      </div>
      <div class="row">
        ${text(`jobs.${index}.title`, "Job title")}
        ${text(`jobs.${index}.company`, "Company")}
      </div>
      <div class="row">
        ${text(`jobs.${index}.city`, "City")}
      </div>
      ${dateFields(index)}
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
      <label class="inline-select"><span>Language of the CV</span>
        <select data-path="language">
          <option value="en"${state.language === "en" ? " selected" : ""}>English</option>
          <option value="cs"${state.language === "cs" ? " selected" : ""}>Čeština</option>
        </select>
      </label>
      <p class="hint">Sets the section headings, the month names and how a length
        is worded. Headings you have written yourself are left alone.</p>
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
      <label class="check">
        <input type="checkbox" data-path="show_durations" ${state.show_durations ? "checked" : ""}>
        Show how long each job lasted, after the dates
      </label>
      ${state.show_durations ? `
      <p class="hint">Worked out from the dates you pick, so a job still running
        keeps counting. Dates typed as free text that cannot be read are left
        alone.</p>` : ""}
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
        <summary>Word a heading differently</summary>
        <p class="hint">Leave one empty and it follows the CV's language.</p>
        <div class="row">
          ${LABEL_KEYS.map((key) => {
            const fallback = DEFAULT_LABELS[state.language][key];
            return text(`labels.${key}`, fallback, fallback);
          }).join("")}
        </div>
      </details>
    </fieldset>`;
}

/* ------------------------------------------------------------- preview */

function fitPreview() {
  const shell = $("#preview-shell");
  const available = shell.parentElement.clientWidth - 22;
  const scale = Math.min(1, available / 794);
  const height = frame.contentDocument?.documentElement?.scrollHeight || 1123;

  frame.style.height = `${height}px`;
  frame.style.transform = `scale(${scale})`;
  shell.style.width = `${794 * scale}px`;
  shell.style.height = `${height * scale}px`;
}

let previewFailed = false;

async function refreshPreview() {
  statusEl.textContent = "updating…";
  try {
    const response = await postJSON("/api/preview", state);
    const { html } = await response.json();
    frame.srcdoc = html;
    frame.onload = () => { fitPreview(); statusEl.textContent = ""; };
    // Only clear a message this function put there. An import or a save says
    // something worth reading, and the preview refresh that follows it must
    // not wipe it half a second later.
    if (previewFailed) notice("");
    previewFailed = false;
  } catch (error) {
    statusEl.textContent = "";
    previewFailed = true;
    notice(`Preview failed — ${error.message}`);
  }
}

function changed({ redraw = false } = {}) {
  if (redraw) draw();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 350);
}

/* ------------------------------------------------------------- actions */

// Fields that reveal, hide or disable other fields have to redraw the form;
// everything else updates state in place, so the caret stays where it was.
const redraws = (path) =>
  path === "show_durations" || path === "language" || path.endsWith(".ongoing");

form.addEventListener("input", (event) => {
  const path = event.target.dataset.path;
  if (!path) return;
  setPath(path, event.target.type === "checkbox" ? event.target.checked : event.target.value);
  changed({ redraw: redraws(path) });
});

form.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, list, kind, index } = button.dataset;

  if (action === "add") {
    getPath(list).push(NEW[kind]());
    changed({ redraw: true });
  } else if (action === "move") {
    const items = getPath(list);
    const from = Number(index);
    const to = Number(button.dataset.to);
    if (to < 0 || to >= items.length) return;
    [items[from], items[to]] = [items[to], items[from]];
    changed({ redraw: true });
    // The block moved, so the button under the pointer belongs to a different
    // entry now. Follow the one that travelled: the same arrow if it can still
    // be used, otherwise the opposite one, so the keyboard never lands nowhere.
    const arrow = (towards) => form.querySelector(
      `button[data-action="move"][data-list="${list}"][data-index="${to}"][data-to="${towards}"]`
    );
    const same = arrow(to + (to - from));
    const other = arrow(to - (to - from));
    if (same && !same.disabled) same.focus();
    else if (other && !other.disabled) other.focus();
  } else if (action === "remove") {
    getPath(list).splice(Number(index), 1);
    changed({ redraw: true });
  } else if (action === "dates-type") {
    // Carry the picked dates over as text, so switching does not wipe them.
    const job = state.jobs[Number(index)];
    job.when = whenText(job) || "";
    job.start = job.end = "";
    job.ongoing = false;
    changed({ redraw: true });
  } else if (action === "dates-pick") {
    const job = state.jobs[Number(index)];
    job.when = "";
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

/* ------------------------------------------------- importing plain text */

async function readText(text) {
  if (!text.trim()) {
    notice("Nothing to read — paste your CV text first.");
    return;
  }
  try {
    const response = await fetch("/api/import-text", {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: text,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `${response.status}`);

    state = normalize(data.cv);
    $("#text-import").hidden = true;
    $("#text-import-input").value = "";
    // The text format does not mark which paragraph is a job's intro, so say
    // so rather than let a wrong guess pass as a finished CV.
    notice([
      "Imported — check it over, especially each job's intro.",
      ...data.warnings,
    ].join(" "));
    changed({ redraw: true });
  } catch (error) {
    notice(`Import failed — ${error.message}`);
  }
}

$("#txt-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => readText(String(reader.result));
  reader.readAsText(file);
});

$("#pdf-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;

  const box = $("#text-import-input");
  notice("Reading the PDF…");
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch("/api/import-pdf", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `${response.status}`);

    // The text goes in the box rather than straight into the form. Recovering
    // a CV from a PDF gets things wrong, and this is the moment where that is
    // cheap to fix — before it becomes a hundred form fields.
    box.value = data.text;
    box.focus();
    box.setSelectionRange(0, 0);
    notice([
      "Read the PDF. Check the text, fix anything it got wrong, then press “Read it”.",
      ...data.warnings,
    ].join(" "));
  } catch (error) {
    notice(`Could not read that PDF — ${error.message}`);
  }
});

$("#text-import").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action } = button.dataset;
  if (action === "text-import-run") readText($("#text-import-input").value);
  else if (action === "text-import-file") $("#txt-input").click();
  else if (action === "pdf-import-file") $("#pdf-input").click();
  else if (action === "text-import-cancel") $("#text-import").hidden = true;
});

document.querySelector(".bar-actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action } = button.dataset;

  if (action === "save") {
    await save();
  } else if (action === "import") {
    $("#json-input").click();
  } else if (action === "import-text") {
    const panel = $("#text-import");
    panel.hidden = !panel.hidden;
    if (!panel.hidden) $("#text-import-input").focus();
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

/* ------------------------------------------------------------- saving */

let savedId = new URLSearchParams(location.search).get("id");
let signedIn = false;

async function save() {
  const button = $("#save-button");
  const title = $("#cv-title").value.trim();
  button.disabled = true;
  try {
    if (savedId) {
      await postJSON(`/api/cvs/${savedId}`, { title, cv: state }, "PUT");
    } else {
      const response = await postJSON("/api/cvs", { title, cv: state });
      savedId = (await response.json()).id;
      // Keep the address in step, so a reload or a bookmark opens this CV
      // rather than starting a new one.
      history.replaceState(null, "", `/edit?id=${encodeURIComponent(savedId)}`);
    }
    button.textContent = "Saved";
    setTimeout(() => { button.textContent = "Save"; }, 1500);
    // Saving is the step that puts this CV on the front page, so that is the
    // moment to say where it went and offer the way there.
    notice("Saved.", { good: true, link: { href: "/", text: "See all your CVs →" } });
  } catch (error) {
    notice(`Could not save — ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

/* Start with whatever this page is for: a saved CV, or the example, so the
   first thing anyone sees is a filled-in CV rather than an empty sheet. */
(async () => {
  try {
    const me = await (await fetch("/api/me")).json();
    signedIn = Boolean(me.signed_in);
    $("#save-button").hidden = !signedIn;
    // Only worth offering when there is a page of saved CVs to go back to.
    $("#mine-link").hidden = !signedIn;
  } catch (_) {}

  if (savedId && signedIn) {
    try {
      const response = await fetch(`/api/cvs/${savedId}`);
      if (!response.ok) throw new Error((await response.json()).error || "not found");
      const saved = await response.json();
      state = normalize(saved.cv);
      $("#cv-title").value = saved.title;
      draw();
      refreshPreview();
      return;
    } catch (error) {
      savedId = null;
      history.replaceState(null, "", "/edit");
      notice(`Could not open that CV — ${error.message}`);
    }
  }

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
