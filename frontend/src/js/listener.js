import { applyPalette } from "./theme.js";

class LiveStreamPlayer {
  constructor() {
    this.audio = new Audio();
    this.mediaSource = null;
    this.sourceBuffer = null;
    this.abortController = null;
    this.queue = [];
    this.isStreaming = false;
    this.hasStartedPlaying = false;
    this.mediaSourceUrl = null;
    this.onAutoplayBlocked = null;
  }

  async play(streamUrl) {
    if (this.isStreaming) return;
    this.stop();
    this.isStreaming = true;
    this.hasStartedPlaying = false;
    this.abortController = new AbortController();

    const isSupported = window.MediaSource && (
      MediaSource.isTypeSupported("audio/webm; codecs=opus") ||
      MediaSource.isTypeSupported("audio/webm;codecs=opus") ||
      MediaSource.isTypeSupported("audio/webm")
    );

    if (isSupported) {
      try {
        return await this._playMediaSource(streamUrl);
      } catch (err) {
        if (err.name === "AbortError") return;
        this.stop();
        if (err.status) {
          throw err;
        }
        this.isStreaming = true;
        this.abortController = new AbortController();
        this.audio.src = streamUrl;
        return this.audio.play();
      }
    } else {
      this.audio.src = streamUrl;
      return this.audio.play();
    }
  }

