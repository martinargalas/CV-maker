/* The landing page: sign in, then the CVs you have saved, as tiles.

   Everything here is about accounts and files, never about CV content — the
   tiles show a name, a role and a date, and the CV itself is only loaded when
   you open it in the editor. */

const $ = (sel) => document.querySelector(sel);
const noticeEl = $("#notice");

let me = { signed_in: false };

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

function notice(message) {
  noticeEl.textContent = message || "";
  noticeEl.hidden = !message;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "X-CV-Client": "1",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.error || `${response.status}`);
  return data;
}

const when = (seconds) => new Date(seconds * 1000).toLocaleDateString(undefined, {
  year: "numeric", month: "short", day: "numeric",
});

/* --------------------------------------------------------------- signing in */

let mode = "login";

function drawGate() {
  const first = me.first_run;
  const signingUp = mode === "signup" || first;

  $("#gate-title").textContent = first ? "Set up this server"
    : signingUp ? "Create an account" : "Sign in";
  $("#gate-hint").textContent = first
    ? "Nobody has an account here yet. The first one becomes the administrator."
    : "";
  $("#gate-submit").textContent = signingUp ? "Create account" : "Sign in";
  $("#gate-password").autocomplete = signingUp ? "new-password" : "current-password";
  $("#gate-code-row").hidden = !(signingUp && !first && me.signup_needs_code);

  const canSwitch = !first && (me.signup_allowed || signingUp);
  $("#gate-switch").hidden = !canSwitch;
  $("#gate-switch").textContent = signingUp ? "I already have an account" : "Create an account";

  $("#gate").hidden = false;
  $("#tiles-pane").hidden = true;
}

$("#gate-switch").addEventListener("click", () => {
  mode = mode === "signup" ? "login" : "signup";
  notice("");
  drawGate();
});

$("#gate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = JSON.stringify({
    username: $("#gate-username").value,
    password: $("#gate-password").value,
    code: $("#gate-code").value,
  });
  const url = (mode === "signup" || me.first_run) ? "/api/signup" : "/api/login";
  try {
    me = await api(url, { method: "POST", body });
    notice("");
    await start();
  } catch (error) {
    notice(error.message);
  }
});

/* ------------------------------------------------------------------- tiles */

function tile(cv) {
  const avatar = cv.photo
    ? `<img class="tile-photo" src="${esc(cv.photo)}" alt="">`
    : `<span class="tile-photo tile-photo-blank" aria-hidden="true"></span>`;
  return `
    <article class="tile">
      <a class="tile-open" href="/edit?id=${encodeURIComponent(cv.id)}">
        ${avatar}
        <span class="tile-text">
          <strong>${esc(cv.title)}</strong>
          <span class="tile-role">${esc(cv.role || cv.name || "No role yet")}</span>
          <span class="tile-meta">${cv.jobs} job${cv.jobs === 1 ? "" : "s"} · ${when(cv.updated_at)}</span>
        </span>
      </a>
      <div class="tile-actions">
        <button type="button" class="tiny" data-act="rename" data-id="${esc(cv.id)}">Rename</button>
        <button type="button" class="tiny" data-act="duplicate" data-id="${esc(cv.id)}">Duplicate</button>
        <button type="button" class="tiny remove" data-act="delete" data-id="${esc(cv.id)}"
                data-title="${esc(cv.title)}">Delete</button>
      </div>
    </article>`;
}

async function drawTiles() {
  $("#gate").hidden = true;
  $("#tiles-pane").hidden = false;
  const { cvs } = await api("/api/cvs");
  $("#tiles").innerHTML = cvs.map(tile).join("");
  $("#tiles-empty").hidden = cvs.length > 0;
}

$("#tiles").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const { act, id, title } = button.dataset;
  try {
    if (act === "rename") {
      const name = prompt("New name for this CV:", title);
      if (name === null) return;
      await api(`/api/cvs/${id}/rename`, { method: "POST", body: JSON.stringify({ title: name }) });
    } else if (act === "duplicate") {
      await api(`/api/cvs/${id}/duplicate`, { method: "POST", body: "{}" });
    } else if (act === "delete") {
      // Deleting is the one action here that cannot be undone, so it asks.
      if (!confirm(`Delete “${title}”? This cannot be undone.`)) return;
      await api(`/api/cvs/${id}`, { method: "DELETE" });
    }
    notice("");
    await drawTiles();
  } catch (error) {
    notice(error.message);
  }
});

/* -------------------------------------------------------------------- bar */

function drawBar() {
  const actions = $("#bar-actions");
  if (!me.signed_in) {
    actions.innerHTML = `<a class="button ghost" href="/edit">Make a CV without an account</a>`;
    return;
  }
  actions.innerHTML = `
    <span class="who">${esc(me.username)}</span>
    ${me.is_admin ? `<a class="button ghost" href="/admin">Admin</a>` : ""}
    <button type="button" class="ghost" id="signout">Sign out</button>`;
  $("#signout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    me = await api("/api/me");
    await start();
  });
}

async function start() {
  drawBar();
  if (me.signed_in) {
    try {
      await drawTiles();
    } catch (error) {
      notice(error.message);
    }
  } else {
    drawGate();
  }
}

(async () => {
  try {
    me = await api("/api/me");
  } catch (_) {
    me = { signed_in: false };
  }
  await start();
})();
