export function fmt(v) {
  if (Math.abs(v) >= 100) return v.toFixed(1);
  if (Math.abs(v) >= 10)  return v.toFixed(2);
  return v.toFixed(3);
}

export function scaleUnits(mu, sigma, unit) {
  if (unit === 'MJ/K') return [mu / 1e6, sigma / 1e6, 'MJ/K'];
  return [mu, sigma, unit];
}
