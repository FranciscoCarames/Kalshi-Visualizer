/* Framework-agnostic perf overlay: FPS, frame time, batch apply-latency (p50/p95),
   dropped frames, batches/s + stress presets. Each app calls recordLatency(ms) after it
   has applied a stream batch, and recordBatch() once per batch. Mount once. */

export interface Perf {
  recordLatency(ms: number): void;
  recordBatch(): void;
  mount(onStress: (rows: number, rate: number) => void, onMode?: (m: string) => void): HTMLElement;
}

export function createPerf(label = ""): Perf {
  const lat: number[] = [];
  let batches = 0, frames = 0, dropped = 0, lastFrame = performance.now(), fps = 0, frameMs = 0, bps = 0;
  let elFps: HTMLElement, elFrame: HTMLElement, elP50: HTMLElement, elP95: HTMLElement, elDrop: HTMLElement, elBps: HTMLElement, elRows: HTMLElement, elRate: HTMLElement;
  let curRows = 200, curRate = 30;

  function loop() {
    const now = performance.now();
    const dt = now - lastFrame; lastFrame = now;
    frames++;
    if (dt > 1000 / 30) dropped++;            // missed ~30fps budget
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  setInterval(() => {
    fps = frames; frameMs = frames ? +(1000 / frames).toFixed(1) : 0; bps = batches;
    frames = 0; batches = 0;
    const sorted = lat.slice().sort((a, b) => a - b);
    const p = (q: number) => sorted.length ? +sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))].toFixed(1) : 0;
    if (elFps) {
      elFps.textContent = fps + " fps";
      elFrame.textContent = frameMs + " ms";
      elP50.textContent = p(0.5) + " ms";
      elP95.textContent = p(0.95) + " ms";
      elDrop.textContent = String(dropped);
      elBps.textContent = bps + "/s";
      elFps.style.color = fps >= 55 ? "var(--green)" : fps >= 30 ? "var(--amber)" : "var(--red)";
    }
    lat.length = 0; dropped = 0;
  }, 1000);

  return {
    recordLatency(ms) { if (isFinite(ms) && ms >= 0) lat.push(ms); },
    recordBatch() { batches++; },
    mount(onStress, onMode) {
      const el = document.createElement("div");
      el.className = "perf";
      el.innerHTML =
        `<div class="ph">PERF ${label}<span class="fps" id="pf-fps">– fps</span></div>` +
        `<div class="body">` +
        `<span class="l">frame</span><span class="v" id="pf-frame">–</span>` +
        `<span class="l">apply p50</span><span class="v" id="pf-p50">–</span>` +
        `<span class="l">apply p95</span><span class="v" id="pf-p95">–</span>` +
        `<span class="l">dropped/s</span><span class="v" id="pf-drop">–</span>` +
        `<span class="l">batches</span><span class="v" id="pf-bps">–</span>` +
        `<span class="l">rows×rate</span><span class="v"><b id="pf-rows">200</b>×<b id="pf-rate">30</b></span>` +
        `</div>` +
        `<div class="ctrl"><span>ROWS</span>${[100,1000,10000].map(n=>`<button data-rows="${n}">${n>=1000?(n/1000)+"k":n}</button>`).join("")}</div>` +
        `<div class="ctrl"><span>UPDATES/SEC</span>${[1,10,60,240].map(r=>`<button data-rate="${r}">${r}</button>`).join("")}</div>` +
        `<div class="ctrl"><span>SOURCE</span><button data-mode="synthetic" class="on">synthetic</button><button data-mode="poll">real (poll)</button></div>`;
      document.body.appendChild(el);
      elFps = el.querySelector("#pf-fps")!; elFrame = el.querySelector("#pf-frame")!; elP50 = el.querySelector("#pf-p50")!;
      elP95 = el.querySelector("#pf-p95")!; elDrop = el.querySelector("#pf-drop")!; elBps = el.querySelector("#pf-bps")!;
      elRows = el.querySelector("#pf-rows")!; elRate = el.querySelector("#pf-rate")!;
      el.querySelectorAll("[data-rows]").forEach(b => b.addEventListener("click", () => { curRows = +(b as HTMLElement).dataset.rows!; elRows.textContent = String(curRows); onStress(curRows, curRate); }));
      el.querySelectorAll("[data-rate]").forEach(b => b.addEventListener("click", () => { curRate = +(b as HTMLElement).dataset.rate!; elRate.textContent = String(curRate); onStress(curRows, curRate); }));
      el.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => {
        el.querySelectorAll("[data-mode]").forEach(x => x.classList.remove("on")); b.classList.add("on");
        onMode && onMode((b as HTMLElement).dataset.mode!);
      }));
      return el;
    },
  };
}
