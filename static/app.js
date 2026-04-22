const $ = (id) => document.getElementById(id);
const stepPhone = $("step-phone");
const stepCode = $("step-code");
const stepDone = $("step-done");
const statusEl = $("status");

// Show sandbox join banner if a keyword is configured server-side
fetch("/api/config")
  .then((r) => r.json())
  .then(({ sandbox_number, sandbox_keyword }) => {
    if (!sandbox_keyword) return;
    const number = sandbox_number.replace("+", "");
    const text = encodeURIComponent(sandbox_keyword);
    $("join-link").href = `https://wa.me/${number}?text=${text}`;
    $("sandbox-banner").hidden = false;
  })
  .catch(() => {});

function show(step) {
  for (const s of [stepPhone, stepCode, stepDone]) s.hidden = s !== step;
}

function setStatus(msg, ok = false) {
  statusEl.textContent = msg || "";
  statusEl.classList.toggle("ok", !!ok);
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function startCooldown(seconds) {
  const resend = $("resend-btn");
  if (!resend) return;
  resend.disabled = true;
  let remaining = seconds;
  resend.textContent = `Resend (${remaining}s)`;
  const interval = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(interval);
      resend.disabled = false;
      resend.textContent = "Resend";
    } else {
      resend.textContent = `Resend (${remaining}s)`;
    }
  }, 1000);
}

async function sendOtp(phone) {
  setStatus("Sending...");
  $("send-btn").disabled = true;
  $("resend-btn") && ($("resend-btn").disabled = true);
  try {
    await postJson("/api/send-otp", { phone });
    $("phone-echo").textContent = phone;
    show(stepCode);
    setStatus("Code sent. Check WhatsApp.", true);
    startCooldown(60);
  } catch (e) {
    setStatus(e.message);
    const match = e.message.match(/wait (\d+) seconds/);
    if (match) startCooldown(parseInt(match[1], 10));
  } finally {
    $("send-btn").disabled = false;
  }
}

$("send-btn").addEventListener("click", () => {
  const phone = $("phone").value.trim();
  if (!phone) return setStatus("Enter a phone number first.");
  sendOtp(phone);
});

$("verify-btn").addEventListener("click", async () => {
  const phone = $("phone").value.trim();
  const code = $("code").value.trim();
  if (!code) return setStatus("Enter the code you received.");
  setStatus("Verifying...");
  $("verify-btn").disabled = true;
  try {
    await postJson("/api/verify-otp", { phone, code });
    show(stepDone);
    setStatus("");
  } catch (e) {
    const map = {
      invalid: "Invalid code.",
      expired: "Code expired. Please resend.",
      too_many_attempts: "Too many attempts. Please resend.",
    };
    setStatus(map[e.message] || e.message);
  } finally {
    $("verify-btn").disabled = false;
  }
});

$("resend-btn").addEventListener("click", () => {
  const phone = $("phone").value.trim();
  if (phone) sendOtp(phone);
});

$("restart-btn").addEventListener("click", () => {
  $("phone").value = "";
  $("code").value = "";
  setStatus("");
  show(stepPhone);
});
