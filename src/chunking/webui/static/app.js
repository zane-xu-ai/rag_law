(function () {
  const $ = (id) => document.getElementById(id);

  const sectionLabel = {
    all: "",
    first: "前段",
    middle: "中段",
    last: "后段",
  };

  const CHUNK_HINT_SLIDING =
    "「与上一块/下一块重叠」表示相邻块在原文中重合的字符数（滑窗重叠），不是本块长度；本块长度见每段标题中的「本块 N 字」。";
  const CHUNK_HINT_DOCSEG =
    "方案 D：相邻块通常无滑窗式重叠（多为 0）；本块长度见「本块 N 字」。边界来自文档分段模型 + min/max 与换行优先再切分。";

  function showError(msg) {
    const el = $("err");
    el.textContent = msg;
    el.hidden = !msg;
  }

  function showErrorDocseg(msg) {
    const el = $("err_docseg");
    el.textContent = msg;
    el.hidden = !msg;
  }

  function parseOptionalFloat(id) {
    const v = $(id).value.trim();
    if (!v) return null;
    const n = parseFloat(v);
    return Number.isNaN(n) ? null : n;
  }

  function parseOptionalInt(id) {
    const v = $(id).value.trim();
    if (!v) return null;
    const n = parseInt(v, 10);
    return Number.isNaN(n) ? null : n;
  }

  function syncSemanticParamsRow() {
    const on = $("compare_semantic").checked;
    $("semantic_params_row").classList.toggle("disabled", !on);
  }

  function setChunkHintSingle(summary) {
    const el = $("chunk_hint_single");
    if (!el) return;
    el.textContent =
      summary.method === "document_segmentation_d" ? CHUNK_HINT_DOCSEG : CHUNK_HINT_SLIDING;
  }

  function renderSummary(s, summaryPreId) {
    if (s.method === "document_segmentation_d") {
      const lines = [
        "切分方式: 方案 D（document_segmentation）",
        `总字符数: ${s.total_chars}`,
        `块数: ${s.chunk_count}`,
        `model_dir: ${s.model_dir}`,
        `min_chars / max_chars / split_overlap: ${s.doc_segmentation_min_chars} / ${s.doc_segmentation_max_chars} / ${s.doc_segmentation_split_overlap}`,
        `原文段落数(粗分): ${s.source_paragraphs}`,
      ];
      if (s.doc_segmentation_note) {
        lines.push("", "说明:", s.doc_segmentation_note);
      }
      lines.push(
        "",
        "每段字符数: " + JSON.stringify(s.chars_per_chunk),
        "每段字符数 min/max/avg: " + JSON.stringify(s.chars_per_chunk_stats),
        "",
        "相邻块在原文中的间隙/重叠(字): " + JSON.stringify(s.overlap_between_adjacent),
        "相邻统计: " + JSON.stringify(s.overlap_adjacent_stats),
      );
      $(summaryPreId).textContent = lines.join("\n");
      return;
    }

    const lines = [
      `总字符数: ${s.total_chars}`,
      `块数: ${s.chunk_count}`,
      `chunk_size: ${s.chunk_size}  chunk_overlap: ${s.chunk_overlap}`,
      `boundary_aware: ${s.boundary_aware}`,
      `原文段落数(粗分): ${s.source_paragraphs}`,
    ];
    if (s.boundary_aware && s.overlap_floor_effective != null) {
      if (s.boundary_priority_overlap_effective != null) {
        lines.push(
          `boundary_priority_overlap_effective: ${s.boundary_priority_overlap_effective}（预览在重叠上下界相等时自动为 true，句界优先于钉死重叠）`,
        );
      }
      lines.push(
        `overlap_floor_effective: ${s.overlap_floor_effective}  overlap_ceiling_effective: ${s.overlap_ceiling_effective}（块链重叠夹紧区间；未配置 CHUNK_OVERLAP_MIN/MAX 时二者通常等于本次 chunk_overlap）`,
      );
      lines.push(
        "提示: 相邻块在原文重合的字符数应落在此区间内；若 floor 与 ceiling 相等，则重合长度基本恒为该值。这与「每块正文长度」无关，后者见每段标题「本块 N 字」与下方「每段字符数」。",
      );
    }
    lines.push(
      `semantic_merge_enabled: ${s.semantic_merge_enabled}`,
      `semantic_merge_threshold / min_chars / max_chars: ${s.semantic_merge_threshold} / ${s.semantic_merge_min_chars} / ${s.semantic_merge_max_chars}`,
    );
    if (s.semantic_merge_note) {
      lines.push("", "语义合并说明:", s.semantic_merge_note);
    }
    lines.push(
      "",
      "每段字符数: " + JSON.stringify(s.chars_per_chunk),
      "每段字符数 min/max/avg: " + JSON.stringify(s.chars_per_chunk_stats),
      "",
      "相邻块实际重叠: " + JSON.stringify(s.overlap_between_adjacent),
      "相邻重叠 min/max/avg: " + JSON.stringify(s.overlap_adjacent_stats),
    );
    if (s.boundary_length_note) {
      lines.push("", "说明:", s.boundary_length_note);
    }
    $(summaryPreId).textContent = lines.join("\n");
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function buildOverlapInnerHtml(text, prefixLen, suffixLen) {
    const L = text.length;
    const p = Math.min(Math.max(0, prefixLen), L);
    const s = Math.min(Math.max(0, suffixLen), L);
    if (L === 0) return "";
    if (p + s > L) {
      return `<span class="overlap-chars">${escapeHtml(text)}</span>`;
    }
    let html = "";
    if (p > 0) {
      html += `<span class="overlap-chars">${escapeHtml(text.slice(0, p))}</span>`;
    }
    html += escapeHtml(text.slice(p, L - s));
    if (s > 0) {
      html += `<span class="overlap-chars">${escapeHtml(text.slice(L - s))}</span>`;
    }
    return html;
  }

  function renderChunks(display, summary, chunksWrapId, omitId) {
    const wrap = $(chunksWrapId);
    wrap.innerHTML = "";
    const omit = $(omitId);
    omit.textContent = display.omitted_message || "";
    const overlaps = summary.overlap_between_adjacent || [];
    const n = summary.chunk_count;

    for (const c of display.chunks) {
      const div = document.createElement("div");
      div.className = "chunk";
      const meta = document.createElement("div");
      meta.className = "chunk-meta";
      const tag =
        display.mode === "truncated" && c.section && c.section !== "all"
          ? `<span class="section-tag">${sectionLabel[c.section] || c.section}</span>`
          : "";
      const idx = c.index;
      const prefixLen =
        typeof c.overlap_prev === "number"
          ? c.overlap_prev
          : idx > 0
            ? overlaps[idx - 1]
            : 0;
      const suffixLen =
        typeof c.overlap_next === "number"
          ? c.overlap_next
          : idx < n - 1
            ? overlaps[idx]
            : 0;

      const pieceLen = c.text.length;
      const overlapBits = [];
      if (prefixLen > 0) overlapBits.push(`与上一块重叠 ${prefixLen} 字`);
      if (suffixLen > 0) overlapBits.push(`与下一块重叠 ${suffixLen} 字`);
      const overlapPart =
        overlapBits.length > 0 ? ` &nbsp;· ${overlapBits.join(" · ")}` : "";

      meta.innerHTML = `${tag}#${c.index} &nbsp; char [${c.char_start}, ${c.char_end}) &nbsp;· 本块 ${pieceLen} 字${overlapPart}`;

      const tx = document.createElement("div");
      tx.className = "chunk-text";
      tx.innerHTML = `<div class="chunk-text-inner">${buildOverlapInnerHtml(
        c.text,
        prefixLen,
        suffixLen,
      )}</div>`;
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
    const compare_semantic = $("compare_semantic").checked;

    const semThr = parseOptionalFloat("semantic_merge_threshold");
    const semMin = parseOptionalInt("semantic_merge_min_chars");
    const semMax = parseOptionalInt("semantic_merge_max_chars");

    const jsonPayload = {
      text: ta,
      chunk_size,
      chunk_overlap,
      boundary_aware,
      compare_semantic,
      semantic_merge_threshold: semThr,
      semantic_merge_min_chars: semMin,
      semantic_merge_max_chars: semMax,
    };

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
        if (compare_semantic) {
          fd.append("compare_semantic", "true");
        }
        if (semThr != null) fd.append("semantic_merge_threshold", String(semThr));
        if (semMin != null) fd.append("semantic_merge_min_chars", String(semMin));
        if (semMax != null) fd.append("semantic_merge_max_chars", String(semMax));
        res = await fetch("/api/preview", { method: "POST", body: fd });
      } else {
        res = await fetch("/api/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(jsonPayload),
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
      const mode = data.mode || "single";

      if (mode === "comparison") {
        $("results_single").hidden = true;
        $("results_compare").hidden = false;
        const b = data.boundary;
        const sm = data.semantic_merged;
        renderSummary(b.summary, "summary_b");
        renderChunks(b.display, b.summary, "chunks_b", "omit_b");
        renderSummary(sm.summary, "summary_s");
        renderChunks(sm.display, sm.summary, "chunks_s", "omit_s");
      } else {
        $("results_single").hidden = false;
        $("results_compare").hidden = true;
        renderSummary(data.summary, "summary");
        setChunkHintSingle(data.summary);
        renderChunks(data.display, data.summary, "chunks", "omit");
      }

      $("results").hidden = false;
    } catch (e) {
      showError(String(e));
    }
  }

  async function runDocSeg() {
    showErrorDocseg("");
    $("results").hidden = true;

    const ta = $("text").value;
    const fileInput = $("file").files && $("file").files[0];
    const modelRaw = $("docseg_model_path").value.trim();
    const jsonPayload = { text: ta };
    if (modelRaw) jsonPayload.model_path = modelRaw;
    const dmin = parseOptionalInt("docseg_min_chars");
    const dmax = parseOptionalInt("docseg_max_chars");
    const dov = parseOptionalInt("docseg_split_overlap");
    if (dmin != null) jsonPayload.min_chars = dmin;
    if (dmax != null) jsonPayload.max_chars = dmax;
    if (dov != null) jsonPayload.split_overlap = dov;

    let res;
    try {
      if (fileInput) {
        const fd = new FormData();
        fd.append("text", ta);
        fd.append("file", fileInput);
        if (modelRaw) fd.append("model_path", modelRaw);
        if (dmin != null) fd.append("min_chars", String(dmin));
        if (dmax != null) fd.append("max_chars", String(dmax));
        if (dov != null) fd.append("split_overlap", String(dov));
        res = await fetch("/api/preview-document-segmentation", {
          method: "POST",
          body: fd,
        });
      } else {
        res = await fetch("/api/preview-document-segmentation", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(jsonPayload),
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
        showErrorDocseg(`${res.status}: ${detail}`);
        return;
      }

      const data = await res.json();
      $("results_single").hidden = false;
      $("results_compare").hidden = true;
      renderSummary(data.summary, "summary");
      setChunkHintSingle(data.summary);
      renderChunks(data.display, data.summary, "chunks", "omit");
      $("results").hidden = false;
    } catch (e) {
      showErrorDocseg(String(e));
    }
  }

  async function loadDocSegStatus() {
    const el = $("docseg_status");
    if (!el) return;
    el.textContent = "正在检查方案 D 配置…";
    try {
      const res = await fetch("/api/document-segmentation/status");
      if (!res.ok) {
        el.textContent = "无法读取 /api/document-segmentation/status";
        return;
      }
      const j = await res.json();
      const parts = [];
      parts.push(
        j.modelscope_import_ok
          ? "modelscope 已安装。"
          : "modelscope 未安装（请 uv sync --extra segmentation）。",
      );
      if (j.document_segmentation_path) {
        parts.push(
          j.path_exists
            ? `DOCUMENT_SEGMENTATION_PATH 已配置且目录存在。`
            : `DOCUMENT_SEGMENTATION_PATH=${j.document_segmentation_path}（目录不存在）`,
        );
      } else {
        parts.push("DOCUMENT_SEGMENTATION_PATH 未配置；可在上方填写模型目录。");
      }
      el.textContent = parts.join(" ");
    } catch (e) {
      el.textContent = String(e);
    }
  }

  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((btn) => {
      const on = btn.dataset.tab === name;
      btn.classList.toggle("tab-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== name;
    });
    if (name === "docseg") {
      loadDocSegStatus();
    }
  }

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });

  $("btn").addEventListener("click", run);
  $("btn_docseg").addEventListener("click", runDocSeg);
  $("compare_semantic").addEventListener("change", syncSemanticParamsRow);
  syncSemanticParamsRow();
})();
