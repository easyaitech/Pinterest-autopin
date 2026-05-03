function classifyPinterestLoginState(state) {
  const url = String(state?.url || '');
  const loginWall = Boolean(state?.loginWall);
  const hasCreateSurface = Boolean(state?.hasCreateSurface);
  if (hasCreateSurface) {
    return { ok: true, reason: '' };
  }
  if (loginWall || redirectedAwayFromPinBuilder(url)) {
    return { ok: false, reason: `Pinterest login required at ${url}` };
  }
  return { ok: false, reason: `Pinterest create surface not detected at ${url}` };
}

function redirectedAwayFromPinBuilder(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.endsWith('pinterest.com') && !parsed.pathname.includes('/pin-builder');
  } catch (_error) {
    return false;
  }
}

module.exports = {
  classifyPinterestLoginState,
  redirectedAwayFromPinBuilder
};
