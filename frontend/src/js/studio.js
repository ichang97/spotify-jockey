import { DJAudioEngine } from "./dj-audio.js";
import { applyPalette } from "./theme.js";

document.addEventListener("DOMContentLoaded", () => {
  const stationSlug = window.STATION_SLUG;
  const backendWsUrl = window.BACKEND_WS_URL;
  const stationPalette = window.STATION_PALETTE;

  if (stationPalette) {
    applyPalette(stationPalette);
  }

  const djEngine = new DJAudioEngine();
  let currentTrack = null;
  let queue = [];
  let stationSocket = null;

  const btnGoLive = document.getElementById("btnGoLive");
  const liveBadge = document.getElementById("liveBadge");
  const btnToggleMic = document.getElementById("btnToggleMic");
  const micStatus = document.getElementById("micStatus");
  const btnCaptureMusic = document.getElementById("btnCaptureMusic");
  const musicCaptureStatus = document.getElementById("musicCaptureStatus");

  const micGainSlider = document.getElementById("micGainSlider");
  const musicGainSlider = document.getElementById("musicGainSlider");
  const duckingToggle = document.getElementById("duckingToggle");

  const searchInput = document.getElementById("searchInput");
  const btnSearch = document.getElementById("btnSearch");
  const searchResults = document.getElementById("searchResults");

  const queueList = document.getElementById("queueList");
  const btnClearQueue = document.getElementById("btnClearQueue");
  const requestsList = document.getElementById("requestsList");
  const chatMessages = document.getElementById("chatMessages");
  const chatInput = document.getElementById("chatInput");
  const btnSendChat = document.getElementById("btnSendChat");

  const nowPlayingTitle = document.getElementById("nowPlayingTitle");
  const nowPlayingArtist = document.getElementById("nowPlayingArtist");
  const nowPlayingAlbum = document.getElementById("nowPlayingAlbum");
  const nowPlayingArt = document.getElementById("nowPlayingArt");
  const nowPlayingArtPlaceholder = document.getElementById("nowPlayingArtPlaceholder");
  const progressBar = document.getElementById("progressBar");
  const timeCurrent = document.getElementById("timeCurrent");
  const timeTotal = document.getElementById("timeTotal");
  const btnDeckPlay = document.getElementById("btnDeckPlay");
  const btnDeckNext = document.getElementById("btnDeckNext");
  const spotifyConnectBadge = document.getElementById("spotifyConnectBadge");
  const monitorVolSlider = document.getElementById("monitorVolSlider");
  const monitorVolText = document.getElementById("monitorVolText");
  const monitorAudio = new Audio();
  monitorAudio.crossOrigin = "anonymous";

  if (monitorVolSlider) {
    monitorVolSlider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      djEngine.setMonitorGain(val);
      if (monitorVolText) {
        monitorVolText.innerText = `${Math.round(val * 100)}%`;
      }
    });
  }

  async function checkSpotifyConnectStatus() {
    try {
      const res = await fetch(`/api/spotify/${stationSlug}/librespot/status`);
      if (res.ok) {
        const data = await res.json();
        if (spotifyConnectBadge) {
          if (data.is_running) {
            spotifyConnectBadge.className = "badge bg-success";
            spotifyConnectBadge.innerText = `Connect: ${data.device_name} (Active)`;
          } else if (data.has_credentials) {
            spotifyConnectBadge.className = "badge bg-info";
            spotifyConnectBadge.innerText = `Connect: ${data.device_name} (Ready)`;
          } else {
            spotifyConnectBadge.className = "badge bg-warning text-dark";
            spotifyConnectBadge.innerText = "Connect: Needs Spotify Login";
          }
        }
      }
    } catch (e) {
      if (spotifyConnectBadge) {
        spotifyConnectBadge.className = "badge bg-secondary";
        spotifyConnectBadge.innerText = "Connect: Offline";
      }
    }
  }

  checkSpotifyConnectStatus();
  setInterval(checkSpotifyConnectStatus, 5000);

  const modalAuthElement = document.getElementById("modalAuthDJ");
  const formAuthDJ = document.getElementById("formAuthDJ");
  const authPasscodeInput = document.getElementById("authPasscodeInput");
  const authErrorAlert = document.getElementById("authErrorAlert");
  const btnLockStudio = document.getElementById("btnLockStudio");

  let authModal = null;
  if (modalAuthElement && window.bootstrap) {
    authModal = new window.bootstrap.Modal(modalAuthElement, { backdrop: "static", keyboard: false });
  }

  function getDJToken() {
    return sessionStorage.getItem(`dj_token_${stationSlug}`);
  }

  function setDJToken(token) {
    sessionStorage.setItem(`dj_token_${stationSlug}`, token);
  }

  function clearDJToken() {
    sessionStorage.removeItem(`dj_token_${stationSlug}`);
  }

  function ensureDJAuth() {
    const token = getDJToken();
    if (!token && authModal) {
      authModal.show();
    }
  }

  ensureDJAuth();

  if (formAuthDJ) {
    formAuthDJ.addEventListener("submit", async (e) => {
      e.preventDefault();
      const passcode = authPasscodeInput.value.trim();
      if (!passcode) return;

      try {
        const res = await fetch(`/api/stations/${stationSlug}/auth/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ passcode })
        });

        if (res.ok) {
          const data = await res.json();
          setDJToken(data.token);
          authPasscodeInput.value = "";
          authErrorAlert.classList.add("d-none");
          authModal.hide();
        } else {
          authErrorAlert.classList.remove("d-none");
          authErrorAlert.innerText = "Invalid passcode. Please try again.";
        }
      } catch (err) {
        authErrorAlert.classList.remove("d-none");
        authErrorAlert.innerText = "Error verifying passcode.";
      }
    });
  }

  if (btnLockStudio) {
    btnLockStudio.addEventListener("click", () => {
      clearDJToken();
      if (djEngine.isLive) {
        djEngine.stopBroadcasting();
        btnGoLive.className = "btn sj-btn-accent";
        btnGoLive.innerText = "GO LIVE (ON-AIR)";
        liveBadge.classList.add("d-none");
      }
      if (authModal) {
        authModal.show();
      }
    });
  }

  const deckAudio = new Audio();
  deckAudio.crossOrigin = "anonymous";
  let isPlaying = false;
  let isAdvancingTrack = false;
  let consecutiveErrors = 0;
  let audioErrorTimeout = null;
  let progressInterval = null;
  let currentMs = 0;

  deckAudio.ontimeupdate = () => {
    if (!isPlaying) return;
    if (deckAudio.duration && !isNaN(deckAudio.duration) && deckAudio.duration > 0) {
      currentMs = Math.floor(deckAudio.currentTime * 1000);
      const pct = Math.min(100, (deckAudio.currentTime / deckAudio.duration) * 100);
      progressBar.style.width = `${pct}%`;
      timeCurrent.innerText = formatTime(deckAudio.currentTime);
      timeTotal.innerText = formatTime(deckAudio.duration);
    }
  };

  deckAudio.onended = () => {
    playNextTrack();
  };

  deckAudio.onerror = () => {
    handleAudioError();
  };

  function handleAudioError() {
    if (audioErrorTimeout) clearTimeout(audioErrorTimeout);
    consecutiveErrors++;
    if (consecutiveErrors <= 2) {
      audioErrorTimeout = setTimeout(() => {
        playNextTrack();
      }, 1500);
    } else {
      consecutiveErrors = 0;
      isPlaying = false;
      btnDeckPlay.innerText = "Play";
      deckAudio.pause();
    }
  }

  initStationWebSocket();
  loadRecentRequests();
  loadRecentChat();
  loadQueueAndState();

  if (btnClearQueue) {
    btnClearQueue.addEventListener("click", clearAllQueue);
  }

  btnGoLive.addEventListener("click", async () => {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    djEngine.connectAudioElement(deckAudio);

    if (!djEngine.isLive) {
      try {
        btnGoLive.disabled = true;
        btnGoLive.innerText = "Connecting...";
        await djEngine.startBroadcasting(stationSlug, backendWsUrl, token);
        btnGoLive.disabled = false;
        btnGoLive.className = "btn sj-btn-live";
        btnGoLive.innerText = "STOP BROADCAST";
        liveBadge.classList.remove("d-none");
      } catch (err) {
        alert("Broadcast connection failed: " + err.message);
        btnGoLive.disabled = false;
        btnGoLive.className = "btn sj-btn-accent";
        btnGoLive.innerText = "GO LIVE (ON-AIR)";
        liveBadge.classList.add("d-none");
      }
    } else {
      djEngine.stopBroadcasting();
      btnGoLive.className = "btn sj-btn-accent";
      btnGoLive.innerText = "GO LIVE (ON-AIR)";
      liveBadge.classList.add("d-none");
    }
  });

  btnToggleMic.addEventListener("click", async () => {
    try {
      const active = await djEngine.toggleMicrophone();
      if (active) {
        btnToggleMic.className = "btn btn-danger";
        btnToggleMic.innerText = "Mute Mic";
        micStatus.innerText = "Active";
        micStatus.className = "badge bg-danger ms-2";
      } else {
        btnToggleMic.className = "btn sj-btn-outline";
        btnToggleMic.innerText = "Open Mic";
        micStatus.innerText = "Muted";
        micStatus.className = "badge bg-secondary ms-2";
      }
    } catch (err) {
      alert("Microphone error: " + err.message);
    }
  });

  async function ensureMusicAudioCaptured() {
    if (djEngine.musicStream && djEngine.musicStream.active) {
      return true;
    }
    try {
      btnCaptureMusic.disabled = true;
      btnCaptureMusic.innerText = "Selecting Audio...";
      await djEngine.captureTabMusic();
      btnCaptureMusic.disabled = false;
      btnCaptureMusic.className = "btn btn-success";
      btnCaptureMusic.innerText = "Tab Audio Captured";
      musicCaptureStatus.innerText = "Connected";
      musicCaptureStatus.className = "badge bg-success ms-2";
      return true;
    } catch (err) {
      btnCaptureMusic.disabled = false;
      btnCaptureMusic.className = "btn sj-btn-outline";
      btnCaptureMusic.innerText = "Capture Tab / Spotify Audio";
      musicCaptureStatus.innerText = "Idle";
      musicCaptureStatus.className = "badge bg-secondary ms-2";
      return false;
    }
  }

  btnCaptureMusic.addEventListener("click", () => {
    ensureMusicAudioCaptured();
  });

  micGainSlider.addEventListener("input", (e) => {
    djEngine.setMicGain(e.target.value);
  });

  musicGainSlider.addEventListener("input", (e) => {
    djEngine.setMusicGain(e.target.value);
  });

  duckingToggle.addEventListener("change", (e) => {
    djEngine.autoDuckingEnabled = e.target.checked;
  });

  btnSearch.addEventListener("click", performSearch);
  searchInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") performSearch();
  });

  async function performSearch() {
    const q = searchInput.value.trim();
    if (!q) return;

    searchResults.innerHTML = '<div class="text-center py-3 sj-text-muted">Searching Spotify...</div>';

    try {
      const res = await fetch(`/api/spotify/${stationSlug}/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) {
        let errMsg = `Search failed (${res.status})`;
        try {
          const errData = await res.json();
          errMsg = errData.detail || errMsg;
        } catch (_) {
          const rawText = await res.text();
          if (rawText && !rawText.includes("<!DOCTYPE html>") && !rawText.includes("<html")) {
            errMsg = rawText.slice(0, 150);
          } else if (res.status === 401) {
            errMsg = "Spotify session expired. Please reconnect Spotify in Settings.";
          } else {
            errMsg = `Server error (${res.status}). Please check Spotify connection.`;
          }
        }
        throw new Error(errMsg);
      }
      const data = await res.json();
      renderSearchResults(data.tracks || []);
    } catch (err) {
      searchResults.innerHTML = `<div class="alert alert-danger py-2 mb-0">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderSearchResults(tracks) {
    if (tracks.length === 0) {
      searchResults.innerHTML = '<div class="text-center py-3 sj-text-muted">No tracks found.</div>';
      return;
    }

    searchResults.innerHTML = "";
    tracks.forEach(track => {
      const item = document.createElement("div");
      item.className = "d-flex align-items-center justify-content-between p-2 mb-2 rounded sj-bg-surface sj-border";

      const left = document.createElement("div");
      left.className = "d-flex align-items-center";

      const art = document.createElement("img");
      art.src = track.album_art_url || "";
      art.className = "sj-cover-art-sm me-3";
      art.alt = track.title;

      const details = document.createElement("div");
      const title = document.createElement("div");
      title.className = "fw-semibold sj-text-main";
      title.innerText = track.title;

      const artist = document.createElement("div");
      artist.className = "small sj-text-muted";
      artist.innerText = track.artist;

      details.appendChild(title);
      details.appendChild(artist);
      left.appendChild(art);
      left.appendChild(details);

      const right = document.createElement("div");
      right.className = "btn-group btn-group-sm";

      const btnQueue = document.createElement("button");
      btnQueue.className = "btn sj-btn-outline";
      btnQueue.innerText = "+ Queue";
      btnQueue.onclick = () => {
        addToQueue(track);
      };

      const btnPlayNow = document.createElement("button");
      btnPlayNow.className = "btn sj-btn-accent";
      btnPlayNow.innerText = "Play";
      btnPlayNow.onclick = () => {
        playTrack(track);
      };

      right.appendChild(btnQueue);
      right.appendChild(btnPlayNow);

      item.appendChild(left);
      item.appendChild(right);
      searchResults.appendChild(item);
    });
  }

  async function loadQueueAndState() {
    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue`);
      if (res.ok) {
        const data = await res.json();
        queue = data.queue || [];
        renderQueue();

        if (data.current_track && !currentTrack && !isAdvancingTrack) {
          currentTrack = data.current_track;
          nowPlayingTitle.innerText = currentTrack.title || "Unknown Title";
          nowPlayingArtist.innerText = currentTrack.artist || "Unknown Artist";
          nowPlayingAlbum.innerText = currentTrack.album || "";

          if (currentTrack.album_art_url) {
            nowPlayingArt.src = currentTrack.album_art_url;
            nowPlayingArt.classList.remove("d-none");
            nowPlayingArtPlaceholder.classList.add("d-none");
          } else {
            nowPlayingArt.classList.add("d-none");
            nowPlayingArtPlaceholder.classList.remove("d-none");
          }

          btnDeckPlay.innerText = "Play";
          isPlaying = false;
          let durationMs = currentTrack.duration_ms || 180000;
          timeTotal.innerText = formatTime(durationMs / 1000);
          timeCurrent.innerText = "0:00";
          progressBar.style.width = "0%";

          const queryParams = new URLSearchParams({
            title: currentTrack.title || "",
            artist: currentTrack.artist || "",
            track_id: currentTrack.id || ""
          });
          fetch(`/api/spotify/${stationSlug}/stream-url?${queryParams.toString()}`)
            .then(r => r.ok ? r.json() : null)
            .then(streamData => {
              if (streamData) {
                deckAudio.src = streamData.proxy_url || streamData.stream_url;
              }
            })
            .catch(() => {});
        }
      }
    } catch (e) {}
  }

  function renderQueue() {
    queueList.innerHTML = "";
    if (queue.length === 0) {
      queueList.innerHTML = '<div class="text-center py-4 sj-text-muted small">Queue is empty.</div>';
      return;
    }

    queue.forEach((track, index) => {
      const item = document.createElement("div");
      item.className = "d-flex align-items-center justify-content-between p-2 mb-2 rounded sj-bg-surface sj-border";

      const left = document.createElement("div");
      left.className = "d-flex align-items-center me-2 overflow-hidden";

      const idxBadge = document.createElement("span");
      idxBadge.className = "badge bg-secondary me-2 flex-shrink-0";
      idxBadge.innerText = `#${index + 1}`;

      const details = document.createElement("div");
      details.className = "text-truncate";

      const title = document.createElement("div");
      title.className = "fw-semibold sj-text-main text-truncate small";
      title.innerText = track.title;

      const artist = document.createElement("div");
      artist.className = "small sj-text-muted text-truncate";
      artist.innerText = track.artist;

      details.appendChild(title);
      details.appendChild(artist);
      left.appendChild(idxBadge);
      left.appendChild(details);

      const right = document.createElement("div");
      right.className = "btn-group btn-group-sm flex-shrink-0";

      const btnUp = document.createElement("button");
      btnUp.className = "btn btn-outline-secondary";
      btnUp.innerText = "▲";
      btnUp.title = "Move Up";
      btnUp.disabled = index === 0;
      btnUp.onclick = () => moveQueueItem(index, -1);

      const btnDown = document.createElement("button");
      btnDown.className = "btn btn-outline-secondary";
      btnDown.innerText = "▼";
      btnDown.title = "Move Down";
      btnDown.disabled = index === queue.length - 1;
      btnDown.onclick = () => moveQueueItem(index, 1);

      const btnPlay = document.createElement("button");
      btnPlay.className = "btn sj-btn-accent";
      btnPlay.innerText = "Play";
      btnPlay.onclick = () => playQueueItem(track);

      const btnRemove = document.createElement("button");
      btnRemove.className = "btn btn-outline-danger";
      btnRemove.innerText = "✕";
      btnRemove.title = "Remove";
      btnRemove.onclick = () => removeFromQueue(track.id);

      right.appendChild(btnUp);
      right.appendChild(btnDown);
      right.appendChild(btnPlay);
      right.appendChild(btnRemove);

      item.appendChild(left);
      item.appendChild(right);
      queueList.appendChild(item);
    });
  }

  async function addToQueue(track) {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          title: track.title,
          artist: track.artist,
          spotify_track_id: track.id || track.spotify_track_id || null,
          album: track.album || null,
          album_art_url: track.album_art_url || null,
          preview_url: track.preview_url || null,
          duration_ms: track.duration_ms || 0
        })
      });
      if (res.ok) {
        await loadQueueAndState();
      }
    } catch (e) {}
  }

  async function removeFromQueue(itemId) {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue/${itemId}`, {
        method: "DELETE",
        headers: {
          "Authorization": `Bearer ${token}`
        }
      });
      if (res.ok) {
        await loadQueueAndState();
      }
    } catch (e) {}
  }

  async function moveQueueItem(index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= queue.length) return;
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    const newQueue = [...queue];
    const item = newQueue.splice(index, 1)[0];
    newQueue.splice(targetIndex, 0, item);
    const itemIds = newQueue.map(i => i.id);

    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue/reorder`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ item_ids: itemIds })
      });
      if (res.ok) {
        await loadQueueAndState();
      }
    } catch (e) {}
  }

  async function clearAllQueue() {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue`, {
        method: "DELETE",
        headers: {
          "Authorization": `Bearer ${token}`
        }
      });
      if (res.ok) {
        await loadQueueAndState();
      }
    } catch (e) {}
  }

  async function playQueueItem(item) {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    await removeFromQueue(item.id);
    const track = {
      id: item.spotify_track_id,
      title: item.title,
      artist: item.artist,
      album: item.album,
      album_art_url: item.album_art_url,
      preview_url: item.preview_url,
      duration_ms: item.duration_ms
    };
    await playTrack(track);
  }

  async function playNextTrack() {
    if (isAdvancingTrack) return;
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }

    isAdvancingTrack = true;
    if (btnDeckNext) {
      btnDeckNext.disabled = true;
      btnDeckNext.innerText = "Loading...";
    }

    if (progressInterval) {
      clearInterval(progressInterval);
      progressInterval = null;
    }
    if (audioErrorTimeout) {
      clearTimeout(audioErrorTimeout);
      audioErrorTimeout = null;
    }

    deckAudio.onended = null;
    deckAudio.onerror = null;
    deckAudio.pause();
    deckAudio.removeAttribute("src");
    deckAudio.load();

    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue/next`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        if (data.track) {
          await loadQueueAndState();
          await playTrack(data.track);
        } else {
          currentTrack = null;
          isPlaying = false;
          btnDeckPlay.innerText = "Play";
          if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
          }
          nowPlayingTitle.innerText = "Ready to Broadcast";
          nowPlayingArtist.innerText = "Load track from search or queue";
          nowPlayingAlbum.innerText = "";
          nowPlayingArt.classList.add("d-none");
          nowPlayingArtPlaceholder.classList.remove("d-none");
          progressBar.style.width = "0%";
          timeCurrent.innerText = "0:00";
          timeTotal.innerText = "0:00";
          broadcastNowPlaying();
          await loadQueueAndState();
        }
      }
    } catch (e) {
    } finally {
      isAdvancingTrack = false;
      if (btnDeckNext) {
        btnDeckNext.disabled = false;
        btnDeckNext.innerText = "Next Track ⏭";
      }
    }
  }

  async function updateBackendNowPlaying(track) {
    const token = getDJToken();
    if (!token) return;
    try {
      await fetch(`/api/stations/${stationSlug}/now-playing`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ track })
      });
    } catch (e) {}
  }

  async function ensureLiveBroadcast() {
    const token = getDJToken();
    if (!token || djEngine.isLive) return;
    djEngine.connectAudioElement(deckAudio);
    try {
      btnGoLive.disabled = true;
      btnGoLive.innerText = "Connecting...";
      await djEngine.startBroadcasting(stationSlug, backendWsUrl, token);
      btnGoLive.disabled = false;
      btnGoLive.className = "btn sj-btn-live";
      btnGoLive.innerText = "STOP BROADCAST";
      liveBadge.classList.remove("d-none");
    } catch (e) {
      btnGoLive.disabled = false;
      btnGoLive.className = "btn sj-btn-accent";
      btnGoLive.innerText = "GO LIVE (ON-AIR)";
      liveBadge.classList.add("d-none");
    }
  }

  async function playTrack(track) {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }

    currentTrack = track;
    isPlaying = true;
    updateBackendNowPlaying(track);

    if (!djEngine.audioContext) {
      await djEngine.initAudioContext();
    }
    if (djEngine.audioContext && djEngine.audioContext.state === "suspended") {
      djEngine.audioContext.resume().catch(() => {});
    }
    djEngine.connectAudioElement(deckAudio);

    nowPlayingTitle.innerText = track.title || "Unknown Title";
    nowPlayingArtist.innerText = track.artist || "Unknown Artist";
    nowPlayingAlbum.innerText = track.album || "";

    if (track.album_art_url) {
      nowPlayingArt.src = track.album_art_url;
      nowPlayingArt.classList.remove("d-none");
      nowPlayingArtPlaceholder.classList.add("d-none");
    } else {
      nowPlayingArt.classList.add("d-none");
      nowPlayingArtPlaceholder.classList.remove("d-none");
    }

    btnDeckPlay.innerText = "Pause";
    let durationMs = track.duration_ms || 180000;
    timeTotal.innerText = formatTime(durationMs / 1000);
    timeCurrent.innerText = "0:00";
    progressBar.style.width = "0%";
    currentMs = 0;

    const queryParams = new URLSearchParams({
      title: track.title || "",
      artist: track.artist || "",
      track_id: track.id || ""
    });

    let streamLoaded = false;
    try {
      const res = await fetch(`/api/spotify/${stationSlug}/stream-url?${queryParams.toString()}`);
      if (res.ok) {
        const streamData = await res.json();
        const playUrl = streamData.proxy_url || streamData.stream_url;
        if (playUrl) {
          deckAudio.src = playUrl;
          streamLoaded = true;
          consecutiveErrors = 0;
          deckAudio.play().catch(() => {});
        }
      }
    } catch (e) {}

    deckAudio.onended = () => {
      playNextTrack();
    };

    deckAudio.onerror = () => {
      handleAudioError();
    };

    if (!streamLoaded) {
      handleAudioError();
    }

    if (!streamLoaded) {
      const trackUri = track.uri || (track.id ? `spotify:track:${track.id}` : null);
      try {
        fetch(`/api/spotify/${stationSlug}/play`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({ uri: trackUri })
        }).catch(() => {});
      } catch (e) {}
    }

    ensureLiveBroadcast();
    broadcastNowPlaying();
    startProgressTracker(track.duration_ms || durationMs, 0);
  }

  btnDeckPlay.addEventListener("click", async () => {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return;
    }
    if (!currentTrack) {
      await playNextTrack();
      return;
    }
    djEngine.connectAudioElement(deckAudio);
    if (isPlaying) {
      isPlaying = false;
      btnDeckPlay.innerText = "Play";
      deckAudio.pause();
      if (progressInterval) clearInterval(progressInterval);
      try {
        fetch(`/api/spotify/${stationSlug}/pause`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${token}` }
        }).catch(() => {});
      } catch (e) {}
    } else {
      isPlaying = true;
      btnDeckPlay.innerText = "Pause";
      if (djEngine.audioContext && djEngine.audioContext.state === "suspended") {
        djEngine.audioContext.resume().catch(() => {});
      }
      ensureLiveBroadcast();
      deckAudio.play().catch(() => {});
      try {
        fetch(`/api/spotify/${stationSlug}/resume`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${token}` }
        }).catch(() => {});
      } catch (e) {}
      startProgressTracker(currentTrack.duration_ms || 180000, currentMs);
    }
    broadcastNowPlaying();
  });

  btnDeckNext.addEventListener("click", async () => {
    await playNextTrack();
  });

  function startProgressTracker(durationMs, resumeMs = 0) {
    if (progressInterval) clearInterval(progressInterval);
    currentMs = resumeMs;

    progressInterval = setInterval(() => {
      if (!isPlaying) return;
      if (deckAudio.src && !deckAudio.paused && deckAudio.duration && !isNaN(deckAudio.duration) && deckAudio.duration > 0) {
        return;
      }
      currentMs += 1000;
      if (currentMs > durationMs) {
        currentMs = durationMs;
      }
      const pct = durationMs > 0 ? (currentMs / durationMs) * 100 : 0;
      progressBar.style.width = `${pct}%`;
      timeCurrent.innerText = formatTime(currentMs / 1000);

      if (currentMs >= durationMs) {
        clearInterval(progressInterval);
        progressInterval = null;
        if (!deckAudio.src || deckAudio.paused || deckAudio.ended) {
          playNextTrack();
        }
      }
    }, 1000);
  }

  function broadcastNowPlaying() {
    if (stationSocket && stationSocket.readyState === WebSocket.OPEN) {
      stationSocket.send(JSON.stringify({
        type: "now_playing",
        token: getDJToken(),
        data: {
          track: currentTrack,
          is_playing: isPlaying,
          progress_ms: currentMs,
          timestamp: Date.now()
        }
      }));
    }
  }

  function initStationWebSocket() {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = backendWsUrl || `${wsProtocol}//${window.location.host}/ws`;
    const socketUrl = `${wsHost}/stations/${stationSlug}`;

    stationSocket = new WebSocket(socketUrl);

    stationSocket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "new_request") {
          appendRequestToUI(msg.data);
        } else if (msg.type === "chat_message") {
          appendChatMessage(msg.data);
        } else if (msg.type === "queue_updated") {
          loadQueueAndState();
        } else if (msg.type === "station_status") {
          if (msg.data && msg.data.deleted) {
            clearDJToken();
            alert("สถานีนี้ถูกลบแล้ว");
            window.location.href = "/";
          }
        }
      } catch (e) {}
    };

    stationSocket.onclose = () => {
      setTimeout(initStationWebSocket, 3000);
    };
  }

  async function loadRecentRequests() {
    try {
      const res = await fetch(`/api/stations/${stationSlug}/requests`);
      if (res.ok) {
        const data = await res.json();
        requestsList.innerHTML = "";
        data.forEach(r => appendRequestToUI(r));
      }
    } catch (e) {}
  }

  function appendRequestToUI(req) {
    const item = document.createElement("div");
    item.className = "p-2 mb-2 rounded sj-bg-surface sj-border";
    item.id = `req-${req.id}`;

    const top = document.createElement("div");
    top.className = "d-flex justify-content-between align-items-center mb-1";

    const sender = document.createElement("span");
    sender.className = "fw-semibold sj-accent-color small";
    sender.innerText = req.requester_name;

    const statusBadge = document.createElement("span");
    statusBadge.className = `badge ${getStatusBadgeClass(req.status)}`;
    statusBadge.innerText = req.status;

    top.appendChild(sender);
    top.appendChild(statusBadge);

    const title = document.createElement("div");
    title.className = "small fw-semibold sj-text-main";
    title.innerText = req.track_title;

    const artist = document.createElement("div");
    artist.className = "small sj-text-muted mb-2";
    artist.innerText = req.track_artist;

    const actions = document.createElement("div");
    actions.className = "btn-group btn-group-sm w-100";

    const btnAccept = document.createElement("button");
    btnAccept.className = "btn sj-btn-accent";
    btnAccept.innerText = "Accept & Queue";
    btnAccept.onclick = async () => {
      const ok = await updateRequestStatus(req.id, "accepted");
      if (ok) {
        await addToQueue({
          id: req.spotify_track_id,
          title: req.track_title,
          artist: req.track_artist,
          album_art_url: req.album_art_url
        });
        statusBadge.className = "badge bg-success";
        statusBadge.innerText = "accepted";
        actions.remove();
      }
    };

    const btnReject = document.createElement("button");
    btnReject.className = "btn btn-outline-danger";
    btnReject.innerText = "Reject";
    btnReject.onclick = async () => {
      const ok = await updateRequestStatus(req.id, "rejected");
      if (ok) {
        statusBadge.className = "badge bg-danger";
        statusBadge.innerText = "rejected";
        actions.remove();
      }
    };

    if (req.status === "pending") {
      actions.appendChild(btnAccept);
      actions.appendChild(btnReject);
    }

    item.appendChild(top);
    item.appendChild(title);
    item.appendChild(artist);
    if (req.status === "pending") {
      item.appendChild(actions);
    }

    requestsList.prepend(item);
  }

  function getStatusBadgeClass(status) {
    if (status === "accepted") return "bg-success";
    if (status === "rejected") return "bg-danger";
    if (status === "played") return "bg-info";
    return "bg-warning text-dark";
  }

  async function updateRequestStatus(reqId, status) {
    const token = getDJToken();
    if (!token) {
      if (authModal) authModal.show();
      return false;
    }
    try {
      const res = await fetch(`/api/stations/${stationSlug}/requests/${reqId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ status })
      });
      if (res.status === 401) {
        clearDJToken();
        if (authModal) authModal.show();
        return false;
      }
      return res.ok;
    } catch (e) {
      return false;
    }
  }

  async function loadRecentChat() {
    try {
      const res = await fetch(`/api/stations/${stationSlug}/chat`);
      if (res.ok) {
        const msgs = await res.json();
        chatMessages.innerHTML = "";
        msgs.forEach(m => appendChatMessage(m));
      }
    } catch (e) {}
  }

  function appendChatMessage(msg) {
    const bubble = document.createElement("div");
    bubble.className = "mb-2 p-2 rounded sj-bg-surface sj-border";

    const header = document.createElement("div");
    header.className = "d-flex justify-content-between small mb-1";

    const sender = document.createElement("span");
    sender.className = msg.is_dj ? "fw-bold sj-accent-color" : "fw-bold sj-text-main";
    sender.innerText = msg.is_dj ? `🎧 ${msg.sender_name} (DJ)` : msg.sender_name;

    const time = document.createElement("span");
    time.className = "sj-text-muted";
    time.innerText = new Date(msg.created_at || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    header.appendChild(sender);
    header.appendChild(time);

    const text = document.createElement("div");
    text.className = "small sj-text-main";
    text.innerText = msg.message;

    bubble.appendChild(header);
    bubble.appendChild(text);

    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  btnSendChat.addEventListener("click", sendDJChat);
  chatInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendDJChat();
  });

  async function sendDJChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    const token = getDJToken();
    chatInput.value = "";

    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    try {
      await fetch(`/api/stations/${stationSlug}/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          sender_name: "DJ Live",
          message: text
        })
      });
    } catch (e) {}
  }

  function formatTime(seconds) {
    const s = Math.floor(seconds || 0);
    const mins = Math.floor(s / 60);
    const rem = s % 60;
    return `${mins}:${rem < 10 ? "0" : ""}${rem}`;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.innerText = str;
    return div.innerHTML;
  }
});
