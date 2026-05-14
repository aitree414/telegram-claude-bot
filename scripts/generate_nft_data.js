/**
 * Generate NFT SVG data from collection.json
 * Produces Solidity deploy-compatible JSON with per-token metadata + SVGs.
 */
const fs = require('fs');
const path = require('path');

const COLLECTION_PATH = path.join(__dirname, '..', '..', 'OpenClaw', 'data', 'nfts', 'collection.json');
const OUTPUT_PATH = path.join(__dirname, '..', 'contracts', 'compiled', 'nft_data.json');

// ── Color tables (mirrors gallery.html) ──────────
const POKE_COLORS = {
  Electric:  { p: '#F8D030', s: '#0D0D1A', g: 'rgba(248,208,48,0.5)' },
  Fire:     { p: '#F08030', s: '#0D0500', g: 'rgba(240,128,48,0.5)' },
  Water:    { p: '#6890F0', s: '#000510', g: 'rgba(104,144,240,0.5)' },
  Grass:    { p: '#78C850', s: '#000D00', g: 'rgba(120,200,80,0.5)' },
  Psychic:  { p: '#F85888', s: '#0D0008', g: 'rgba(248,88,136,0.5)' },
  Ghost:    { p: '#705898', s: '#08000D', g: 'rgba(112,88,152,0.5)' },
  Dark:     { p: '#705848', s: '#050505', g: 'rgba(112,88,72,0.5)' },
  Dragon:   { p: '#7038F8', s: '#04000D', g: 'rgba(112,56,248,0.5)' },
};

const NEN_COLORS = {
  '強化系': { p: '#FF4444', s: '#1A0000' },
  '變化系': { p: '#44AAFF', s: '#00101A' },
  '具體化系': { p: '#FF8800', s: '#1A0800' },
  '放出系': { p: '#44DD44', s: '#001A00' },
  '操作系': { p: '#8888FF', s: '#08001A' },
  '特質系': { p: '#DD44DD', s: '#1A001A' },
};

// ── Mona Lisa base SVG parts (shared) ──────────
function monaLisaSilhouette() {
  return `<path d="M 148 130 Q 142 108 158 96 Q 178 80 200 78 Q 222 80 242 96 Q 258 108 252 130 Q 260 152 265 180 Q 270 208 268 230 Q 266 248 260 258 Q 254 272 244 278 Q 222 290 200 292 Q 178 290 156 278 Q 146 272 140 258 Q 134 248 132 230 Q 130 208 135 180 Q 140 152 148 130 Z" fill="#0a0a12" opacity="0.85"/>
<path d="M 148 130 Q 140 168 136 200 Q 133 225 138 248" fill="none" stroke="#1a1a2e" stroke-width="1.5" opacity="0.4"/>
<path d="M 252 130 Q 260 168 264 200 Q 267 225 262 248" fill="none" stroke="#1a1a2e" stroke-width="1.5" opacity="0.4"/>
<path d="M 200 78 Q 197 120 195 160 Q 193 190 196 210" fill="none" stroke="#1a1a2e" stroke-width="1.2" opacity="0.3"/>
<ellipse cx="172" cy="180" rx="10" ry="4" fill="#e8e6f0" opacity="0.85"/>
<ellipse cx="228" cy="180" rx="10" ry="4" fill="#e8e6f0" opacity="0.85"/>
<circle cx="175" cy="180" r="3" fill="#0a0a12" opacity="0.6"/>
<circle cx="225" cy="180" r="3" fill="#0a0a12" opacity="0.6"/>
<path d="M 162 170 Q 172 166 182 170" fill="none" stroke="#e8e6f0" stroke-width="1.2" opacity="0.35"/>
<path d="M 218 170 Q 228 166 238 170" fill="none" stroke="#e8e6f0" stroke-width="1.2" opacity="0.35"/>
<path d="M 200 178 Q 197 195 200 204" fill="none" stroke="#e8e6f0" stroke-width="1.5" opacity="0.3"/>
<path d="M 182 216 Q 192 222 200 224 Q 208 222 218 216" fill="none" stroke="#e8e6f0" stroke-width="2" opacity="0.75"/>
<path d="M 186 220 Q 192 224 200 226 Q 208 224 214 220" fill="none" stroke="#e8e6f0" stroke-width="0.8" opacity="0.3"/>
<path d="M 158 260 Q 162 276 176 282 Q 190 286 200 282 Q 210 286 224 282 Q 238 276 242 260 Q 238 254 224 258 Q 210 262 200 258 Q 190 262 176 258 Q 162 254 158 260 Z" fill="#0a0a12" opacity="0.7"/>
<path d="M 176 282 L 178 288" fill="none" stroke="#0a0a12" stroke-width="1" opacity="0.3"/>
<path d="M 224 282 L 222 288" fill="none" stroke="#0a0a12" stroke-width="1" opacity="0.3"/>
<path d="M 152 276 Q 160 305 176 325 Q 190 340 200 344 Q 210 340 224 325 Q 240 305 248 276" fill="none" stroke="#0a0a12" stroke-width="2" opacity="0.4"/>`;
}

