(function () {
  const $ = (id) => document.getElementById(id);

  const sectionLabel = {
    all: "",
    first: "前段",
    middle: "中段",
    last: "后段",
  };

  function showError(msg) {
    const el = $("err");
    el.textContent = msg;
    el.hidden = !msg;
  }

  function renderSummary(s) {
    const lines = [
      `总字符数: ${s.total_chars}`,
      `块数: ${s.chunk_count}`,
      `chunk_size: ${s.chunk_size}  chunk_overlap: ${s.chunk_overlap}`,
      `boundary_aware: ${s.boundary_aware}`,
      `原文段落数(粗分): ${s.source_paragraphs}`,
    ];
    if (s.boundary_aware && s.overlap_floor_effective != null) {
      lines.push(
        `overlap_floor_effective: ${s.overlap_floor_effective}  overlap_ceiling_effective: ${s.overlap_ceiling_effective}（来自 min(本次 chunk_overlap, .env 中 CHUNK_OVERLAP_MIN/MAX)）`
      );
    }
    lines.push(
      "",
      "每段字符数: " + JSON.stringify(s.chars_per_chunk),
      "每段字符数 min/max/avg: " + JSON.stringify(s.chars_per_chunk_stats),
      "",
      "相邻块实际重叠: " + JSON.stringify(s.overlap_between_adjacent),
      "相邻重叠 min/max/avg: " + JSON.stringify(s.overlap_adjacent_stats)
    );
    if (s.boundary_length_note) {
      lines.push("", "说明:", s.boundary_length_note);
    }
    $("summary").textContent = lines.join("\n");
  }

  function renderChunks(display) {
    const wrap = $("chunks");
    wrap.innerHTML = "";
    const omit = $("omit");
    omit.textContent = display.omitted_message || "";
    for (const c of display.chunks) {
      const div = document.createElement("div");
      div.className = "chunk";
      const meta = document.createElement("div");
      meta.className = "chunk-meta";
      const tag =
        display.mode === "truncated" && c.section && c.section !== "all"
          ? `<span class="section-tag">${sectionLabel[c.section] || c.section}</span>`
          : "";
      meta.innerHTML = `${tag}#${c.index} &nbsp; char [${c.char_start}, ${c.char_end})`;
      const tx = document.createElement("div");
      tx.className = "chunk-text";
      tx.textContent = c.text;
      div.appendChild(meta);
      div.appendChild(tx);
      wrap.appendChild(div);
    }
  }

  async function run() {
    showError("");
    $("results").hidden = true;

    const chunk_size = parseInt($("chunk_size").value, 10);
    const chunk_overlap = parseInt($("chunk_overlap").value, 10);
    if (Number.isNaN(chunk_size) || chunk_size < 1) {
      showError("chunk_size 须为大于等于 1 的整数");
      return;
    }
    if (Number.isNaN(chunk_overlap) || chunk_overlap < 0) {
      showError("chunk_overlap 须为非负整数");
      return;
    }

    const ta = $("text").value;
    const fileInput = $("file").files && $("file").files[0];
    const boundary_aware = $("boundary_aware").checked;

    let res;
    try {
      if (fileInput) {
        const fd = new FormData();
        fd.append("text", ta);
        fd.append("file", fileInput);
        fd.append("chunk_size", String(chunk_size));
        fd.append("chunk_overlap", String(chunk_overlap));
        if (boundary_aware) {
          fd.append("boundary_aware", "true");
        }
        res = await fetch("/api/preview", { method: "POST", body: fd });
      } else {
        res = await fetch("/api/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: ta,
            chunk_size,
            chunk_overlap,
            boundary_aware,
          }),
        });
      }

      if (!res.ok) {
        let detail = res.statusText;
        try {
          const j = await res.json();
          if (j.detail) {
            detail =
              typeof j.detail === "string"
                ? j.detail
                : JSON.stringify(j.detail);
          }
        } catch (_) {}
        showError(`${res.status}: ${detail}`);
        return;
      }

      const data = await res.json();
      renderSummary(data.summary);
      renderChunks(data.display);
      $("results").hidden = false;
    } catch (e) {
      showError(String(e));
    }
  }

  $("btn").addEventListener("click", run);
})();
