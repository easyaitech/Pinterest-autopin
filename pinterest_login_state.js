function classifyPinterestLoginState(state) {
  const url = String(state?.url || '');
  const loginWall = Boolean(state?.loginWall);
  const hasCreateSurface = Boolean(state?.hasCreateSurface);
  if (loginWall || redirectedAwayFromCreateSurface(url)) {
    return { ok: false, reason: `Pinterest login required at ${url}` };
  }
  if (hasCreateSurface && isPinterestCreateRoute(url)) {
    return { ok: true, reason: '' };
  }
  return { ok: false, reason: `Pinterest create surface not detected at ${url}` };
}

function isPinterestHost(hostname) {
  const host = String(hostname || '').toLowerCase();
  return host === 'pinterest.com' || host.endsWith('.pinterest.com');
}

function isPinterestCreateRoute(url) {
  try {
    const parsed = new URL(url);
    return (
      isPinterestHost(parsed.hostname) &&
      (
        parsed.pathname.includes('/pin-creation-tool') ||
        parsed.pathname.includes('/pin-builder')
      )
    );
  } catch (_error) {
    return false;
  }
}

function redirectedAwayFromCreateSurface(url) {
  try {
    const parsed = new URL(url);
    return isPinterestHost(parsed.hostname) && !isPinterestCreateRoute(url);
  } catch (_error) {
    return false;
  }
}

function redirectedAwayFromPinBuilder(url) {
  return redirectedAwayFromCreateSurface(url);
}

module.exports = {
  classifyPinterestLoginState,
  isPinterestHost,
  isPinterestCreateRoute,
  redirectedAwayFromCreateSurface,
  redirectedAwayFromPinBuilder
};