// ── Pokemon overlays (mirrors gallery.html pokemonSVG) ──
function pokemonOverlay(pokemon, c) {
  const overlays = {
    'Pikachu': `<path d="M 120 50 L 100 10 L 140 50 Z" fill="${c.p}" opacity="0.9"/><path d="M 280 50 L 300 10 L 260 50 Z" fill="${c.p}" opacity="0.9"/><path d="M 108 20 L 100 10 L 118 25 Z" fill="#222" opacity="0.7"/><path d="M 292 20 L 300 10 L 282 25 Z" fill="#222" opacity="0.7"/><path d="M 200 12 L 220 55 L 200 48 L 225 80" fill="none" stroke="${c.p}" stroke-width="3" opacity="0.9"/><path d="M 185 25 L 198 55 L 185 50 L 200 72" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.6"/><path d="M 215 25 L 202 55 L 215 50 L 200 72" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.6"/><circle cx="158" cy="205" r="14" fill="${c.p}" opacity="0.3"/><circle cx="242" cy="205" r="14" fill="${c.p}" opacity="0.3"/>`,
    'Charizard': `<path d="M 20 300 Q -20 140 70 90 Q 120 60 150 130 Q 90 200 50 330 Z" fill="${c.p}" opacity="0.3"/><path d="M 380 300 Q 420 140 330 90 Q 280 60 250 130 Q 310 200 350 330 Z" fill="${c.p}" opacity="0.3"/><path d="M 70 90 Q 50 170 40 250" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.5"/><path d="M 330 90 Q 350 170 360 250" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.5"/><ellipse cx="200" cy="360" rx="14" ry="20" fill="#FF6600" opacity="0.5"/><ellipse cx="200" cy="355" rx="8" ry="12" fill="#FFCC00" opacity="0.6"/><path d="M 200 375 Q 195 395 200 400 Q 205 395 200 375" fill="#FF6600" opacity="0.4"/>`,
    'Blastoise': `<rect x="112" y="242" width="20" height="44" rx="4" fill="#444" opacity="0.8" stroke="${c.p}" stroke-width="1.5"/><rect x="268" y="242" width="20" height="44" rx="4" fill="#444" opacity="0.8" stroke="${c.p}" stroke-width="1.5"/><rect x="105" y="238" width="34" height="14" rx="4" fill="#555" opacity="0.9" stroke="${c.p}" stroke-width="1"/><rect x="261" y="238" width="34" height="14" rx="4" fill="#555" opacity="0.9" stroke="${c.p}" stroke-width="1"/><path d="M 105 245 L 65 235 L 70 250 Z" fill="${c.p}" opacity="0.7"/><path d="M 295 245 L 335 235 L 330 250 Z" fill="${c.p}" opacity="0.7"/><path d="M 172 282 Q 200 330 228 282" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.4"/><path d="M 178 294 Q 200 340 222 294" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.25"/>`,
    'Venusaur': `<ellipse cx="200" cy="65" rx="65" ry="38" fill="${c.p}" opacity="0.18"/><ellipse cx="200" cy="65" rx="45" ry="28" fill="#FF6699" opacity="0.15"/><ellipse cx="200" cy="68" rx="25" ry="16" fill="#FFCC00" opacity="0.12"/>${[0,1,2,3,4,5].map(i => '<ellipse cx="' + (200 + Math.cos(i*Math.PI/3)*45) + '" cy="' + (65 + Math.sin(i*Math.PI/3)*25) + '" rx="22" ry="10" fill="' + c.p + '" opacity="0.12" transform="rotate(' + (i*60) + ',' + (200 + Math.cos(i*Math.PI/3)*45) + ',' + (65 + Math.sin(i*Math.PI/3)*25) + ')"/>').join('')}<path d="M 148 140 Q 110 190 100 250" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.5"/><path d="M 252 140 Q 290 190 300 250" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.5"/><ellipse cx="105" cy="230" rx="12" ry="5" fill="${c.p}" opacity="0.4" transform="rotate(-30,105,230)"/><ellipse cx="295" cy="230" rx="12" ry="5" fill="${c.p}" opacity="0.4" transform="rotate(30,295,230)"/>`,
    'Mewtwo': `<path d="M 200 340 Q 150 400 130 370 Q 110 340 125 310" fill="none" stroke="${c.p}" stroke-width="5" opacity="0.4"/><ellipse cx="200" cy="220" rx="110" ry="120" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.2"><animateTransform attributeName="transform" type="rotate" from="0 200 220" to="360 200 220" dur="6s" repeatCount="indefinite"/></ellipse><ellipse cx="200" cy="220" rx="85" ry="95" fill="none" stroke="${c.p}" stroke-width="0.8" opacity="0.12"><animateTransform attributeName="transform" type="rotate" from="360 200 220" to="0 200 220" dur="4s" repeatCount="indefinite"/></ellipse><circle cx="200" cy="170" r="12" fill="${c.p}" opacity="0.2"><animate attributeName="opacity" values="0.2;0.4;0.2" dur="2s" repeatCount="indefinite"/></circle>`,
    'Gengar': `<path d="M 140 110 Q 110 70 95 110 Z" fill="${c.p}" opacity="0.6"/><path d="M 260 110 Q 290 70 305 110 Z" fill="${c.p}" opacity="0.6"/><path d="M 165 245 Q 200 275 235 245" fill="none" stroke="${c.p}" stroke-width="3.5" opacity="0.7"/><path d="M 170 252 Q 200 278 230 252" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.4"/><path d="M 155 275 Q 145 340 170 360 Q 200 380 230 360 Q 255 340 245 275" fill="${c.p}" opacity="0.12"/><path d="M 168 360 Q 182 348 200 360 Q 218 348 232 360" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.25"/>`,
    'Mew': `<path d="M 200 300 Q 230 340 270 310 Q 310 280 330 250 Q 350 220 370 240" fill="none" stroke="${c.p}" stroke-width="4" opacity="0.45"/><path d="M 270 310 Q 290 290 310 260" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.3"/>${[[110,90],[290,80],[125,310],[275,320],[310,150],[90,170]].map(([x,y]) => '<text x="' + x + '" y="' + y + '" text-anchor="middle" font-size="20" fill="' + c.p + '" opacity="0.4">✦</text>').join('')}<circle cx="90" cy="220" r="6" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.25"/><circle cx="310" cy="140" r="5" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.25"/>`,
    'Lugia': `<path d="M 200 120 Q 80 30 20 180 Q -10 280 30 350" fill="none" stroke="${c.p}" stroke-width="3.5" opacity="0.4"/><path d="M 200 120 Q 320 30 380 180 Q 410 280 370 350" fill="none" stroke="${c.p}" stroke-width="3.5" opacity="0.4"/><path d="M 70 90 Q 30 60 10 120 Q 0 170 30 190" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.25"/><path d="M 330 90 Q 370 60 390 120 Q 400 170 370 190" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.25"/><path d="M 30 420 Q 100 390 200 410 Q 300 390 370 420" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.25"/>`,
    'Umbreon': `<path d="M 148 110 L 125 40 L 158 100 Z" fill="#222" opacity="0.8" stroke="${c.p}" stroke-width="1.2"/><path d="M 252 110 L 275 40 L 242 100 Z" fill="#222" opacity="0.8" stroke="${c.p}" stroke-width="1.2"/><circle cx="200" cy="105" r="18" fill="none" stroke="${c.g}" stroke-width="3" opacity="0.7"><animate attributeName="r" values="18;22;18" dur="2.5s" repeatCount="indefinite"/></circle><circle cx="152" cy="145" r="10" fill="none" stroke="${c.g}" stroke-width="2" opacity="0.5"/><circle cx="248" cy="145" r="10" fill="none" stroke="${c.g}" stroke-width="2" opacity="0.5"/><circle cx="340" cy="70" r="30" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.15"/><text x="340" y="78" text-anchor="middle" font-size="30" fill="${c.p}" opacity="0.15">🌙</text>`,
    'Rayquaza': `<path d="M 10 40 Q 50 20 90 50 Q 130 80 180 50 Q 230 20 280 60 Q 330 100 370 70 Q 390 60 395 85" fill="none" stroke="${c.p}" stroke-width="4.5" opacity="0.35"/><path d="M 10 40 Q 50 20 90 50 Q 130 80 180 50 Q 230 20 280 60 Q 330 100 370 70 Q 390 60 395 85" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.6"/>${[80, 160, 250, 340].map(x => '<path d="M ' + x + ' ' + (x < 200 ? 50+x*0.03 : 65-x*0.03) + ' L ' + (x-12) + ' ' + (x < 200 ? 38 : 52) + ' L ' + (x+12) + ' ' + (x < 200 ? 38 : 52) + ' Z" fill="' + c.p + '" opacity="0.3"/>').join('')}<ellipse cx="80" cy="420" rx="70" ry="8" fill="${c.p}" opacity="0.08"/><ellipse cx="320" cy="400" rx="60" ry="6" fill="${c.p}" opacity="0.06"/>`,
  };
  return overlays[pokemon] || '';
}

