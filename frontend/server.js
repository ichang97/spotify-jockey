const express = require("express");
const path = require("path");
const expressLayouts = require("express-ejs-layouts");
const axios = require("axios");
const { createProxyMiddleware } = require("http-proxy-middleware");
require("dotenv").config({ path: path.join(__dirname, "../.env") });

const app = express();
app.set("trust proxy", 1);
const PORT = process.env.FRONTEND_PORT || 3000;
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";
const BACKEND_PUBLIC_URL = process.env.BACKEND_PUBLIC_URL || "";

const apiProxy = createProxyMiddleware({
  target: BACKEND_URL,
  changeOrigin: true,
  xfwd: true
});

const wsProxy = createProxyMiddleware({
  target: BACKEND_URL,
  changeOrigin: true,
  ws: true,
  xfwd: true
});

app.disable("x-powered-by");

app.use((req, res, next) => {
  res.setHeader("X-Frame-Options", "SAMEORIGIN");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(self), display-capture=(self)");
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss: https://api.spotify.com https://itunes.apple.com https://*.googlevideo.com; img-src 'self' data: https://*.scdn.co https://*.spotifycdn.com https://*.mzstatic.com https://*.ytimg.com; media-src 'self' blob: https://*.scdn.co https://*.apple.com https://*.mzstatic.com https://*.dzcdn.net https://*.googlevideo.com;"
  );
  next();
});

app.use("/api", apiProxy);
app.use("/ws", wsProxy);

app.use(express.json({ limit: "100kb" }));
app.use(express.urlencoded({ extended: true, limit: "100kb" }));
app.use(express.static(path.join(__dirname, "public")));
app.use("/js", express.static(path.join(__dirname, "src/js")));

app.use(expressLayouts);
app.set("views", path.join(__dirname, "views"));
app.set("view engine", "ejs");
app.set("layout", "layouts/main");

app.use(async (req, res, next) => {
  const protocol = req.headers["x-forwarded-proto"] || req.protocol;
  const host = req.headers["x-forwarded-host"] || req.get("host");
  res.locals.backendPublicUrl = BACKEND_PUBLIC_URL || `${protocol}://${host}`;
  res.locals.currentPath = req.path;
  next();
});

app.get("/", async (req, res) => {
  try {
    const response = await axios.get(`${BACKEND_URL}/api/stations`);
    res.render("pages/index", {
      title: "Spotify Jockey - Radio Stations",
      stations: response.data || [],
      error: req.query.error || null
    });
  } catch (err) {
    res.render("pages/index", {
      title: "Spotify Jockey - Radio Stations",
      stations: [],
      error: "Unable to connect to backend service"
    });
  }
});

app.post("/stations/create", async (req, res) => {
  const { name, slug, description, passcode } = req.body;
  try {
    const clientIp = req.ip || req.socket.remoteAddress || "127.0.0.1";
    await axios.post(
      `${BACKEND_URL}/api/stations`,
      {
        name,
        slug: slug.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
        description,
        passcode: passcode || undefined
      },
      {
        headers: {
          "x-forwarded-for": clientIp
        }
      }
    );
    res.redirect(`/studio/${slug}`);
  } catch (err) {
    res.redirect(`/?error=${encodeURIComponent(err.response?.data?.detail || "Creation failed")}`);
  }
});

app.get("/studio/:slug", async (req, res) => {
  const { slug } = req.slug || req.params;
  try {
    const stationRes = await axios.get(`${BACKEND_URL}/api/stations/${slug}`);
    res.render("pages/studio", {
      title: `DJ Studio - ${stationRes.data.name}`,
      station: stationRes.data,
      connected: req.query.connected === "true",
      error: req.query.error || null
    });
  } catch (err) {
    res.status(404).render("pages/index", {
      title: "Not Found",
      stations: [],
      error: `Station '${slug}' not found`
    });
  }
});

app.get("/live/:slug", async (req, res) => {
  const { slug } = req.params;
  try {
    const stationRes = await axios.get(`${BACKEND_URL}/api/stations/${slug}`);
    res.render("pages/listener", {
      title: `${stationRes.data.name} - Live Radio`,
      station: stationRes.data
    });
  } catch (err) {
    res.status(404).render("pages/index", {
      title: "Not Found",
      stations: [],
      error: `Station '${slug}' not found`
    });
  }
});

app.get("/settings/:slug", async (req, res) => {
  const { slug } = req.params;
  try {
    const stationRes = await axios.get(`${BACKEND_URL}/api/stations/${slug}`);
    res.render("pages/settings", {
      title: `Settings - ${stationRes.data.name}`,
      station: stationRes.data
    });
  } catch (err) {
    res.status(404).render("pages/index", {
      title: "Not Found",
      stations: [],
      error: `Station '${slug}' not found`
    });
  }
});

app.get("/auth/spotify/callback", (req, res) => {
  const queryStr = req.url.includes("?") ? req.url.slice(req.url.indexOf("?")) : "";
  const target = BACKEND_PUBLIC_URL ? `${BACKEND_PUBLIC_URL}/api/auth/spotify/callback${queryStr}` : `/api/auth/spotify/callback${queryStr}`;
  res.redirect(target);
});

const server = app.listen(PORT, "0.0.0.0", () => {
  console.log(`Frontend server running on port ${PORT}`);
});

server.on("upgrade", (req, socket, head) => {
  if (req.url && req.url.startsWith("/ws")) {
    wsProxy.upgrade(req, socket, head);
  }
});
