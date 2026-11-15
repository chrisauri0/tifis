// Parses "08h55m10.8s -07d14m42s", "08:55:10.8 -07:14:42", "08 55 10.8 -07 14 42"
// or decimal degrees "133.795 -7.245". Returns {ra, dec} in degrees or null.
export function parseCoords(input) {
  const s = input.trim()
    .replace(/[−–]/g, '-')
    .replace(/[°º]/g, 'd')
    .replace(/[′']/g, 'm')
    .replace(/[″"]/g, 's')
    .replace(/,/g, ' ');
  if (!/^[\d\s.:+\-hdms]+$/i.test(s)) return null;
  const nums = (part) => [...part.matchAll(/\d+(?:\.\d+)?/g)].map((m) => parseFloat(m[0]));

  // Dec starts at its sign; without one, split the numbers in half.
  let raNums, decNums, neg = false;
  const signAt = s.search(/(?<=\S\s*)[+-]/);
  if (signAt > 0) {
    raNums = nums(s.slice(0, signAt));
    decNums = nums(s.slice(signAt));
    neg = s[signAt] === '-';
  } else if (s.split(/\s+/).length === 2) {
    [raNums, decNums] = s.split(/\s+/).map(nums);
  } else {
    const all = nums(s);
    if (all.length % 2) return null;
    raNums = all.slice(0, all.length / 2);
    decNums = all.slice(all.length / 2);
  }
  if (!raNums.length || !decNums.length || raNums.length > 3 || decNums.length > 3) return null;

  const sexa = (v) => v[0] + (v[1] ?? 0) / 60 + (v[2] ?? 0) / 3600;
  const degrees = raNums.length === 1 && decNums.length === 1 && !/[hms:]/i.test(s);
  const ra = degrees ? raNums[0] : 15 * sexa(raNums);
  const dec = (neg ? -1 : 1) * (degrees ? decNums[0] : sexa(decNums));
  if (!(ra >= 0 && ra < 360 && dec >= -90 && dec <= 90)) return null;
  return { ra, dec };
}

const pad = (n, w, d = 0) => n.toFixed(d).padStart(w + (d ? d + 1 : 0), '0');

export function formatRA(ra) {
  let s = ((ra % 360) + 360) % 360 / 15 * 3600;
  s = Math.round(s * 10) / 10;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${pad(h, 2)}h${pad(m, 2)}m${pad(s % 60, 2, 1)}s`;
}

export function formatDec(dec) {
  const sign = dec < 0 ? '−' : '+';
  let s = Math.round(Math.abs(dec) * 3600);
  const d = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${sign}${pad(d, 2)}°${pad(m, 2)}′${pad(s % 60, 2)}″`;
}
