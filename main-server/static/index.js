const phoneEl = document.getElementById("phone");
const sendBtn = document.getElementById("send-btn");
const statusEl = document.getElementById("status");

function setStatus(msg, ok = false) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (ok ? " ok" : "");
}

sendBtn.addEventListener("click", async () => {
  const phone = phoneEl.value.trim();
  if (!phone) return setStatus("Enter a phone number first.");

  sendBtn.disabled = true;
  setStatus("Sending…");

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
      return;
    }

    sessionStorage.setItem("otp_phone", phone);
    window.location.href = "/verify";
  } catch (e) {
    setStatus("Network error — please try again.");
  } finally {
    sendBtn.disabled = false;
  }
});