// ── HxH overlays (mirrors gallery.html hxhSVG) ──
function hxhOverlay(char, c) {
  const overlays = {
    'Gon Freecss': `<path d="M 155 270 Q 160 300 170 320 Q 185 345 200 348 Q 215 345 230 320 Q 240 300 245 270" fill="#2ECC71" opacity="0.12"/><path d="M 155 270 Q 160 300 170 320 Q 185 345 200 348 Q 215 345 230 320 Q 240 300 245 270" fill="none" stroke="#2ECC71" stroke-width="1.2" opacity="0.4"/><line x1="200" y1="275" x2="200" y2="140" stroke="#8B4513" stroke-width="2" opacity="0.5"/><line x1="200" y1="140" x2="240" y2="100" stroke="#8B4513" stroke-width="1.5" opacity="0.4"/><line x1="240" y1="100" x2="280" y2="130" stroke="#CCC" stroke-width="0.5" opacity="0.3"/>`,
    'Killua Zoldyck': `${[[160,100],[240,100],[140,180],[260,180],[150,280],[250,280]].map(([x,y]) => `<path d="M ${x} ${y} L ${x+15} ${y-20} L ${x+5} ${y-10} L ${x+20} ${y-30}" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.35"/>`).join('')}<circle cx="200" cy="240" r="100" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.12" stroke-dasharray="4,6"><animateTransform attributeName="transform" type="rotate" from="0 200 240" to="360 200 240" dur="3s" repeatCount="indefinite"/></circle>`,
    'Kurapika': `<circle cx="178" cy="182" r="8" fill="#FF0000" opacity="0.3"><animate attributeName="opacity" values="0.3;0.6;0.3" dur="1.5s" repeatCount="indefinite"/></circle><circle cx="222" cy="182" r="8" fill="#FF0000" opacity="0.3"><animate attributeName="opacity" values="0.3;0.6;0.3" dur="1.5s" repeatCount="indefinite"/></circle><path d="M 155 260 Q 138 275 148 292 Q 158 308 175 298" fill="none" stroke="#FFD700" stroke-width="2.5" opacity="0.55" stroke-dasharray="3,2"/><path d="M 245 260 Q 262 275 252 292 Q 242 308 225 298" fill="none" stroke="#FFD700" stroke-width="2.5" opacity="0.55" stroke-dasharray="3,2"/>`,
    'Hisoka': `<path d="M 174 195 L 180 190 L 178 198 Z" fill="${c.p}" opacity="0.35"/><path d="M 226 195 L 220 190 L 222 198 Z" fill="${c.p}" opacity="0.35"/><path d="M 200 208 L 203 216 L 197 216 Z" fill="${c.p}" opacity="0.25"/><rect x="76" y="280" width="22" height="30" rx="2" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.35" transform="rotate(-15,87,295)"/><rect x="302" y="248" width="22" height="30" rx="2" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.35" transform="rotate(20,313,263)"/>`,
    'Chrollo Lucilfer': `<ellipse cx="200" cy="178" rx="22" ry="28" fill="none" stroke="#333" stroke-width="2" opacity="0.55"/><path d="M 183 166 Q 200 155 217 166" fill="none" stroke="#333" stroke-width="1.2" opacity="0.45"/><path d="M 188 190 Q 200 202 212 190" fill="none" stroke="#333" stroke-width="1.2" opacity="0.45"/>${[1,2,3,4].map(i => {const ang = i*Math.PI/2.5; return '<line x1="' + (200 + Math.cos(ang)*22) + '" y1="' + (178 + Math.sin(ang)*28) + '" x2="' + (200 + Math.cos(ang)*38) + '" y2="' + (178 + Math.sin(ang)*38) + '" stroke="#333" stroke-width="1" opacity="0.35"/>'}).join('')}<circle cx="200" cy="178" r="3.5" fill="#333" opacity="0.35"/><line x1="168" y1="172" x2="188" y2="190" stroke="#FF0000" stroke-width="1.5" opacity="0.45"/><line x1="188" y1="172" x2="168" y2="190" stroke="#FF0000" stroke-width="1.5" opacity="0.45"/>`,
    'Meruem': `<circle cx="200" cy="240" r="100" fill="none" stroke="${c.p}" stroke-width="1.5" opacity="0.12"/><circle cx="200" cy="240" r="80" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.1"/><circle cx="200" cy="240" r="60" fill="none" stroke="#FFD700" stroke-width="1" opacity="0.18"><animate attributeName="r" values="60;65;60" dur="2s" repeatCount="indefinite"/></circle><path d="M 200 280 Q 240 350 290 320 Q 310 310 300 275" fill="none" stroke="${c.p}" stroke-width="4" opacity="0.35"/><path d="M 180 85 L 190 68 L 200 82 L 210 68 L 220 85" fill="none" stroke="#FFD700" stroke-width="2" opacity="0.45"/>`,
    'Isaac Netero': `${Array.from({length:12}, (_, i) => {const side = i%2===0?-1:1; const row = Math.floor(i/2); const xOff=side*(40+row*25); const yOff=-20+row*30; return '<path d="M 200 240 Q ' + (200+xOff/2) + ' ' + (240+yOff/2) + ' ' + (200+xOff) + ' ' + (240+yOff) + '" fill="none" stroke="' + c.p + '" stroke-width="1.2" opacity="' + (0.18-row*0.025) + '"/>'}).join('')}<circle cx="200" cy="240" r="90" fill="none" stroke="${c.p}" stroke-width="0.8" opacity="0.1" stroke-dasharray="2,4"/>`,
    'Leorio Paradinight': `<path d="M 170 270 L 185 295 L 200 290 L 215 295 L 230 270" fill="none" stroke="#2C3E50" stroke-width="1.5" opacity="0.4"/><path d="M 192 270 L 196 295 L 200 300 L 204 295 L 208 270" fill="#E74C3C" opacity="0.2"/><path d="M 235 265 Q 245 255 252 250" fill="none" stroke="${c.p}" stroke-width="2" opacity="0.5"/>`,
    'Biscuit Krueger': `<g opacity="0.18"><path d="M 155 135 Q 150 115 165 105 Q 185 90 200 88 Q 215 90 235 105 Q 250 115 245 135" fill="none" stroke="#FF69B4" stroke-width="2" opacity="0.5"/><path d="M 150 260 Q 160 310 200 348 Q 240 310 250 260" fill="none" stroke="#FF69B4" stroke-width="1.5" opacity="0.3"/></g><circle cx="100" cy="100" r="45" fill="#FF69B4" opacity="0.05"/><circle cx="300" cy="400" r="55" fill="#8B4513" opacity="0.05"/>`,
    'Feitan Portor': `<line x1="245" y1="100" x2="245" y2="340" stroke="#333" stroke-width="2.5" opacity="0.5"/><path d="M 222 102 Q 245 90 268 102 Q 255 108 245 104 Q 235 108 222 102 Z" fill="#333" opacity="0.35"/><circle cx="200" cy="160" r="35" fill="none" stroke="#FF4500" stroke-width="1" opacity="0.18"><animate attributeName="r" values="35;48;35" dur="2s" repeatCount="indefinite"/></circle><circle cx="200" cy="160" r="18" fill="#FF4500" opacity="0.1"><animate attributeName="r" values="18;30;18" dur="2s" repeatCount="indefinite"/></circle>`,
    'Illumi Zoldyck': `${[[170,140,25],[230,140,25],[160,200,20],[240,200,20],[200,130,30]].map(([x,y,len]) => `<line x1="${x}" y1="${y}" x2="${x + (x-200)*0.3}" y2="${y - len}" stroke="${c.p}" stroke-width="1.5" opacity="0.35"/><circle cx="${x + (x-200)*0.3}" cy="${y - len}" r="2" fill="${c.p}" opacity="0.25"/>`).join('')}<rect x="60" y="380" width="280" height="4" fill="${c.p}18"/><rect x="80" y="400" width="240" height="3" fill="${c.p}12"/><rect x="100" y="420" width="200" height="2" fill="${c.p}0A"/>`,
    'Ging Freecss': `<rect x="100" y="340" width="30" height="60" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.18"/><rect x="270" y="350" width="25" height="50" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.15"/><polygon points="110,340 115,325 120,340" fill="none" stroke="${c.p}" stroke-width="0.8" opacity="0.18"/><polygon points="277,350 282,335 288,350" fill="none" stroke="${c.p}" stroke-width="0.8" opacity="0.15"/><rect x="190" y="265" width="20" height="15" rx="2" fill="none" stroke="${c.p}" stroke-width="1" opacity="0.35"/><circle cx="320" cy="130" r="3.5" fill="${c.p}" opacity="0.18"/><path d="M 320 133 L 320 140 L 317 145 M 320 140 L 323 145" fill="none" stroke="${c.p}" stroke-width="0.8" opacity="0.15"/>`,
  };
  return overlays[char] || '';
}

