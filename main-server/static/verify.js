const phone = sessionStorage.getItem("otp_phone");
const codeEl = document.getElementById("code");
const verifyBtn = document.getElementById("verify-btn");
const resendBtn = document.getElementById("resend-btn");
const statusEl = document.getElementById("status");
const verifySection = document.getElementById("verify-section");
const successSection = document.getElementById("success-section");

if (!phone) {
  window.location.href = "/";
}

document.getElementById("sent-to").textContent =
  `Enter the 6-digit code sent to ${phone} via WhatsApp.`;

function setStatus(msg, ok = false) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (ok ? " ok" : "");
}

function startCooldown(seconds) {
  resendBtn.disabled = true;
  let remaining = seconds;
  resendBtn.textContent = `Resend code (${remaining}s)`;
  const iv = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(iv);
      resendBtn.disabled = false;
      resendBtn.textContent = "Resend code";
    } else {
      resendBtn.textContent = `Resend code (${remaining}s)`;
    }
  }, 1000);
}

verifyBtn.addEventListener("click", async () => {
  const code = codeEl.value.trim();
  if (!code) return setStatus("Enter the code you received.");

  verifyBtn.disabled = true;
  setStatus("Verifying…");

  try {
    const res = await fetch("/api/verify-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, code }),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      const map = {
        invalid: "Invalid code. Please try again.",
        expired: "Code expired. Request a new one.",
        too_many_attempts: "Too many wrong attempts. Request a new code.",
      };
      setStatus(map[data.detail] || data.detail || res.statusText);
      return;
    }

    sessionStorage.removeItem("otp_phone");
    verifySection.hidden = true;
    successSection.hidden = false;
    setStatus("");
  } catch (e) {
    setStatus("Network error — please try again.");
  } finally {
    verifyBtn.disabled = false;
  }
});

resendBtn.addEventListener("click", async () => {
  resendBtn.disabled = true;
  setStatus("Resending…");

  try {
    const res = await fetch("/api/send-otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      const detail = data.detail || res.statusText;
      setStatus(typeof detail === "string" ? detail : JSON.stringify(detail));
      const match = (typeof detail === "string") && detail.match(/wait (\d+) seconds/);
      if (match) startCooldown(parseInt(match[1], 10));
      else resendBtn.disabled = false;
      return;
    }

    setStatus("New code sent. Check WhatsApp.", true);
    startCooldown(60);
  } catch (e) {
    setStatus("Network error — please try again.");
    resendBtn.disabled = false;
  }
});
