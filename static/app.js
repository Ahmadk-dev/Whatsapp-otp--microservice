const $ = (id) => document.getElementById(id);
const stepPhone = $("step-phone");
const stepCode = $("step-code");
const stepDone = $("step-done");
const statusEl = $("status");

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

async function sendOtp(phone) {
  setStatus("Sending...");
  $("send-btn").disabled = true;
  $("resend-btn") && ($("resend-btn").disabled = true);
  try {
    await postJson("/api/send-otp", { phone });
    $("phone-echo").textContent = phone;
    show(stepCode);
    setStatus("Code sent. Check WhatsApp.", true);
  } catch (e) {
    setStatus(e.message);
  } finally {
    $("send-btn").disabled = false;
    $("resend-btn") && ($("resend-btn").disabled = false);
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
