"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const token = $("meta[name=silver-token]").content;
let catalog,
  formats = [],
  busy = false,
  group = "farm",
  lastJob = "",
  noticeTimer,
  refreshing = false;
const labels = {
  hook_text: "Wording",
  bad: "Cross",
  good: "Tick",
  enabled: "Enabled",
  retire_at: "Use limit",
  amount: "Amount",
  per: "Period",
  caption: "Caption",
  heard: "Heard",
  correct: "Correction",
  gain_db: "Volume (dB)",
  start: "Start (seconds)",
  end: "End (seconds)",
  chance: "Chance (%)",
  song_start: "Song start (seconds)",
  offset: "Offset after hook (seconds)",
  use_case: "Tutorial category",
  use_cases: "Matching categories (comma-separated)",
  join: "Join",
  answer_start: "Tutorial starts (seconds)",
  ending_text: "Ending text",
  assembly: "Tutorial assembly",
  crop_top: "Crop top (0–0.9)",
  crop_bottom: "Crop bottom (0–0.9)",
  crop_left: "Crop left (0–0.9)",
  crop_right: "Crop right (0–0.9)",
  frame_scale: "Full-screen zoom (1–3)",
  frame_x: "Frame X (0–1)",
  frame_y: "Frame Y (0–1)",
  background: "Background",
  position: "Presenter position",
  width: "Presenter width (0.08–1.5)",
  x: "Presenter X (−1–1)",
  y: "Presenter Y (−1–1)",
  loop: "Loop reaction",
};
function toast(message, error = false) {
  clearTimeout(noticeTimer);
  const el = $("#toast");
  el.textContent = message;
  el.className = error ? "error-toast" : "";
  el.hidden = false;
  noticeTimer = setTimeout(() => (el.hidden = true), error ? 10000 : 4000);
}
const act =
  (fn) =>
  async (...args) => {
    try {
      return await fn(...args);
    } catch (e) {
      toast(e.message, true);
    }
  };
