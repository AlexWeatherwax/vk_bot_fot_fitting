const express = require("express");
const multer = require("multer");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const PORT = process.env.PORT || 3000;
const DATA_DIR = path.join(__dirname, "data");
const UPLOADS_DIR = path.join(DATA_DIR, "uploads");
const ITEMS_FILE = path.join(DATA_DIR, "items.json");

fs.mkdirSync(UPLOADS_DIR, { recursive: true });
if (!fs.existsSync(ITEMS_FILE)) fs.writeFileSync(ITEMS_FILE, "[]");

const CATEGORIES = [
  { slug: "rings", label: "Кольца" },
  { slug: "earrings", label: "Серьги" },
  { slug: "bracelets", label: "Браслеты" },
  { slug: "necklaces", label: "Колье и цепочки" },
  { slug: "pendants", label: "Кулоны и подвески" },
  { slug: "brooches", label: "Броши" },
  { slug: "watches", label: "Часы" },
  { slug: "other", label: "Другое" },
];
const CATEGORY_SLUGS = new Set(CATEGORIES.map((c) => c.slug));

const EXT_BY_MIME = {
  "image/png": ".png",
  "image/webp": ".webp",
  "image/jpeg": ".jpg",
  "image/gif": ".gif",
};

function readItems() {
  try {
    return JSON.parse(fs.readFileSync(ITEMS_FILE, "utf8"));
  } catch {
    return [];
  }
}

function writeItems(items) {
  // write to a temp file then rename, so a crash mid-write can't corrupt items.json
  const tmp = ITEMS_FILE + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(items, null, 2));
  fs.renameSync(tmp, ITEMS_FILE);
}

const storage = multer.diskStorage({
  destination: UPLOADS_DIR,
  filename: (req, file, cb) => {
    const ext = EXT_BY_MIME[file.mimetype] || path.extname(file.originalname) || "";
    cb(null, crypto.randomUUID() + ext);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 15 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    if (!EXT_BY_MIME[file.mimetype]) {
      return cb(new Error("unsupported_type"));
    }
    cb(null, true);
  },
});

const app = express();

app.use("/uploads", express.static(UPLOADS_DIR, { maxAge: "30d" }));
app.use(express.static(path.join(__dirname, "public")));
app.use(express.json());

app.get("/api/categories", (req, res) => {
  res.json(CATEGORIES);
});

app.get("/api/items", (req, res) => {
  const items = readItems().sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  res.json(items);
});

app.post("/api/items", (req, res) => {
  upload.single("photo")(req, res, (err) => {
    if (err) return handleUploadError(err, res);

    const name = (req.body.name || "").trim();
    const category = CATEGORY_SLUGS.has(req.body.category) ? req.body.category : "other";

    if (!req.file) {
      return res.status(400).json({ error: "Фото обязательно" });
    }
    if (!name) {
      fs.unlink(req.file.path, () => {});
      return res.status(400).json({ error: "Название обязательно" });
    }

    const item = {
      id: crypto.randomUUID(),
      name: name.slice(0, 120),
      category,
      photo: req.file.filename,
      createdAt: new Date().toISOString(),
    };

    const items = readItems();
    items.push(item);
    writeItems(items);

    res.status(201).json(item);
  });
});

app.delete("/api/items/:id", (req, res) => {
  const items = readItems();
  const idx = items.findIndex((it) => it.id === req.params.id);
  if (idx === -1) {
    return res.status(404).json({ error: "Товар не найден" });
  }
  const [removed] = items.splice(idx, 1);
  writeItems(items);
  fs.unlink(path.join(UPLOADS_DIR, removed.photo), () => {});
  res.json({ ok: true });
});

function handleUploadError(err, res) {
  if (err.message === "unsupported_type") {
    return res.status(400).json({ error: "Неподдерживаемый формат файла. Используйте PNG, JPEG, WEBP или GIF." });
  }
  if (err.code === "LIMIT_FILE_SIZE") {
    return res.status(400).json({ error: "Файл слишком большой (максимум 15 МБ)." });
  }
  console.error(err);
  return res.status(500).json({ error: "Внутренняя ошибка сервера" });
}

app.listen(PORT, () => {
  console.log(`Ларец запущен: http://localhost:${PORT}`);
});