  _playMediaSource(streamUrl) {
    return new Promise((resolve, reject) => {
      this.mediaSource = new MediaSource();
      this.mediaSourceUrl = URL.createObjectURL(this.mediaSource);
      this.audio.src = this.mediaSourceUrl;

      let resolved = false;

      this.audio.addEventListener("waiting", () => {
        if (this.isStreaming && this.sourceBuffer && this.sourceBuffer.buffered.length > 0) {
          const start = this.sourceBuffer.buffered.start(0);
          const end = this.sourceBuffer.buffered.end(this.sourceBuffer.buffered.length - 1);
          if (end - start >= 1.0) {
            this.audio.currentTime = Math.max(start, end - 1.2);
            this.audio.play().catch(() => {});
          }
        }
      });

      this.mediaSource.addEventListener("sourceopen", async () => {
        try {
          const mimeType = MediaSource.isTypeSupported("audio/webm; codecs=opus")
            ? "audio/webm; codecs=opus"
            : (MediaSource.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm");
          this.sourceBuffer = this.mediaSource.addSourceBuffer(mimeType);
          this.sourceBuffer.mode = "segments";

          this.sourceBuffer.addEventListener("updateend", () => {
            if (this.sourceBuffer && this.sourceBuffer.buffered.length > 0) {
              const bufStart = this.sourceBuffer.buffered.start(0);
              const bufEnd = this.sourceBuffer.buffered.end(this.sourceBuffer.buffered.length - 1);

              if (!this.hasStartedPlaying) {
                if (bufEnd - bufStart >= 1.0) {
                  const targetTime = Math.max(bufStart, bufEnd - 1.2);
                  this.audio.currentTime = targetTime;
                  this.hasStartedPlaying = true;
                  const p = this.audio.play();
                  if (p && typeof p.catch === "function") {
                    p.catch((err) => {
                      if (err.name === "NotAllowedError" && this.onAutoplayBlocked) {
                        this.onAutoplayBlocked();
                      }
                    });
                  }
                  if (!resolved) {
                    resolved = true;
                    resolve();
                  }
                }
              } else {
                if (this.audio.paused) {
                  const p = this.audio.play();
                  if (p && typeof p.catch === "function") {
                    p.catch((err) => {
                      if (err.name === "NotAllowedError" && this.onAutoplayBlocked) {
                        this.onAutoplayBlocked();
                      }
                    });
                  }
                }
                if (this.audio.currentTime < bufStart || bufEnd - this.audio.currentTime > 4.0) {
                  this.audio.currentTime = Math.max(bufStart, bufEnd - 1.2);
                }
              }
            }
            this._flushQueue();
          });

          const response = await fetch(streamUrl, {
            signal: this.abortController.signal
          });

          if (!response.ok) {
            let errorMsg = response.status === 503 ? "Station is currently offline. Live stream is not active." : `Server error (${response.status})`;
            try {
              const data = await response.json();
              if (data && data.detail) {
                errorMsg = data.detail;
              }
            } catch (_) {}
            const httpErr = new Error(errorMsg);
            httpErr.status = response.status;
            throw httpErr;
          }

          const reader = response.body.getReader();
          this._pumpStream(reader);

          setTimeout(() => {
            if (!resolved && this.isStreaming) {
              if (this.sourceBuffer && this.sourceBuffer.buffered.length > 0) {
                const s = this.sourceBuffer.buffered.start(0);
                const e = this.sourceBuffer.buffered.end(this.sourceBuffer.buffered.length - 1);
                if (e - s >= 0.5) {
                  this.audio.currentTime = Math.max(s, e - 1.2);
                }
              }
              this.audio.play().catch(() => {});
              this.hasStartedPlaying = true;
              resolved = true;
              resolve();
            }
          }, 2000);
        } catch (err) {
          if (!resolved) {
            resolved = true;
            reject(err);
          }
        }
      }, { once: true });
    });
  }

  async _pumpStream(reader) {
    try {
      while (this.isStreaming) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value && value.length > 0) {
          this.queue.push(value);
          this._flushQueue();
        }
      }
    } catch (e) {
    } finally {
      try {
        reader.cancel();
      } catch (e) {}
    }
  }

  _flushQueue() {
    if (!this.sourceBuffer || this.sourceBuffer.updating || this.queue.length === 0) {
      return;
    }
    try {
      const chunk = this.queue.shift();
      this.sourceBuffer.appendBuffer(chunk);
    } catch (e) {
    }
  }

  stop() {
    this.isStreaming = false;
    this.hasStartedPlaying = false;
    if (this.abortController) {
      try {
        this.abortController.abort();
      } catch (e) {}
      this.abortController = null;
    }
    this.queue = [];
    if (this.audio) {
      try {
        this.audio.pause();
        this.audio.removeAttribute("src");
        this.audio.load();
      } catch (e) {}
    }
    if (this.mediaSourceUrl) {
      try {
        URL.revokeObjectURL(this.mediaSourceUrl);
      } catch (e) {}
      this.mediaSourceUrl = null;
    }
    this.sourceBuffer = null;
    this.mediaSource = null;
  }

  setVolume(vol) {
    if (this.audio) {
      this.audio.volume = vol;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const stationSlug = window.STATION_SLUG;
  const backendWsUrl = window.BACKEND_WS_URL;
  const stationPalette = window.STATION_PALETTE;

  if (stationPalette) {
    applyPalette(stationPalette);
  }

  const streamPlayer = new LiveStreamPlayer();
  let isListening = false;
  let isConnecting = false;

  const btnPlayStream = document.getElementById("btnPlayStream");
  const volumeSlider = document.getElementById("volumeSlider");
  const streamStatusBadge = document.getElementById("streamStatusBadge");
  const waveformContainer = document.getElementById("waveformContainer");

  streamPlayer.onAutoplayBlocked = () => {
    isListening = false;
    btnPlayStream.disabled = false;
    btnPlayStream.innerHTML = "<span>🔊 คลิกเพื่อเปิดเสียงสด (Unmute)</span>";
    btnPlayStream.className = "btn btn-warning btn-lg w-100 py-3 fw-bold";
  };

  const nowPlayingTitle = document.getElementById("nowPlayingTitle");
  const nowPlayingArtist = document.getElementById("nowPlayingArtist");
  const nowPlayingAlbum = document.getElementById("nowPlayingAlbum");
  const nowPlayingArt = document.getElementById("nowPlayingArt");
  const nowPlayingPlaceholder = document.getElementById("nowPlayingPlaceholder");
  const upNextContainer = document.getElementById("upNextContainer");
  const upNextTrack = document.getElementById("upNextTrack");

  const requestSearchInput = document.getElementById("requestSearchInput");
  const btnRequestSearch = document.getElementById("btnRequestSearch");
  const requestSearchResults = document.getElementById("requestSearchResults");
  const requesterNameInput = document.getElementById("requesterNameInput");
  const requestSuccessAlert = document.getElementById("requestSuccessAlert");

  const chatMessages = document.getElementById("chatMessages");
  const chatSenderName = document.getElementById("chatSenderName");
  const chatInput = document.getElementById("chatInput");
  const btnSendChat = document.getElementById("btnSendChat");

  const streamOfflineAlert = document.getElementById("streamOfflineAlert");
  const streamOfflineMessage = document.getElementById("streamOfflineMessage");

  function showStreamAlert(msg) {
    if (streamOfflineAlert) {
      if (streamOfflineMessage && msg) {
        streamOfflineMessage.innerText = msg;
      }
      streamOfflineAlert.classList.remove("d-none");
    }
  }

  function hideStreamAlert() {
    if (streamOfflineAlert) {
      streamOfflineAlert.classList.add("d-none");
    }
  }

  initWebSocket();
  loadChat();
  checkInitialStreamStatus();
  loadUpNext();

  async function startListeningStream() {
    if (isListening || isConnecting) return;
    isConnecting = true;
    btnPlayStream.disabled = true;
    try {
      hideStreamAlert();
      await streamPlayer.play(`/api/stations/${stationSlug}/stream?t=${Date.now()}`);
      isListening = true;
      btnPlayStream.disabled = false;
      btnPlayStream.innerHTML = "<span>⏸ Pause Broadcast</span>";
      btnPlayStream.className = "btn sj-btn-live btn-lg w-100 py-3";
      streamStatusBadge.className = "badge bg-danger ms-2";
      streamStatusBadge.innerText = "STREAMING LIVE";
      waveformContainer.classList.remove("d-none");
    } catch (err) {
      if (err.name === "NotAllowedError") {
        isListening = false;
        btnPlayStream.disabled = false;
        btnPlayStream.innerHTML = "<span>🔊 คลิกเพื่อเปิดเสียงสด (Unmute)</span>";
        btnPlayStream.className = "btn btn-warning btn-lg w-100 py-3 fw-bold";
      } else if (err.status === 503 || (err.message && err.message.toLowerCase().includes("offline"))) {
        btnPlayStream.disabled = false;
        btnPlayStream.innerHTML = "<span>▶ Listen Live Stream</span>";
        btnPlayStream.className = "btn sj-btn-accent btn-lg w-100 py-3";
        streamStatusBadge.className = "badge bg-secondary ms-2";
        streamStatusBadge.innerText = "OFFLINE";
        waveformContainer.classList.add("d-none");
        showStreamAlert("ดีเจยังไม่ออนไลน์ในขณะนี้ กรุณารอสักครู่หรือกลับมาใหม่ภายหลัง");
      } else if (err.name !== "AbortError") {
        btnPlayStream.disabled = false;
        btnPlayStream.innerHTML = "<span>▶ Listen Live Stream</span>";
        btnPlayStream.className = "btn sj-btn-accent btn-lg w-100 py-3";
        waveformContainer.classList.add("d-none");
        showStreamAlert(err.message || "ไม่สามารถเชื่อมต่อสัญญาณเสียงได้ในขณะนี้");
      }
      isListening = false;
    } finally {
      isConnecting = false;
    }
  }

  function pauseListeningStream() {
    isConnecting = false;
    if (!isListening) return;
    streamPlayer.stop();
    isListening = false;
    btnPlayStream.disabled = false;
    btnPlayStream.innerHTML = "<span>▶ Listen Live Stream</span>";
    btnPlayStream.className = "btn sj-btn-accent btn-lg w-100 py-3";
    streamStatusBadge.className = "badge bg-secondary ms-2";
    streamStatusBadge.innerText = "PAUSED";
    waveformContainer.classList.add("d-none");
  }

  async function checkInitialStreamStatus() {
    try {
      const res = await fetch(`/api/stations/${stationSlug}/stream/status`);
      if (res.ok) {
        const data = await res.json();
        if (data.is_broadcasting) {
          hideStreamAlert();
          streamStatusBadge.className = "badge bg-danger ms-2";
          streamStatusBadge.innerText = "STREAMING LIVE";
          startListeningStream();
        } else {
          streamStatusBadge.className = "badge bg-secondary ms-2";
          streamStatusBadge.innerText = "OFFLINE";
        }
      }
    } catch (e) {}
  }

  btnPlayStream.addEventListener("click", () => {
    if (!isListening) {
      startListeningStream();
    } else {
      pauseListeningStream();
    }
  });

  volumeSlider.addEventListener("input", (e) => {
    streamPlayer.setVolume(parseFloat(e.target.value));
  });

  btnRequestSearch.addEventListener("click", performRequestSearch);
  requestSearchInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") performRequestSearch();
  });

  async function performRequestSearch() {
    const q = requestSearchInput.value.trim();
    if (!q) return;

    requestSearchResults.innerHTML = '<div class="text-center py-2 sj-text-muted small">Searching...</div>';

    try {
      const res = await fetch(`/api/spotify/${stationSlug}/search?q=${encodeURIComponent(q)}&limit=6`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      renderRequestResults(data.tracks || []);
    } catch (err) {
      requestSearchResults.innerHTML = `<div class="alert alert-danger py-1 small">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderRequestResults(tracks) {
    if (tracks.length === 0) {
      requestSearchResults.innerHTML = '<div class="text-center py-2 sj-text-muted small">No tracks found</div>';
      return;
    }

    requestSearchResults.innerHTML = "";
    tracks.forEach(track => {
      const item = document.createElement("div");
      item.className = "d-flex align-items-center justify-content-between p-2 mb-2 rounded sj-bg-surface sj-border";

      const left = document.createElement("div");
      left.className = "d-flex align-items-center";

      const img = document.createElement("img");
      img.src = track.album_art_url || "";
      img.className = "sj-cover-art-sm me-2";
      img.alt = track.title;

      const details = document.createElement("div");
      const title = document.createElement("div");
      title.className = "small fw-semibold sj-text-main";
      title.innerText = track.title;

      const artist = document.createElement("div");
      artist.className = "small sj-text-muted";
      artist.innerText = track.artist;

      details.appendChild(title);
      details.appendChild(artist);
      left.appendChild(img);
      left.appendChild(details);

      const btnRequest = document.createElement("button");
      btnRequest.className = "btn btn-sm sj-btn-outline";
      btnRequest.innerText = "Request";
      btnRequest.onclick = () => submitSongRequest(track);

      item.appendChild(left);
      item.appendChild(btnRequest);
      requestSearchResults.appendChild(item);
    });
  }

  async function submitSongRequest(track) {
    const name = requesterNameInput.value.trim() || "Anonymous Listener";
    try {
      const res = await fetch(`/api/stations/${stationSlug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester_name: name,
          spotify_track_id: track.id,
          track_title: track.title,
          track_artist: track.artist,
          album_art_url: track.album_art_url
        })
      });

      if (res.ok) {
        requestSearchResults.innerHTML = "";
        requestSearchInput.value = "";
        requestSuccessAlert.classList.remove("d-none");
        setTimeout(() => requestSuccessAlert.classList.add("d-none"), 4000);
      }
    } catch (e) {
      alert("Failed to submit request");
    }
  }

  async function loadChat() {
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

  btnSendChat.addEventListener("click", sendChat);
  chatInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendChat();
  });

  async function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    const name = chatSenderName.value.trim() || "Listener";
    chatInput.value = "";

    try {
      await fetch(`/api/stations/${stationSlug}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_name: name,
          message: text,
          is_dj: false
        })
      });
    } catch (e) {}
  }

  function initWebSocket() {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = backendWsUrl || `${wsProtocol}//${window.location.host}/ws`;
    const socket = new WebSocket(`${wsHost}/stations/${stationSlug}`);

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "queue_updated") {
          loadUpNext();
        } else if (msg.type === "now_playing") {
          loadUpNext();
          updateNowPlaying(msg.data);
          if (msg.data && msg.data.is_playing) {
            hideStreamAlert();
            startListeningStream();
          } else if (msg.data && msg.data.is_playing === false) {
            pauseListeningStream();
          }
        } else if (msg.type === "chat_message") {
          appendChatMessage(msg.data);
        } else if (msg.type === "station_status") {
          if (msg.data && msg.data.is_live) {
            hideStreamAlert();
            streamStatusBadge.className = "badge bg-danger ms-2";
            streamStatusBadge.innerText = "STREAMING LIVE";
            startListeningStream();
          } else {
            streamStatusBadge.className = "badge bg-secondary ms-2";
            streamStatusBadge.innerText = "OFFLINE";
            waveformContainer.classList.add("d-none");
            pauseListeningStream();
            if (msg.data && msg.data.deleted) {
              alert("สถานีนี้ถูกลบแล้ว");
              window.location.href = "/";
              return;
            }
            showStreamAlert("ดีเจสิ้นสุดการถ่ายทอดสดแล้ว");
          }
        }
      } catch (e) {}
    };

    socket.onclose = () => {
      setTimeout(initWebSocket, 3000);
    };
  }

  function updateNowPlaying(data) {
    if (!data || !data.track) {
      nowPlayingTitle.innerText = "No track playing";
      nowPlayingArtist.innerText = "Stay tuned";
      nowPlayingAlbum.innerText = "";
      nowPlayingArt.classList.add("d-none");
      nowPlayingPlaceholder.classList.remove("d-none");
      return;
    }

    const track = data.track;
    nowPlayingTitle.innerText = track.title;
    nowPlayingArtist.innerText = track.artist;
    nowPlayingAlbum.innerText = track.album || "";

    if (track.album_art_url) {
      nowPlayingArt.src = track.album_art_url;
      nowPlayingArt.classList.remove("d-none");
      nowPlayingPlaceholder.classList.add("d-none");
    } else {
      nowPlayingArt.classList.add("d-none");
      nowPlayingPlaceholder.classList.remove("d-none");
    }
  }

  async function loadUpNext() {
    try {
      const res = await fetch(`/api/stations/${stationSlug}/queue`);
      if (res.ok) {
        const data = await res.json();
        updateUpNext(data.up_next);
        if (data.current_track && (!nowPlayingTitle.innerText || nowPlayingTitle.innerText === "Live Broadcast")) {
          updateNowPlaying({ track: data.current_track });
        }
      }
    } catch (e) {}
  }

  function updateUpNext(upNext) {
    if (!upNextContainer || !upNextTrack) return;
    if (upNext && upNext.title) {
      upNextTrack.innerText = `${upNext.title} - ${upNext.artist}`;
      upNextContainer.classList.remove("d-none");
    } else {
      upNextContainer.classList.add("d-none");
      upNextTrack.innerText = "";
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.innerText = str;
    return div.innerHTML;
  }
});