async function api(url, data) {
  const options =
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "X-Silver-Token": token },
          body: data instanceof FormData ? data : JSON.stringify(data),
        };
  if (data !== undefined && !(data instanceof FormData))
    options.headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw Error(
      "Panel is offline. Open Start Silver Goose.command to reconnect.",
    );
  }
  const result = await response.json();
  if (!response.ok || result.ok === false)
    throw Error(result.error || "Request failed.");
  return result;
}
function modal(title, body, buttons = []) {
  $("#dialog-title").textContent = title;
  $("#dialog-body").innerHTML = body;
  $("#dialog-actions").replaceChildren();
  for (const [text, fn, primary] of buttons) {
    const b = document.createElement("button");
    b.textContent = text;
    if (primary) b.className = "primary";
    b.onclick = act(async () => {
      b.disabled = true;
      try {
        await fn();
      } finally {
        b.disabled = false;
      }
    });
    $("#dialog-actions").append(b);
  }
  if (!$("#dialog").open) $("#dialog").showModal();
}
function close() {
  for (const v of $$("#dialog video,#dialog audio")) v.pause();
  $("#dialog").close();
}
$("#dialog-close").onclick = close;
$("#dialog").addEventListener("close", () => {
  for (const v of $$("#dialog video,#dialog audio")) v.pause();
});
function tab(name) {
  for (const t of $$(".tab")) {
    const active = t.dataset.tab === name;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", String(active));
  }
  $("#builder").hidden = name !== "builder";
  $("#assets").hidden = name !== "assets";
  if (name === "assets") loadAssets();
}
for (const t of $$(".tab")) t.onclick = () => tab(t.dataset.tab);
function selected() {
  return Object.fromEntries(
    $$("[data-count]").map((x) => [x.dataset.count, Number(x.value) || 0]),
  );
}
function selection() {
  let sum = Object.values(selected()).reduce((a, b) => a + b, 0);
  $("#total").textContent =
    sum + " video" + (sum === 1 ? "" : "s") + " selected";
  $("#build").disabled = busy || !sum;
  $("#selection-note").textContent = busy ? "Build in progress" : "";
  for (const input of $$("[data-count]")) {
    input.disabled = busy || Number(input.max) === 0;
    input
      .closest(".format-card")
      .classList.toggle("selected", Number(input.value) > 0);
  }
}
async function refreshFormats() {
  const product = $("#product").value;
  const result = await api("/api/state?product=" + product);
  if (product !== $("#product").value) return;
  formats = result.formats;
  $("#formats").innerHTML = formats
    .map(
      (f, i) =>
        `<article class="format-card ${f.left ? "" : "unavailable"}"><span class="format-number">${String(i + 1).padStart(2, "0")}</span><h3>${esc(f.label)}</h3>${f.reason ? `<p class="reason">${esc(f.reason)}</p><button class="add-assets" data-assets="${f.id}">Open assets ↗</button>` : ""}<div class="format-foot"><span class="availability">${f.left ? `Up to <b>${f.left}</b> available` : "Needs assets"}</span><label class="sr-only" for="count-${f.id}">${esc(f.label)} quantity</label><input id="count-${f.id}" data-count="${f.id}" type="number" min="0" max="${Math.min(500, f.left)}" step="1" value="0" ${!f.left ? "disabled" : ""}></div></article>`,
    )
    .join("");
  for (const x of $$("[data-count]")) x.oninput = selection;
  for (const x of $$("[data-assets]"))
    x.onclick = () => {
      group = x.dataset.assets;
      tab("assets");
    };
  selection();
}
$("#product").onchange = act(async () => {
  localStorage.setItem("sg-product", $("#product").value);
  await refreshFormats();
});
$("#build").onclick = act(async () => {
  $("#build").disabled = true;
  try {
    await api("/api/build", {
      product: $("#product").value,
      counts: selected(),
    });
    await poll();
  } finally {
    selection();
  }
});
async function outputs() {
  const fmt = $("#output-format").value;
  const result = await api("/api/outputs?format=" + encodeURIComponent(fmt));
  $("#output-count").textContent = result.outputs.length;
  $("#output-grid").innerHTML = result.outputs.length
    ? result.outputs
        .map(
          (r) =>
            `<article class="output-card">${r.available ? `<button class="output-preview" data-output-file="${esc(r.file)}" aria-label="Preview ${esc(r.video_id)}"><img loading="lazy" src="/media/thumbnail/${encodeURI(r.file)}" alt="${esc(r.video_id)}"><span aria-hidden="true">▶</span></button>` : '<div class="empty">File moved or removed</div>'}<div class="info"><strong>${esc(r.video_id)}</strong><p class="muted">${esc(catalog.formats[r.format])} · ${esc(catalog.products[r.product] || r.product)}</p>${r.caption ? `<button class="small" data-copy="${esc(r.caption)}">Copy caption</button>` : ""}${r.available ? ` <a href="/media/output/${encodeURI(r.file)}" download>Save video</a>` : ""}</div></article>`,
        )
        .join("")
    : '<div class="empty">Your finished videos will appear here.</div>';
  for (const b of $$("[data-output-file]"))
    b.onclick = () =>
      modal(
        "Video preview",
        `<video class="preview" controls autoplay playsinline src="/media/output/${encodeURI(b.dataset.outputFile)}"></video>`,
      );
  for (const b of $$("[data-copy]"))
    b.onclick = act(async () => {
      await navigator.clipboard.writeText(b.dataset.copy);
      toast("Caption copied.");
    });
}
$("#output-format").onchange = act(outputs);
$("#open-videos").onclick = act(() =>
  api("/api/open", { format: $("#output-format").value }),
);
$("#open-trash").onclick = act(() => api("/api/open", { where: "trash" }));
async function poll() {
  if (refreshing) return;
  refreshing = true;
  try {
    const j = await api("/api/job");
    const wasBusy = busy;
    busy = j.busy;
    selection();
    $("#job").hidden = j.status === "idle";
    if (j.status !== "idle") {
      $("#job-title").textContent =
        {
          running:
            "Building" + (j.current ? " · " + catalog.formats[j.current] : ""),
          complete: "Build complete",
          partial: "Some videos need attention",
          failed: "Build failed",
          interrupted: "Build interrupted",
        }[j.status] || j.status;
      $("#job-count").textContent = j.made + " / " + j.requested + " videos";
      $("#job-progress").max = Math.max(1, j.requested);
      $("#job-progress").value = j.made;
      $("#job-log").textContent = j.log || "Starting…";
      $("#job-error").hidden = !j.error;
      $("#job-error").textContent = j.error || "";
      const key = j.id + "|" + j.status + "|" + j.made;
      if (key !== lastJob) {
        lastJob = key;
        await outputs();
        if (!busy) await refreshFormats();
      }
    }
    if (wasBusy && !busy) toast("Build finished.");
  } finally {
    refreshing = false;
  }
}
const grouping = {
  common: ["font", "logos", "song", "song_short"],
  line: ["hooks"],
  card: ["hooks_short"],
  compare: ["hooks"],
  farm: ["farm_scenes", "farm_speaking", "farm_songs"],
  mcp_farm: [
    "mcp_farm_scenes",
    "mcp_farm_speaking",
    "mcp_farm_tutorials",
    "mcp_farm_songs",
  ],
  reaction: [
    "reaction_hooks",
    "reaction_intros",
    "reaction_reactions",
    "reaction_bridges",
    "reaction_endings",
    "reaction_music",
  ],
  tutorial_story: [
    "tutorial_story_scenes",
    "tutorial_story_endings",
    "tutorial_story_music",
  ],
  ai_larp: ["ai_larp_originals", "ai_larp_ai", "ai_larp_music"],
};
const textGroups = {
  common: ["captions", "caption_fixes"],
  line: ["hook_lines", "money_cards"],
  card: ["money_cards"],
  compare: ["compare_lines"],
  farm: ["farm_hooks"],
  mcp_farm: ["mcp_farm_hooks"],
};
const poolHint = (key) =>
  key.endsWith("_speaking")
    ? "Paired filenames: take-1-a.mp4 + take-1-b.mp4"
    : key === "ai_larp_originals"
      ? "Filenames: larp-1.mp4, larp-2.mp4"
      : key === "ai_larp_ai"
        ? "Match originals: larp-1-ai-1.mp4, larp-1-ai-2.mp4"
        : key === "logos"
          ? "Paired PNGs: openart-1.png + shorts-1.png"
          : "";
