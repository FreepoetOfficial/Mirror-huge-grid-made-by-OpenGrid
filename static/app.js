const WIDTH = 24;
const HEIGHT = 32;
const canvas = document.getElementById("ledCanvas");
const context = canvas.getContext("2d");
let levels = new Uint8Array(WIDTH * HEIGHT);
let demoEnabled = false;
let demoStart = performance.now();
let connected = false;

function draw() {
  const w = canvas.width;
  const h = canvas.height;
  const cellW = w / WIDTH;
  const cellH = h / HEIGHT;
  context.fillStyle = "#030303";
  context.fillRect(0, 0, w, h);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      const value = levels[y * WIDTH + x] / 15;
      const px = (x + 0.5) * cellW;
      const py = (y + 0.5) * cellH;
      const radius = Math.min(cellW, cellH) * 0.23;
      if (value > 0.015) {
        const glow = context.createRadialGradient(px, py, 0, px, py, radius * 2.9);
        glow.addColorStop(0, `rgba(255, 232, 176, ${0.46 * value})`);
        glow.addColorStop(0.35, `rgba(239, 174, 77, ${0.2 * value})`);
        glow.addColorStop(1, "rgba(205, 120, 34, 0)");
        context.fillStyle = glow;
        context.beginPath();
        context.arc(px, py, radius * 2.9, 0, Math.PI * 2);
        context.fill();
      }
      const luminance = Math.round(30 + 225 * value);
      context.fillStyle = value > 0 ? `rgb(${luminance}, ${Math.round(24 + 198 * value)}, ${Math.round(17 + 126 * value)})` : "#171613";
      context.beginPath();
      context.arc(px, py, radius, 0, Math.PI * 2);
      context.fill();
    }
  }
  requestAnimationFrame(draw);
}

function decodeLevels(encoded) {
  const binary = atob(encoded);
  const result = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) result[i] = binary.charCodeAt(i);
  return result;
}

function updateStatus(data) {
  if (!demoEnabled && data.levels) levels = decodeLevels(data.levels);
  document.getElementById("fps").textContent = Number(data.fps || 0).toFixed(1);
  document.getElementById("area").textContent = ((data.area_ratio || 0) * 100).toFixed(1);
  document.getElementById("camera").textContent = data.camera || "--";
  document.getElementById("output").textContent = data.output || "--";
  const statusText = document.getElementById("statusText");
  const statusDot = document.getElementById("statusDot");
  statusDot.classList.add("live");
  if (demoEnabled) {
    statusText.textContent = "浏览器测试动画";
    return;
  }
  if (Number(data.active_ripples || 0) > 0) {
    statusText.textContent = `涟漪扩散 · ${data.active_ripples}`;
  } else if (data.state === "calibrating") {
    statusText.textContent = `采集背景 ${data.calibration_remaining || 0}s`;
  } else if (data.state === "tracking") {
    statusText.textContent = "正在跟随剪影";
  } else {
    statusText.textContent = "等待参与者";
  }
  if (data.hardware_error) {
    document.getElementById("message").textContent = `灯板输出错误：${data.hardware_error}`;
  }
}

const source = new EventSource("/api/stream");
source.onmessage = (event) => {
  connected = true;
  updateStatus(JSON.parse(event.data));
};
source.onerror = () => {
  connected = false;
  if (!demoEnabled) {
    document.getElementById("statusDot").classList.remove("live");
    document.getElementById("statusText").textContent = "后端未连接";
  }
};

function demoFrame(time) {
  if (!demoEnabled) return;
  const t = (time - demoStart) / 1000;
  const next = new Uint8Array(WIDTH * HEIGHT);
  const cx = WIDTH / 2 + Math.sin(t * 0.8) * 4;
  const headY = 8;
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      const head = ((x - cx) ** 2) / 6 + ((y - headY) ** 2) / 8 < 1;
      const torso = ((x - cx) ** 2) / 22 + ((y - 19) ** 2) / 90 < 1;
      const armWave = Math.sin(t * 1.9) * 3;
      const leftArm = Math.abs(y - (12 + (x - (cx - 4)) * 0.55 - armWave)) < 1 && x > cx - 9 && x < cx - 2;
      const rightArm = Math.abs(y - (12 - (x - (cx + 4)) * 0.55 + armWave)) < 1 && x > cx + 2 && x < cx + 9;
      const inside = head || torso || leftArm || rightArm;
      const index = y * WIDTH + x;
      const target = inside ? Number(document.getElementById("brightness").value) : 0;
      next[index] = Math.round(levels[index] + (target - levels[index]) * (target > levels[index] ? 0.24 : 0.08));
    }
  }
  levels = next;
  requestAnimationFrame(demoFrame);
}

document.getElementById("demoButton").addEventListener("click", (event) => {
  demoEnabled = !demoEnabled;
  event.currentTarget.textContent = demoEnabled ? "返回树莓派画面" : "测试动画";
  if (demoEnabled) {
    demoStart = performance.now();
    document.getElementById("statusText").textContent = "浏览器测试动画";
    requestAnimationFrame(demoFrame);
  } else if (!connected) {
    levels.fill(0);
  }
});

document.getElementById("calibrateButton").addEventListener("click", async () => {
  demoEnabled = false;
  document.getElementById("demoButton").textContent = "测试动画";
  await fetch("/api/recalibrate", { method: "POST" });
  document.getElementById("message").textContent = "正在重新采集空场背景，请暂时离开画面。";
});

const bindings = [
  ["threshold", "thresholdValue", "threshold", (v) => v],
  ["rise", "riseValue", "rise_ms", (v) => `${v} ms`],
  ["fall", "fallValue", "fall_ms", (v) => `${v} ms`],
  ["brightness", "brightnessValue", "max_level", (v) => `${v} / 15`],
];
let updateTimer;
for (const [inputId, outputId, key, format] of bindings) {
  const input = document.getElementById(inputId);
  const output = document.getElementById(outputId);
  input.addEventListener("input", () => {
    output.textContent = format(input.value);
    clearTimeout(updateTimer);
    updateTimer = setTimeout(() => {
      fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: Number(input.value) }),
      }).catch(() => {});
    }, 120);
  });
}

fetch("/api/config")
  .then((response) => response.json())
  .then((config) => {
    const values = { threshold: config.threshold, rise: config.rise_ms, fall: config.fall_ms, brightness: config.max_level };
    for (const [inputId, outputId, , format] of bindings) {
      if (values[inputId] !== undefined) {
        document.getElementById(inputId).value = values[inputId];
        document.getElementById(outputId).textContent = format(values[inputId]);
      }
    }
  })
  .catch(() => {});

draw();