// ── Full SVGs ────────────────────────────────

function generatePokemonSVG(pokemon, type, rarity) {
  const c = POKE_COLORS[type] || POKE_COLORS.Psychic;
  const glow = rarity === 'legendary' ? 'rgba(255,107,53,0.6)' : rarity === 'mythic' ? 'rgba(187,107,217,0.6)' : c.g;
  const starN = rarity === 'legendary' ? 5 : rarity === 'mythic' ? 4 : 3;
  const overlay = pokemonOverlay(pokemon, c);

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 560" width="400" height="560">
<defs>
<radialGradient id="bg" cx="50%" cy="50%" r="75%">
  <stop offset="0%" stop-color="#1a1a2e"/>
  <stop offset="100%" stop-color="${c.s}"/>
</radialGradient>
<radialGradient id="aura" cx="50%" cy="48%" r="45%">
  <stop offset="0%" stop-color="${c.p}25"/>
  <stop offset="100%" stop-color="${c.p}00"/>
</radialGradient>
<filter id="g">
  <feGaussianBlur stdDeviation="3" result="b"/>
  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
</defs>
<rect width="400" height="560" fill="url(#bg)"/>
<rect x="8" y="8" width="384" height="544" fill="none" stroke="${c.p}55" stroke-width="1.5" rx="5"/>
<rect x="12" y="12" width="376" height="536" fill="none" stroke="${c.p}33" stroke-width="0.5" rx="4"/>
<path d="M 0 340 Q 80 290 180 320 Q 280 350 400 310 L 400 560 L 0 560 Z" fill="${c.p}0C"/>
<path d="M 0 370 Q 100 330 220 355 Q 340 380 400 350 L 400 560 L 0 560 Z" fill="${c.p}08"/>
<path d="M 0 410 Q 130 370 250 400 Q 370 430 400 390 L 400 560 L 0 560 Z" fill="${c.p}05"/>
<path d="M 190 490 Q 180 440 195 410 Q 215 380 200 350" fill="none" stroke="${c.p}44" stroke-width="2.5" stroke-dasharray="4,3"/>
<circle cx="200" cy="350" r="4" fill="${c.p}55"/>
<ellipse cx="200" cy="230" rx="140" ry="155" fill="url(#aura)"/>
<g filter="url(#g)">
${monaLisaSilhouette()}
</g>
<g filter="url(#g)">
${overlay}
</g>
<rect x="18" y="18" width="54" height="22" rx="4" fill="${c.p}33" stroke="${c.p}66" stroke-width="0.8"/>
<text x="45" y="33" text-anchor="middle" font-family="'Orbitron',monospace" font-size="10" fill="${c.p}" opacity="0.8">${type.toUpperCase()}</text>
<rect x="120" y="428" width="160" height="26" rx="13" fill="${c.p}22" stroke="${c.p}44" stroke-width="0.8"/>
<text x="200" y="446" text-anchor="middle" font-family="'Orbitron',monospace" font-size="10" fill="${c.p}" letter-spacing="2" opacity="0.8">${pokemon.toUpperCase()}</text>
<text x="200" y="485" text-anchor="middle" font-family="monospace" font-size="8" fill="#7a78a0" opacity="0.35">0x...MonaLisaNFT</text>
<text x="200" y="515" text-anchor="middle" fill="${glow}" font-size="15" font-family="monospace" opacity="0.65">${'★'.repeat(starN)}${'☆'.repeat(5-starN)}</text>
<text x="200" y="540" text-anchor="middle" font-family="'Orbitron',monospace" font-size="9" fill="${glow}" letter-spacing="3" opacity="0.5">${rarity.toUpperCase()}</text>
</svg>`;
}

function generateHxHSVG(char, nen, rarity) {
  const c = NEN_COLORS[nen] || { p: '#FFD700', s: '#1A1400' };
  const glow = rarity === 'legendary' ? 'rgba(255,107,53,0.6)' : rarity === 'mythic' ? 'rgba(187,107,217,0.6)' : c.p + '88';
  const starN = rarity === 'legendary' ? 5 : rarity === 'mythic' ? 4 : 3;
  const overlay = hxhOverlay(char, c);

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 560" width="400" height="560">
<defs>
<radialGradient id="bg" cx="50%" cy="50%" r="75%">
  <stop offset="0%" stop-color="#1a1a2e"/>
  <stop offset="100%" stop-color="${c.s}"/>
</radialGradient>
<radialGradient id="aura" cx="50%" cy="48%" r="45%">
  <stop offset="0%" stop-color="${c.p}25"/>
  <stop offset="100%" stop-color="${c.p}00"/>
</radialGradient>
<filter id="g">
  <feGaussianBlur stdDeviation="3" result="b"/>
  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
</defs>
<rect width="400" height="560" fill="url(#bg)"/>
<rect x="8" y="8" width="384" height="544" fill="none" stroke="${c.p}55" stroke-width="1.5" rx="5"/>
<rect x="12" y="12" width="376" height="536" fill="none" stroke="${c.p}33" stroke-width="0.5" rx="4"/>
<path d="M 0 340 Q 80 290 180 320 Q 280 350 400 310 L 400 560 L 0 560 Z" fill="${c.p}0C"/>
<path d="M 0 370 Q 100 330 220 355 Q 340 380 400 350 L 400 560 L 0 560 Z" fill="${c.p}08"/>
<ellipse cx="200" cy="230" rx="140" ry="155" fill="url(#aura)"/>
<g filter="url(#g)">
${monaLisaSilhouette()}
</g>
<g filter="url(#g)">
${overlay}
</g>
<rect x="18" y="18" width="54" height="22" rx="4" fill="${c.p}33" stroke="${c.p}66" stroke-width="0.8"/>
<text x="45" y="33" text-anchor="middle" font-family="'Orbitron',monospace" font-size="9" fill="${c.p}" opacity="0.8">${nen}</text>
<rect x="100" y="428" width="200" height="26" rx="13" fill="${c.p}22" stroke="${c.p}44" stroke-width="0.8"/>
<text x="200" y="446" text-anchor="middle" font-family="'Orbitron',monospace" font-size="9" fill="${c.p}" letter-spacing="1" opacity="0.8">${char.toUpperCase()}</text>
<text x="200" y="485" text-anchor="middle" font-family="monospace" font-size="8" fill="#7a78a0" opacity="0.35">0x...MonaLisaNFT</text>
<text x="200" y="515" text-anchor="middle" fill="${glow}" font-size="15" font-family="monospace" opacity="0.65">${'★'.repeat(starN)}${'☆'.repeat(5-starN)}</text>
<text x="200" y="540" text-anchor="middle" font-family="'Orbitron',monospace" font-size="9" fill="${glow}" letter-spacing="3" opacity="0.5">${rarity.toUpperCase()}</text>
</svg>`;
}