async function loadAssets() {
  if (!catalog) return;
  const current = group;
  $("#asset-nav").innerHTML = Object.keys(grouping)
    .map(
      (k) =>
        `<button data-group="${k}" class="${k === group ? "active" : ""}">${esc(k === "common" ? "Common" : catalog.formats[k])}</button>`,
    )
    .join("");
  for (const b of $$("[data-group]"))
    b.onclick = act(async () => {
      group = b.dataset.group;
      await loadAssets();
    });
  $("#asset-body").innerHTML = '<div class="empty">Loading assets…</div>';
  try {
    const settings = await api("/api/settings");
    const keys = [...grouping[current]];
    if (settings.formats[current])
      keys.splice(1, 0, "tutorial_" + settings.formats[current]);
    const items = await Promise.all(
      keys.map((k) => api("/api/assets/" + k + "?format=" + current)),
    );
    if (current !== group) return;
    $("#asset-body").innerHTML =
      `<div class="text-controls">${(textGroups[current] || []).map((k) => `<button data-text="${k}">${esc(catalog.tables[k].label)}</button>`).join("")}${current === "common" ? '<button id="emoji">Emoji</button><button id="vocabulary">Caption vocabulary</button>' : ""}</div>` +
      items
        .map(
          ({ pool, files }) =>
            `<section class="asset-section"><div class="section-head"><h3>${esc(pool.label)} <span class="badge">${files.length}</span></h3><div class="actions"><button data-folder="${pool.id}">Open folder</button><button data-upload="${pool.id}">Add files</button></div></div>${poolHint(pool.id) ? `<p class="pool-hint">${esc(poolHint(pool.id))}</p>` : ""}<div class="asset-files">${
              files
                .map(
                  (f) =>
                    `<div class="asset-row"><button class="asset-name" data-preview="${pool.id}" data-name="${esc(f.name)}">${esc(f.name)}</button>${
                      pool.library
                        ? `<label class="sr-only" for="tag-${pool.id}-${files.indexOf(f)}">Content type for ${esc(f.name)}</label><select id="tag-${pool.id}-${files.indexOf(f)}" data-tag="${pool.library}" data-name="${esc(f.name)}"><option value="">Unassigned</option>${Object.entries(
                            catalog.products,
                          )
                            .map(
                              ([id, label]) =>
                                `<option value="${id}" ${id === f.product ? "selected" : ""}>${label}</option>`,
                            )
                            .join(
                              "",
                            )}</select><button class="small" data-pairing="${pool.library}" data-name="${esc(f.name)}">Pairing</button>`
                        : `<small>${(f.bytes / 1024 / 1024).toFixed(1)} MB</small>`
                    }${f.settings || pool.id === "reaction_music" ? `<button class="small" data-media-settings="${pool.id}" data-name="${esc(f.name)}">Settings</button>` : ""}<button class="small remove" data-remove="${pool.id}" data-name="${esc(f.name)}" aria-label="Remove ${esc(f.name)}">×</button></div>${f.error ? `<p class="error">${esc(f.error)}</p>` : ""}`,
                )
                .join("") || '<div class="empty">No files yet.</div>'
            }</div></section>`,
        )
        .join("");
    for (const b of $$("[data-text]"))
      b.onclick = act(() => editText(b.dataset.text));
    for (const b of $$("[data-folder]"))
      b.onclick = act(() => api("/api/open", { pool: b.dataset.folder }));
    for (const b of $$("[data-upload]"))
      b.onclick = () => uploadDialog(b.dataset.upload);
    for (const b of $$("[data-preview]"))
      b.onclick = () => preview(b.dataset.preview, b.dataset.name);
    for (const b of $$("[data-remove]"))
      b.onclick = () =>
        modal("Remove asset?", `<p>${esc(b.dataset.name)}</p>`, [
          ["Keep", close],
          [
            "Move to trash",
            async () => {
              await api("/api/assets/" + b.dataset.remove + "/remove", {
                name: b.dataset.name,
              });
              close();
              await loadAssets();
              toast("Moved to library trash.");
              await refreshFormats();
            },
          ],
        ]);
    for (const s of $$("[data-tag]"))
      s.onchange = act(async () => {
        await api("/api/tutorials/assign", {
          library: s.dataset.tag,
          names: [s.dataset.name],
          product: s.value,
        });
        toast("Content type saved.");
        await refreshFormats();
      });
    for (const b of $$("[data-pairing]"))
      b.onclick = act(() => editPairing(b.dataset.pairing, b.dataset.name));
    for (const b of $$("[data-media-settings]"))
      b.onclick = act(() => {
        const item = items.find((x) => x.pool.id === b.dataset.mediaSettings);
        return mediaSettings(
          item.pool,
          item.files.find((f) => f.name === b.dataset.name),
        );
      });
    if ($("#emoji"))
      $("#emoji").onclick = () => textSetting("emoji", "Emoji", settings.emoji);
    if ($("#vocabulary"))
      $("#vocabulary").onclick = () =>
        textSetting("vocabulary", "Caption vocabulary", settings.vocabulary);
  } catch (e) {
    $("#asset-body").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}
function preview(key, name) {
  const kind = catalog.pools[key].kind,
    url = "/media/asset/" + key + "/" + encodeURIComponent(name);
  modal(
    name,
    kind === "video"
      ? `<video class="preview" controls autoplay playsinline src="${url}"></video>`
      : kind === "audio"
        ? `<audio class="preview" controls src="${url}"></audio>`
        : kind === "image"
          ? `<img class="preview-image" src="${url}" alt="${esc(name)}">`
          : "<p>Classic · TikTok Display Medium</p>",
  );
}
function uploadDialog(key) {
  const pool = catalog.pools[key];
  modal(
    "Add " + pool.label.toLowerCase(),
    `${poolHint(key) ? `<p class="pool-hint">${esc(poolHint(key))}</p>` : ""}<label class="field">Files<input type="file" id="upload-files" ${pool.fixed ? "" : "multiple"} accept="${pool.kind === "video" ? "video/*" : pool.kind === "audio" ? "audio/*" : pool.kind === "image" ? ".png" : ".ttf"}"></label>${
      pool.library
        ? `<label class="field">Content type<select id="upload-product">${Object.entries(
            catalog.products,
          )
            .map(
              ([k, v]) =>
                `<option value="${k}" ${k === $("#product").value ? "selected" : ""}>${v}</option>`,
            )
            .join("")}</select></label>`
        : ""
    }<label class="field" style="margin-top:15px">Filename (one file only; optional)<input id="upload-name" placeholder="Keep original filename" ${pool.fixed ? 'disabled value="' + pool.fixed + '"' : ""}></label>`,
    [
      [
        "Add files",
        async () => {
          const files = [...$("#upload-files").files];
          if (!files.length) throw Error("Choose files first.");
          const form = new FormData();
          files.forEach((f) => form.append("files", f));
          if (pool.library) form.append("product", $("#upload-product").value);
          const name = $("#upload-name").value.trim();
          if (name && !pool.fixed) {
            if (files.length !== 1) throw Error("Rename one file at a time.");
            form.append("names", JSON.stringify([name]));
          }
          const result = await api("/api/assets/" + key + "/upload", form);
          close();
          toast(result.added.length + " file(s) added.");
          await loadAssets();
          await refreshFormats();
        },
        true,
      ],
    ],
  );
}
async function editText(key) {
  const t = await api("/api/text/" + key);
  let rows = t.rows.map((r, i) => ({ ...r, id: r.id ?? String(i) }));
  function draw() {
    modal(
      t.label,
      `<div class="table-wrap"><table><thead><tr>${t.fields.map((f) => `<th>${esc(labels[f] || f)}</th>`).join("")}<th></th></tr></thead><tbody>${rows.map((r, i) => `<tr data-row="${i}">${t.fields.map((f) => `<td><input aria-label="${esc(labels[f] || f)} ${i + 1}" data-field="${f}" ${f === "enabled" ? `type="checkbox" ${r[f] !== "0" ? "checked" : ""}` : f === "retire_at" ? `type="number" min="1" max="1000" value="${esc(r[f] || (/farm/.test(key) ? 40 : 25))}"` : `type="text" value="${esc(r[f] || "")}"`}></td>`).join("")}<td><button data-delete-row="${i}" aria-label="Remove row ${i + 1}">×</button></td></tr>`).join("")}</tbody></table></div><button id="add-row" style="margin-top:12px">+ Add row</button>`,
      [
        [
          "Save",
          async () => {
            collect();
            await api("/api/text/" + key, { rows });
            close();
            toast("Text saved.");
            await refreshFormats();
          },
          true,
        ],
      ],
    );
    $("#add-row").onclick = () => {
      collect();
      rows.push({ id: "", enabled: "1" });
      draw();
    };
    for (const b of $$("[data-delete-row]"))
      b.onclick = () => {
        collect();
        rows.splice(Number(b.dataset.deleteRow), 1);
        draw();
      };
  }
  function collect() {
    for (const tr of $$("[data-row]"))
      for (const el of tr.querySelectorAll("[data-field]"))
        rows[Number(tr.dataset.row)][el.dataset.field] =
          el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
  }
  draw();
}
function textSetting(key, title, value) {
  modal(
    title,
    `<label class="field">One entry per line<textarea id="plain-text">${esc(value)}</textarea></label>`,
    [
      [
        "Save",
        async () => {
          await api("/api/settings", { [key]: $("#plain-text").value });
          close();
          toast("Saved.");
          await refreshFormats();
        },
        true,
      ],
    ],
  );
}
$("#build-settings").onclick = act(async () => {
  const s = await api("/api/settings");
  modal(
    "Build settings",
    `<div class="settings-grid">${s.formulas.map((x) => `<label class="field">${esc(x.fmt.map((f) => catalog.formats[f]).join(" / "))} · ${esc(x.label)}<input data-formula="${x.key}" type="number" min="${x.lo}" max="${x.hi}" step="${x.whole ? 1 : 0.5}" value="${x.value}"></label>`).join("")}</div>`,
    [
      [
        "Save",
        async () => {
          await api("/api/settings", {
            formulas: Object.fromEntries(
              $$("[data-formula]").map((x) => [x.dataset.formula, x.value]),
            ),
          });
          close();
          await refreshFormats();
          toast("Build settings saved.");
        },
        true,
      ],
    ],
  );
});
$("#tutorial-settings").onclick = act(async () => {
  const s = await api("/api/settings");
  modal(
    "Tutorial folders",
    `<div class="settings-grid">${Object.entries(s.formats)
      .map(
        ([fmt, lib]) =>
          `<label class="field">${esc(catalog.formats[fmt])}<select data-library-format="${fmt}">${catalog.libraries.map((x) => `<option value="${x.id}" ${x.id === lib ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>`,
      )
      .join("")}</div>`,
    [
      [
        "Save",
        async () => {
          await api("/api/settings", {
            formats: Object.fromEntries(
              $$("[data-library-format]").map((x) => [
                x.dataset.libraryFormat,
                x.value,
              ]),
            ),
          });
          close();
          await loadAssets();
          await refreshFormats();
          toast("Tutorial folders saved.");
        },
        true,
      ],
    ],
  );
});
async function editPairing(library, name) {
  const p = await api(
    "/api/tutorials/pairing?library=" +
      library +
      "&name=" +
      encodeURIComponent(name),
  );
  const choices = {
    logos: p.logos.map((x) => [x, x]),
    compare: p.compare.map((x) => [x.id, x.bad + " / " + x.good]),
  };
  modal(
    "Pairing · " + name,
    Object.entries(choices)
      .map(
        ([kind, options]) =>
          `<section class="pairing-group"><label><input type="checkbox" data-pair-all="${kind}" ${p.choice[kind] === null || p.choice[kind] === undefined ? "checked" : ""}> All ${kind === "compare" ? "comparison wordings" : kind}</label><div class="pairing-options">${options.map(([id, label]) => `<label><input type="checkbox" data-pair-kind="${kind}" value="${esc(id)}" ${p.choice[kind]?.includes(id) ? "checked" : ""}>${esc(label)}</label>`).join("")}</div></section>`,
      )
      .join(""),
    [
      [
        "Save",
        async () => {
          const d = { library, name };
          for (const kind of Object.keys(choices))
            d[kind] = $(`[data-pair-all="${kind}"]`).checked
              ? null
              : $$(`[data-pair-kind="${kind}"]:checked`).map((x) => x.value);
          await api("/api/tutorials/pairing", d);
          close();
          await refreshFormats();
          toast("Pairing saved.");
        },
        true,
      ],
    ],
  );
}
function mediaSettings(pool, file) {
  let settings = { ...file.settings };
  const reaction =
    (pool.format === "reaction" && pool.role !== "music") || pool.library;
  if (reaction && !file.settings)
    settings = {
      start: 0,
      end: file.seconds || 1,
      join: "contrast",
      assembly: "finished",
      use_case: "",
      answer_start: null,
      enabled: true,
    };
  if (pool.id === "reaction_music")
    settings = {
      enabled: true,
      song_start: 0,
      offset: 0,
      gain_db: -18,
      ...settings,
    };
  const enums = {
    join: ["contrast", "answer", "either"],
    assembly: ["finished", "pieces"],
    background: ["person", "green", "keep", "alpha"],
    position: ["alternate", "left", "center", "right", "custom"],
  };
  modal(
    "Settings · " + file.name,
    `<div class="settings-grid">${Object.entries(settings)
      .filter(([k]) => labels[k] || k === "enabled")
      .map(
        ([k, v]) =>
          `<label class="field ${typeof v === "boolean" ? "check" : ""}">${esc(labels[k] || k)}${typeof v === "boolean" ? `<input type="checkbox" data-setting="${k}" ${v ? "checked" : ""}>` : enums[k] ? `<select data-setting="${k}">${enums[k].map((x) => `<option ${v === x ? "selected" : ""}>${x}</option>`).join("")}</select>` : `<input data-setting="${k}" type="${["use_case", "use_cases", "ending_text"].includes(k) ? "text" : "number"}" step="any" value="${esc(Array.isArray(v) ? v.join(", ") : (v ?? ""))}">`}</label>`,
      )
      .join("")}</div>`,
    [
      [
        "Save",
        async () => {
          const value = { ...settings };
          for (const x of $$("[data-setting]")) {
            const k = x.dataset.setting;
            value[k] =
              x.type === "checkbox"
                ? x.checked
                : x.type === "number"
                  ? x.value === ""
                    ? null
                    : Number(x.value)
                  : x.value;
            if (k === "use_cases")
              value[k] = x.value.trim()
                ? x.value
                    .split(",")
                    .map((v) => v.trim())
                    .filter(Boolean)
                : null;
          }
          await api("/api/assets/" + pool.id + "/settings", {
            name: file.name,
            settings: value,
            format: group,
          });
          close();
          await loadAssets();
          await refreshFormats();
          toast("Asset settings saved.");
        },
        true,
      ],
    ],
  );
}
act(async () => {
  catalog = await api("/api/catalog");
  $("#output-format").innerHTML =
    '<option value="">All formats</option>' +
    Object.entries(catalog.formats)
      .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`)
      .join("");
  const saved = localStorage.getItem("sg-product");
  if (catalog.products[saved]) $("#product").value = saved;
  await refreshFormats();
  await outputs();
  await poll();
  setInterval(() => poll().catch((e) => toast(e.message, true)), 2500);
})();
