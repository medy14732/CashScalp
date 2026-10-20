// Usage : node scraper/cli.js "iphone 13" [--magasin ARLON] [--pages 3] [--json]
import { rechercher } from "./cashConverters.js";

const args = process.argv.slice(2);
const option = nom => {
  const i = args.indexOf(`--${nom}`);
  return i === -1 ? undefined : args.splice(i, 2)[1];
};
const magasin = option("magasin");
const maxPages = Number(option("pages") ?? 5);
const enJson = args.includes("--json");
const motCle = args.filter(a => !a.startsWith("--")).join(" ");

if (!motCle) {
  console.error('Usage : node scraper/cli.js "mot-clé" [--magasin ARLON] [--pages 3] [--json]');
  process.exit(1);
}

const annonces = await rechercher(motCle, { magasin, maxPages });
if (enJson) {
  console.log(JSON.stringify(annonces, null, 2));
} else {
  console.table(annonces.map(({ titre, prix, etat, magasin, lien }) => ({ titre, prix, etat, magasin, lien })));
  console.log(`${annonces.length} annonce(s)`);
}
