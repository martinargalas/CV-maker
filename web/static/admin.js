/* The admin page: accounts, not their contents.

   Everything the server returns here is about who has an account and how much
   they hold. There is no route that hands an administrator somebody else's CV,
   and this page does not ask for one. */

const $ = (sel) => document.querySelector(sel);
const noticeEl = $("#notice");

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

function notice(message, ok = false) {
  noticeEl.textContent = message || "";
  noticeEl.hidden = !message;
  noticeEl.classList.toggle("good", ok);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "X-CV-Client": "1",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.error || `${response.status}`);
  return data;
}

const when = (seconds) => new Date(seconds * 1000).toLocaleDateString();

async function draw() {
  const { users, signup_allowed } = await api("/api/admin/users");
  $("#signup-allowed").checked = signup_allowed;
  $("#users").innerHTML = users.map((user) => `
    <tr>
      <td>${esc(user.username)}${user.is_admin ? ' <span class="badge">admin</span>' : ""}</td>
      <td>${user.cvs}</td>
      <td>${when(user.created_at)}</td>
      <td class="right">
        <button type="button" class="tiny" data-act="reset"
                data-id="${user.id}" data-name="${esc(user.username)}">Reset password</button>
        <button type="button" class="tiny remove" data-act="delete"
                data-id="${user.id}" data-name="${esc(user.username)}"
                data-cvs="${user.cvs}">Delete</button>
      </td>
    </tr>`).join("");
  $("#admin").hidden = false;
}

$("#signup-allowed").addEventListener("change", async (event) => {
  try {
    await api("/api/admin/signup-allowed", {
      method: "POST",
      body: JSON.stringify({ allowed: event.target.checked }),
    });
    notice(event.target.checked ? "Anyone can create an account." : "New accounts are off.", true);
  } catch (error) {
    notice(error.message);
    await draw();
  }
});

$("#users").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const { act, id, name, cvs } = button.dataset;
  try {
    if (act === "reset") {
      const password = prompt(`New password for ${name}:`);
      if (!password) return;
      await api(`/api/admin/users/${id}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      notice(`${name} has a new password, and has been signed out everywhere.`, true);
    } else if (act === "delete") {
      // Deleting an account takes their CVs with it, so say so plainly.
      const warning = Number(cvs)
        ? `Delete ${name}? Their ${cvs} saved CV(s) go too. This cannot be undone.`
        : `Delete ${name}? This cannot be undone.`;
      if (!confirm(warning)) return;
      await api(`/api/admin/users/${id}`, { method: "DELETE" });
      notice(`${name} has been removed.`, true);
    }
    await draw();
  } catch (error) {
    notice(error.message);
  }
});

$("#add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({
        username: $("#add-username").value,
        password: $("#add-password").value,
        code: "",
      }),
    });
    $("#add-form").reset();
    notice("Account created.", true);
    await draw();
  } catch (error) {
    notice(error.message);
  }
});

$("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/password", {
      method: "POST",
      body: JSON.stringify({
        current: $("#pw-current").value,
        replacement: $("#pw-new").value,
      }),
    });
    $("#password-form").reset();
    notice("Password changed. Other browsers have been signed out.", true);
  } catch (error) {
    notice(error.message);
  }
});

(async () => {
  try {
    await draw();
  } catch (error) {
    // Not an administrator, or not signed in — the page has nothing to show.
    notice(`${error.message} Go back to the front page to sign in.`);
  }
})();
