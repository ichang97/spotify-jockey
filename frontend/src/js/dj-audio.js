export class DJAudioEngine {
  constructor() {
    this.audioContext = null;
    this.micStream = null;
    this.musicStream = null;
    this.micGainNode = null;
    this.musicGainNode = null;
    this.monitorGainNode = null;
    this.limiterNode = null;
    this.destNode = null;
    this.analyserNode = null;
    this.mediaRecorder = null;
    this.socket = null;
    this.isLive = false;
    this.isMicActive = false;
    this.autoDuckingEnabled = true;
    this.duckingInterval = null;
    this._connectedAudioElements = new WeakSet();
  }

  async initAudioContext() {
    if (!this.audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: 48000, latencyHint: "playback" });
    }
    this._ensureLimiterAndDestination();
    if (this.audioContext.state === "suspended") {
      try {
        await this.audioContext.resume();
      } catch (e) {}
    }
  }

  _ensureLimiterAndDestination() {
    if (!this.audioContext) return;

    if (!this.limiterNode) {
      this.limiterNode = this.audioContext.createDynamicsCompressor();
      this.limiterNode.threshold.setValueAtTime(-1.0, this.audioContext.currentTime);
      this.limiterNode.knee.setValueAtTime(3.0, this.audioContext.currentTime);
      this.limiterNode.ratio.setValueAtTime(16.0, this.audioContext.currentTime);
      this.limiterNode.attack.setValueAtTime(0.003, this.audioContext.currentTime);
      this.limiterNode.release.setValueAtTime(0.15, this.audioContext.currentTime);
    }

    if (!this.musicGainNode) {
      this.musicGainNode = this.audioContext.createGain();
      this.musicGainNode.gain.setValueAtTime(1.0, this.audioContext.currentTime);
      this.musicGainNode.connect(this.limiterNode);
    }

    if (!this.monitorGainNode) {
      this.monitorGainNode = this.audioContext.createGain();
      this.monitorGainNode.gain.setValueAtTime(1.0, this.audioContext.currentTime);
      this.monitorGainNode.connect(this.audioContext.destination);
    }
  }

  async enableMicrophone() {
    await this.initAudioContext();
    if (!this.micStream) {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          sampleRate: 48000,
          channelCount: 1
        }
      });

      const micSource = this.audioContext.createMediaStreamSource(this.micStream);
      this.micGainNode = this.audioContext.createGain();
      this.micGainNode.gain.setValueAtTime(1.0, this.audioContext.currentTime);
      this.analyserNode = this.audioContext.createAnalyser();
      this.analyserNode.fftSize = 256;

      micSource.connect(this.micGainNode);
      this.micGainNode.connect(this.analyserNode);
      this.micGainNode.connect(this.limiterNode);
    }
    this.isMicActive = true;
    if (this.micGainNode) {
      this.micGainNode.gain.setValueAtTime(1.0, this.audioContext.currentTime);
    }
    this.startAutoDucking();
  }

  disableMicrophone() {
    this.isMicActive = false;
    if (this.micGainNode) {
      this.micGainNode.gain.setValueAtTime(0, this.audioContext.currentTime);
    }
    if (this.musicGainNode && this.audioContext) {
      this.musicGainNode.gain.setTargetAtTime(1.0, this.audioContext.currentTime, 0.1);
    }
  }

  toggleMicrophone() {
    if (this.isMicActive) {
      this.disableMicrophone();
      return false;
    } else {
      if (!this.micStream) {
        return this.enableMicrophone().then(() => true);
      }
      this.isMicActive = true;
      if (this.micGainNode) {
        this.micGainNode.gain.setValueAtTime(1.0, this.audioContext.currentTime);
      }
      return Promise.resolve(true);
    }
  }

  async captureTabMusic() {
    await this.initAudioContext();
    if (this.musicStream && this.musicStream.active) {
      return true;
    }
    const displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: true
    });

    const audioTracks = displayStream.getAudioTracks();
    if (audioTracks.length === 0) {
      displayStream.getTracks().forEach(t => t.stop());
      throw new Error("No audio track selected in screen share dialog");
    }

    displayStream.getVideoTracks().forEach(t => t.stop());

    this.musicStream = new MediaStream(audioTracks);
    const musicSource = this.audioContext.createMediaStreamSource(this.musicStream);
    musicSource.connect(this.musicGainNode);

    audioTracks[0].onended = () => {
      this.musicStream = null;
    };

    return true;
  }

  connectAudioElement(audioElement) {
    if (!audioElement) return;
    this.initAudioContext();
    this._ensureLimiterAndDestination();
    if (this._connectedAudioElements.has(audioElement)) {
      return;
    }
    if (!this.audioContext || !this.musicGainNode || !this.monitorGainNode) {
      return;
    }
    try {
      const source = this.audioContext.createMediaElementSource(audioElement);
      this._connectedAudioElements.add(audioElement);
      source.connect(this.musicGainNode);
      source.connect(this.monitorGainNode);
    } catch (e) {}
  }

  startAutoDucking() {
    if (this.duckingInterval) clearInterval(this.duckingInterval);
    const buffer = new Uint8Array(this.analyserNode.frequencyBinCount);

    this.duckingInterval = setInterval(() => {
      if (!this.autoDuckingEnabled || !this.isMicActive || !this.analyserNode || !this.musicGainNode) {
        return;
      }

      this.analyserNode.getByteFrequencyData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i++) {
        sum += buffer[i];
      }
      const avg = sum / buffer.length;

      const now = this.audioContext.currentTime;
      if (avg > 25) {
        this.musicGainNode.gain.setTargetAtTime(0.25, now, 0.15);
      } else {
        this.musicGainNode.gain.setTargetAtTime(1.0, now, 0.4);
      }
    }, 120);
  }

  setMicGain(value) {
    if (this.micGainNode && this.audioContext) {
      this.micGainNode.gain.setValueAtTime(parseFloat(value), this.audioContext.currentTime);
    }
  }

  setMusicGain(value) {
    if (this.musicGainNode && this.audioContext) {
      this.musicGainNode.gain.setValueAtTime(parseFloat(value), this.audioContext.currentTime);
    }
  }

  setMonitorGain(value) {
    if (this.monitorGainNode && this.audioContext) {
      this.monitorGainNode.gain.setValueAtTime(parseFloat(value), this.audioContext.currentTime);
    }
  }

  async startBroadcasting(slug, backendWsUrl, token) {
    await this.initAudioContext();
    if (!this.destNode) {
      this.destNode = this.audioContext.createMediaStreamDestination();
    }

    try {
      this.limiterNode.disconnect(this.destNode);
    } catch (e) {}
    this.limiterNode.connect(this.destNode);

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = backendWsUrl || `${wsProtocol}//${window.location.host}/ws`;
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : "";
    const audioWsUrl = `${wsHost}/audio/${slug}${tokenParam}`;

    return new Promise((resolve, reject) => {
      this.socket = new WebSocket(audioWsUrl);
      this.socket.binaryType = "arraybuffer";

      this.socket.onopen = () => {
        let mimeType = "audio/webm;codecs=opus";
        if (!MediaRecorder.isTypeSupported(mimeType)) {
          mimeType = "audio/webm";
        }

        this.mediaRecorder = new MediaRecorder(this.destNode.stream, {
          mimeType: mimeType,
          audioBitsPerSecond: 320000
        });

        this.mediaRecorder.ondataavailable = async (e) => {
          if (e.data && e.data.size > 0 && this.socket && this.socket.readyState === WebSocket.OPEN) {
            const buffer = await e.data.arrayBuffer();
            this.socket.send(buffer);
          }
        };

        this.mediaRecorder.start(250);
        this.isLive = true;
        resolve(true);
      };

      this.socket.onerror = (err) => {
        reject(err);
      };

      this.socket.onclose = () => {
        this.stopBroadcasting();
      };
    });
  }

  stopBroadcasting() {
    this.isLive = false;
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.close();
    }
    if (this.duckingInterval) {
      clearInterval(this.duckingInterval);
    }
  }
}
