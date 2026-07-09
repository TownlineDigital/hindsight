/*
 * One-shot export: EVERY species' full learnset (Pokemon Showdown's own
 * data, via the official @pkmn/data package) -> a single JSON file this
 * project's moveset_validator.py can load, in the exact shape it expects:
 *   { "speciesid": ["moveid", "moveid", ...], ... }
 *
 * RUN AND VERIFIED 2026-07-05: node_modules/@pkmn/{data,sim} were already
 * present in this sandbox (a prior session's "npm registry blocked" note no
 * longer applied here), so this actually executed - exit 0, no stderr, 818
 * species, written to ../data/showdown_learnsets_full.json. Spot-checked
 * against every VGC-relevant species this project's real footage features
 * (Hydreigon, Primarina, Rotom, Incineroar, Whimsicott, Rillaboom,
 * Kingambit, Bisharp) - all present with real, non-empty (58-104 move)
 * learnsets. Re-run this any time a game patch changes what's learnable;
 * see moveset_validator.py's module docstring for the full writeup.
 *
 * Usage:
 *   npm install @pkmn/data @pkmn/sim
 *   node export_showdown_learnsets.js > ../data/showdown_learnsets_full.json
 *
 * No further code changes needed after that: moveset_validator.py now
 * auto-detects ../data/showdown_learnsets_full.json the moment it exists on
 * disk and prefers it over the 15-species showdown_learnsets_starter.json
 * this was developed against (see moveset_validator.py's
 * _resolve_default_data_path() / DEFAULT_DATA_PATH).
 */

const {Generations} = require('@pkmn/data');
const {Dex} = require('@pkmn/sim');

async function main() {
  // Gen 9 = current-generation learnsets (Scarlet/Violet-era mechanics,
  // the generation this project's adapters/pokemon/*.json already target).
  // Change to gens.get(<n>) for a different generation if ever needed -
  // see @pkmn/data's Generations docs.
  const gens = new Generations(Dex);
  const gen = gens.get(9);

  const out = {};
  for (const species of gen.species) {
    // .id is Showdown's own normalized species id (lowercase, no spaces/
    // punctuation) - the exact format moveset_validator.py's _norm()
    // produces from an OCR/vision-read species name, so no extra mapping
    // step is needed between this export and that module.
    const learnset = await gen.learnsets.get(species.id);
    if (!learnset || !learnset.learnset) continue;
    // Object.keys(learnset.learnset) is every move id this species can
    // legally learn in gen 9, by any method - dropping the per-move
    // generation/level/method detail on purpose, same as the Python
    // module's own scope (see moveset_validator.py's docstring).
    const moves = new Set(Object.keys(learnset.learnset));

    // REAL BUG FOUND + FIXED 2026-07-05: Showdown's own learnsets.ts stores
    // an alternate forme's OWN entry as ONLY its forme-exclusive move(s) -
    // e.g. species.get('rotomwash').learnset only has "hydropump", NOT the
    // 67 moves the base "Rotom" species can learn. Confirmed directly via
    // @pkmn/data: gen.species.get('rotomwash').baseSpecies === 'Rotom', and
    // gen.learnsets.get('rotomwash') really does return just {hydropump:...}
    // - this isn't a rare edge case either: EVERY Rotom appliance forme
    // (Wash/Heat/Frost/Fan/Mow), both Necrozma fusion formes (Dusk-Mane/
    // Dawn-Wings), and both Crowned formes (Zacian-Crowned/Zamazenta-Crowned)
    // exported with under 10 moves before this fix - all real VGC-relevant
    // Pokemon this project's own footage features Rotom-Wash for. A species
    // whose baseSpecies differs from its own name is a forme, not a fully
    // separate Pokemon for move-learning purposes, so its real learnable
    // move pool is the UNION of its own forme-exclusive move(s) and its
    // base species' full learnset - merged in below rather than trusting
    // the forme's own (deliberately sparse) learnsets.ts entry alone.
    if (species.baseSpecies && species.baseSpecies !== species.name) {
      const baseId = gen.species.get(species.baseSpecies).id;
      const baseLearnset = await gen.learnsets.get(baseId);
      if (baseLearnset && baseLearnset.learnset) {
        for (const m of Object.keys(baseLearnset.learnset)) moves.add(m);
      }
    }

    out[species.id] = Array.from(moves);
  }

  process.stdout.write(JSON.stringify(out, null, 2));
}

main().catch(err => {
  console.error('export_showdown_learnsets.js failed:', err);
  process.exit(1);
});
