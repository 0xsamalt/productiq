/* Product Health Score — renders cached insights and handles on-demand refresh. */
(function () {
  const SEV = {
    high: { label: "High", cls: "bg-red-100 text-red-700" },
    medium: { label: "Medium", cls: "bg-amber-100 text-amber-700" },
    low: { label: "Low", cls: "bg-zinc-100 text-zinc-600" },
  };
  const TREND = { up: "↑ rising", down: "↓ falling", flat: "→ stable" };

  function scoreColor(s) {
    if (s == null) return "bg-zinc-100 text-zinc-500";
    if (s >= 85) return "bg-emerald-100 text-emerald-700";
    if (s >= 70) return "bg-green-100 text-green-700";
    if (s >= 50) return "bg-amber-100 text-amber-700";
    return "bg-red-100 text-red-700";
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function bar(label, val) {
    const pct = Math.round((val || 0) * 100);
    return `<div class="flex items-center gap-2 text-xs">
      <span class="w-20 text-zinc-500 capitalize">${esc(label)}</span>
      <div class="flex-1 h-1.5 bg-zinc-100 rounded-full overflow-hidden">
        <div class="h-full bg-brand rounded-full" style="width:${pct}%"></div>
      </div>
      <span class="w-9 text-right text-zinc-600 tabular-nums">${pct}%</span>
    </div>`;
  }

  function render(container, d) {
    if (!d || d.computed_at == null) {
      container.innerHTML =
        `<p class="text-xs text-zinc-500">No insights yet. Click <span class="font-medium">Refresh insights</span> to analyze diagnostic conversations.</p>`;
      return;
    }
    const score = d.health_score;
    const scoreBox = `<div class="flex items-center gap-3">
        <div class="flex flex-col items-center justify-center rounded-xl px-4 py-2 ${scoreColor(score)}">
          <span class="text-2xl font-bold leading-none tabular-nums">${score == null ? "—" : score}</span>
          <span class="text-[10px] font-medium uppercase tracking-wider mt-0.5">${esc(d.grade || "—")}</span>
        </div>
        <div class="text-xs text-zinc-500 leading-relaxed">
          <div>Health score${score == null ? " <span class='text-zinc-400'>(need ≥5 chats)</span>" : ""}</div>
          <div>${d.sample_size} conversation(s) · issues ${TREND[d.trend] || "→ stable"}</div>
        </div>
      </div>`;

    const b = d.breakdown || {};
    const bars = Object.keys(b).length
      ? `<div class="space-y-1 mt-3">${["coverage", "resolution", "severity", "trend"]
          .filter((k) => k in b)
          .map((k) => bar(k, b[k]))
          .join("")}</div>`
      : "";

    const summary = d.summary
      ? `<p class="text-xs text-zinc-600 mt-3 leading-relaxed">${esc(d.summary)}</p>`
      : "";

    const issues = (d.top_issues || []).length
      ? `<div class="mt-3">
          <div class="text-xs font-semibold text-zinc-500 mb-1.5">Top reported issues</div>
          <ul class="space-y-1.5">${d.top_issues
            .map((it) => {
              const sev = SEV[it.severity] || SEV.low;
              const gap = it.doc_gap_rate >= 0.5
                ? `<span class="text-[10px] text-amber-600">· doc gap</span>` : "";
              return `<li class="flex items-center justify-between gap-2 text-xs">
                <span class="min-w-0 truncate"><span class="font-medium">${esc(it.title)}</span> ${gap}</span>
                <span class="flex items-center gap-1.5 shrink-0">
                  <span class="px-1.5 py-0.5 rounded ${sev.cls} text-[10px] font-medium">${sev.label}</span>
                  <span class="text-zinc-400 tabular-nums">${it.count}×</span>
                </span>
              </li>`;
            })
            .join("")}</ul>
        </div>`
      : "";

    const gaps = (d.coverage_gaps || []).length
      ? `<div class="mt-3 rounded-lg bg-amber-50 border border-amber-100 p-2.5">
          <div class="text-xs font-semibold text-amber-700 mb-1">Documentation gaps</div>
          <ul class="text-xs text-amber-800 space-y-0.5">${d.coverage_gaps
            .map((g) => `<li>• ${esc(g.title)} <span class="text-amber-600">(${g.count}× uncovered)</span></li>`)
            .join("")}</ul>
        </div>`
      : "";

    container.innerHTML = scoreBox + bars + summary + issues + gaps;
  }

  function init() {
    const data = window.__INSIGHTS__ || {};
    document.querySelectorAll("[id^='health-']").forEach((el) => {
      const pid = el.id.replace("health-", "");
      render(el, data[pid]);
    });

    document.querySelectorAll("[data-refresh-health]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pid = btn.getAttribute("data-refresh-health");
        const container = document.getElementById("health-" + pid);
        const label = btn.querySelector("span");
        const original = label ? label.textContent : "";
        btn.disabled = true;
        btn.classList.add("opacity-60");
        if (label) label.textContent = "Analyzing…";
        try {
          const res = await fetch(`/api/products/${pid}/insights/refresh`, { method: "POST" });
          if (!res.ok) throw new Error("HTTP " + res.status);
          const d = await res.json();
          render(container, d);
        } catch (e) {
          container.innerHTML = `<p class="text-xs text-red-600">Couldn't refresh insights (${esc(e.message)}). Try again.</p>`;
        } finally {
          btn.disabled = false;
          btn.classList.remove("opacity-60");
          if (label) label.textContent = original;
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