// ── Main ──────────────────────────────────────

function main() {
  const raw = JSON.parse(fs.readFileSync(COLLECTION_PATH, 'utf-8'));
  const ethToWei = (eth) => Math.round(eth * 1e18).toString();

  const tokens = [];

  // Pokemon collection (tokenId 0-9)
  const pokeCol = raw.collections.find(c => c.slug === 'pokemon');
  if (pokeCol) {
    for (const nft of pokeCol.nfts) {
      const type = nft.attributes?.type || 'Psychic';
      tokens.push({
        name: nft.name,
        character: nft.pokemon,
        charType: type,
        rarity: nft.rarity,
        price: ethToWei(nft.price_eth),
        svg: generatePokemonSVG(nft.pokemon, type, nft.rarity),
      });
    }
  }

  // HxH collection (tokenId 10-21)
  const hxhCol = raw.collections.find(c => c.slug === 'hxh');
  if (hxhCol) {
    for (const nft of hxhCol.nfts) {
      tokens.push({
        name: nft.name,
        character: nft.char,
        charType: nft.nen,
        rarity: nft.rarity,
        price: ethToWei(nft.price_eth),
        svg: generateHxHSVG(nft.char, nft.nen, nft.rarity),
      });
    }
  }

  console.log(`Generated ${tokens.length} tokens`);
  console.log(`Pokemon: ${tokens.filter(t => t.rarity).length} (IDs 0-9)`);
  console.log(`HxH: ${tokens.filter(t => t.rarity).length - 10} (IDs 10-21)`);

  // Minify SVGs: strip whitespace between tags to reduce size
  const minifySvg = (svg) => svg.replace(/>\s+</g, '><').replace(/\n\s*/g, '');

  const out = {
    name: 'MonaLisaNFT',
    symbol: 'MLNFT',
    tokens: tokens.map(t => ({
      name: t.name,
      character: t.character,
      charType: t.charType,
      rarity: t.rarity,
      price: t.price,
      svg: minifySvg(t.svg),
    })),
  };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(out, null, 2));
  console.log(`\nSaved to ${OUTPUT_PATH}`);

  // Print stats
  const sizes = tokens.map(t => t.svg.length);
  console.log(`\nSVG sizes: min=${Math.min(...sizes)} max=${Math.max(...sizes)} avg=${Math.round(sizes.reduce((a,b)=>a+b,0)/sizes.length)}`);
  console.log(`Total SVG data: ${sizes.reduce((a,b)=>a+b,0)} bytes`);
}

main();
