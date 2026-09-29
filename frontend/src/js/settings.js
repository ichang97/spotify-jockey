import { applyPalette, PALETTE_PRESETS } from "./theme.js";

document.addEventListener("DOMContentLoaded", () => {
  const stationSlug = window.STATION_SLUG;
  const initialPalette = window.STATION_PALETTE || PALETTE_PRESETS.obsidian;

  applyPalette(initialPalette);

  const presetSelect = document.getElementById("presetSelect");
  const formSettings = document.getElementById("formSettings");
  const saveSuccessAlert = document.getElementById("saveSuccessAlert");
  const btnConnectSpotify = document.getElementById("btnConnectSpotify");
  const btnDisconnectSpotify = document.getElementById("btnDisconnectSpotify");

  const colorInputs = {
    bg_base: document.getElementById("color_bg_base"),
    bg_surface: document.getElementById("color_bg_surface"),
    bg_card: document.getElementById("color_bg_card"),
    border: document.getElementById("color_border"),
    text_main: document.getElementById("color_text_main"),
    text_muted: document.getElementById("color_text_muted"),
    accent: document.getElementById("color_accent"),
    accent_hover: document.getElementById("color_accent_hover"),
    live: document.getElementById("color_live")
  };

  for (const [key, input] of Object.entries(colorInputs)) {
    if (input && initialPalette[key]) {
      input.value = initialPalette[key];
    }
  }

  for (const [key, input] of Object.entries(colorInputs)) {
    if (input) {
      input.addEventListener("input", () => {
        const currentConfig = getCurrentPaletteFromInputs();
        applyPalette(currentConfig);
      });
    }
  }

  if (presetSelect) {
    presetSelect.addEventListener("change", (e) => {
      const selected = e.target.value;
      if (PALETTE_PRESETS[selected]) {
        const p = PALETTE_PRESETS[selected];
        for (const [key, input] of Object.entries(colorInputs)) {
          if (input && p[key]) {
            input.value = p[key];
          }
        }
        applyPalette(p);
      }
    });
  }

  function getCurrentPaletteFromInputs() {
    const palette = {};
    for (const [key, input] of Object.entries(colorInputs)) {
      if (input) {
        palette[key] = input.value;
      }
    }
    return palette;
  }

  if (formSettings) {
    formSettings.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = document.getElementById("stationName").value.trim();
      const description = document.getElementById("stationDescription").value.trim();
      const palette = getCurrentPaletteFromInputs();

      const token = sessionStorage.getItem(`dj_token_${stationSlug}`);
      const headers = { "Content-Type": "application/json" };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      try {
        const res = await fetch(`/api/stations/${stationSlug}`, {
          method: "PATCH",
          headers,
          body: JSON.stringify({
            name,
            description,
            palette_config: palette
          })
        });

        if (res.ok) {
          saveSuccessAlert.classList.remove("d-none");
          setTimeout(() => saveSuccessAlert.classList.add("d-none"), 3000);
        } else if (res.status === 401) {
          alert("Unauthorized. Please unlock the studio with your DJ passcode first.");
          window.location.href = `/studio/${stationSlug}`;
        } else {
          alert("Failed to save station settings");
        }
      } catch (err) {
        alert("Error saving settings: " + err.message);
      }
    });
  }

  if (btnConnectSpotify) {
    btnConnectSpotify.addEventListener("click", async () => {
      const token = sessionStorage.getItem(`dj_token_${stationSlug}`);
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      try {
        const res = await fetch(`/api/auth/spotify/login?station_slug=${stationSlug}`, { headers });
        if (res.ok) {
          const data = await res.json();
          window.location.href = data.auth_url;
        } else if (res.status === 401) {
          alert("Unauthorized. Please unlock the studio with your DJ passcode first.");
          window.location.href = `/studio/${stationSlug}`;
        } else {
          alert("Failed to initiate Spotify login");
        }
      } catch (err) {
        alert("Error connecting Spotify: " + err.message);
      }
    });
  }

  if (btnDisconnectSpotify) {
    btnDisconnectSpotify.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to disconnect Spotify?")) return;
      const token = sessionStorage.getItem(`dj_token_${stationSlug}`);
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      try {
        const res = await fetch(`/api/auth/spotify/disconnect/${stationSlug}`, {
          method: "POST",
          headers
        });
        if (res.ok) {
          window.location.reload();
        } else if (res.status === 401) {
          alert("Unauthorized. Please unlock the studio with your DJ passcode first.");
          window.location.href = `/studio/${stationSlug}`;
        }
      } catch (err) {
        alert("Error disconnecting Spotify: " + err.message);
      }
    });
  }

  const formDeleteStation = document.getElementById("formDeleteStation");
  const deletePasscodeInput = document.getElementById("deletePasscodeInput");
  const deleteErrorAlert = document.getElementById("deleteErrorAlert");
  const btnConfirmDelete = document.getElementById("btnConfirmDelete");

  if (formDeleteStation) {
    formDeleteStation.addEventListener("submit", async (e) => {
      e.preventDefault();
      const passcode = deletePasscodeInput.value.trim();
      if (!passcode) return;

      if (deleteErrorAlert) {
        deleteErrorAlert.classList.add("d-none");
        deleteErrorAlert.innerText = "";
      }
      if (btnConfirmDelete) {
        btnConfirmDelete.disabled = true;
        btnConfirmDelete.innerText = "กำลังลบสถานี...";
      }

      try {
        const verifyRes = await fetch(`/api/stations/${stationSlug}/auth/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ passcode })
        });

        if (!verifyRes.ok) {
          const errData = await verifyRes.json().catch(() => ({}));
          throw new Error(errData.detail || "DJ Passcode ไม่ถูกต้อง");
        }

        const authData = await verifyRes.json();
        const token = authData.token;

        const deleteRes = await fetch(`/api/stations/${stationSlug}`, {
          method: "DELETE",
          headers: {
            "Authorization": `Bearer ${token}`
          }
        });

        if (!deleteRes.ok) {
          const errData = await deleteRes.json().catch(() => ({}));
          throw new Error(errData.detail || "เกิดข้อผิดพลาดในการลบสถานี");
        }

        sessionStorage.removeItem(`dj_token_${stationSlug}`);
        alert("ลบสถานีเรียบร้อยแล้ว");
        window.location.href = "/";
      } catch (err) {
        if (deleteErrorAlert) {
          deleteErrorAlert.innerText = err.message;
          deleteErrorAlert.classList.remove("d-none");
        } else {
          alert(err.message);
        }
      } finally {
        if (btnConfirmDelete) {
          btnConfirmDelete.disabled = false;
          btnConfirmDelete.innerText = "ยืนยันการลบสถานี";
        }
      }
    });
  }
});
