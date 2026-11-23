// Genere les assets statiques versionnes de l'interface :
//   - static/icons.svg  : sprite des icones Lucide utilisees (liste ICONS)
//   - static/fonts/*    : polices Geist et JetBrains Mono (sous-ensemble latin)
// Le CSS est produit ensuite par le CLI Tailwind (voir package.json).
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
// Icones construites dynamiquement (pas de nom litteral a detecter).
const EXTRA_ICONS = ["circle-check", "circle-alert", "lightbulb", "loader-circle", "circle-dot", "square", "camera-off", "eye", "eye-off", "chevron-up", "chevron-down"];
const staticDir = join(here, "..", "src", "handshortcut", "webui", "static");

// Les icones sont detectees automatiquement dans les sources : un nom d'icone ajoute dans
// un template, un fichier JS ou le catalogue d'etapes (steps.py) est inclus au prochain build.
//   {{ icon("nom") }} | HSC.icon("nom") | icon: "nom" | icon="nom" | data-icon="nom"
const root = join(here, "..", "src", "handshortcut");
const sources = [];
const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "__pycache__") walk(full); }
    else if (/\.(html|js|py)$/.test(entry.name)) sources.push(full);
  }
};
walk(root);
const PATTERNS = [
  /\bicon\(\s*["']([a-z0-9-]+)["']/g,
  /\bicon\s*[=:]\s*["']([a-z0-9-]+)["']/g,
  /data-icon="([a-z0-9-]+)"/g,
  /\bCategory\("[a-z]+",\s*"[^"]*",\s*"([a-z0-9-]+)"/g,
  /\bStepSpec\(\s*"[a-z_]+",\s*"[a-z]+",\s*"[^"]*",\s*"([a-z0-9-]+)"/g,
];
const found = new Set(EXTRA_ICONS);
for (const file of sources) {
  const text = readFileSync(file, "utf8");
  for (const pattern of PATTERNS) for (const m of text.matchAll(pattern)) found.add(m[1]);
}
const ICONS = [...found].sort();
const missing = ICONS.filter((n) => !existsSync(join(here, "node_modules", "lucide-static", "icons", `${n}.svg`)));
if (missing.length) {
  console.error(`Icones Lucide inconnues : ${missing.join(", ")}`);
  process.exit(1);
}

const symbols = ICONS.map((name) => {
  const svg = readFileSync(join(here, "node_modules", "lucide-static", "icons", `${name}.svg`), "utf8");
  const inner = svg.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "")
    .replace(/<!--[\s\S]*?-->/g, "").trim();
  return `<symbol id="${name}" viewBox="0 0 24 24">${inner}</symbol>`;
});
writeFileSync(
  join(staticDir, "icons.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n${symbols.join("\n")}\n</svg>\n`,
);

mkdirSync(join(staticDir, "fonts"), { recursive: true });
for (const [pkg, file] of [
  ["@fontsource-variable/geist", "geist-latin-wght-normal.woff2"],
  ["@fontsource-variable/jetbrains-mono", "jetbrains-mono-latin-wght-normal.woff2"],
]) {
  copyFileSync(join(here, "node_modules", pkg, "files", file), join(staticDir, "fonts", file));
}
console.log(`icons.svg (${ICONS.length} icones) + polices ecrites dans ${staticDir}`);
